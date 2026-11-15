"""Fixed actual-provider sibling process. No public account/credential/runtime issuer."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from time import monotonic
from types import TracebackType
from typing import IO
from uuid import UUID, uuid4

from auvexo_alpha.application.ds03_actual import ActualDs03Reader
from auvexo_alpha.application.ds03_ports import ActualDs03ReadPort
from auvexo_alpha.domain.ds03 import MAX_REQUESTS
from auvexo_alpha.domain.ds03_actual import (
    PROTOCOL_FAMILY,
    ActualAttestation,
    ActualAttestationPayload,
    ActualAttestRequest,
    ActualDisconnectRequest,
    ActualIdentity,
    ActualReply,
    ActualRequest,
    ActualRights,
    ActualServerTimePayload,
    ActualServerTimeRequest,
    Ds03Refusal,
    ServerTimeBasis,
    decode_actual_reply,
    decode_actual_request,
    refusal,
    require_server_time_binding,
)
from auvexo_alpha.domain.ds03_authority import (
    Ds03AuthorityAdmission,
    Ds03OnboardingAdmission,
    Ds03OnboardingAuthority,
    Ds03RuntimeBinding,
    admit_authority,
    decode_authority,
)
from auvexo_alpha.infrastructure import ds03_mt5_binding as measured
from auvexo_alpha.infrastructure.ds03_ipc import (
    Ds03ProtocolError,
    ProtocolFamily,
    bootstrap_frame,
    canonical,
    decode_frame,
    decode_outcome,
    encode_frame,
    error_payload,
    error_reason,
    new_pipe_key,
    read_bootstrap,
)
from auvexo_alpha.infrastructure.ds03_process import (
    Ds03Process,
    _bounded,
    _child_environment,
    _exchange,
    _read,
    _write,
)

_FAMILY = ProtocolFamily.MT5_READONLY


def _measurement(authority: Ds03OnboardingAuthority) -> Ds03RuntimeBinding:
    bound = authority.runtime
    return measured.measure_binding(
        accepted_release_sha=bound.release_sha,
        accepted_release_tree=bound.release_tree,
        terminal_build=bound.terminal_build,
        terminal_version=bound.terminal_version,
    )


def _rights(admission: Ds03AuthorityAdmission) -> ActualRights:
    return ActualRights(
        review_hash=admission.authority.rights_hash,
        valid_until=admission.authority.rights_valid_until,
        protocol_family=PROTOCOL_FAMILY,
        synthetic=False,
    )


def _pin_identity(observed: ActualAttestation, admission: Ds03AuthorityAdmission) -> ActualIdentity:
    identity, authority, bound = observed.identity, admission.authority, admission.binding
    native = measured.probe_terminal_process(bound)
    if (
        identity.time_basis_hash != authority.time_basis_hash
        or identity.server_offset_seconds != authority.server_offset_seconds
    ):
        raise Ds03Refusal("TIME_BASIS_MISMATCH")
    if not timedelta(0) <= datetime.now(UTC) - observed.observed_at <= timedelta(seconds=30):
        raise Ds03Refusal("ATTESTATION_STALE")
    if (
        identity.account_ref != "ds03.account." + authority.account_digest
        or identity.login_hash != authority.account_digest
        or identity.server != "ds03.server." + authority.server_digest
        or identity.account_type != authority.account_type
        or identity.account_type_source != authority.account_type_source
        or identity.currency != authority.currency
        or identity.leverage != authority.leverage
        or identity.mode != "DEMO"
        or identity.terminal_build != bound.terminal_build
        or identity.terminal_version != bound.terminal_version
        or identity.process_ref != native.process_ref
        or identity.profile_hash != native.profile_hash
        or identity.profile_hash != bound.profile_identity_hash
        or identity.release_hash != bound.connector_source_hash
        or identity.config_hash != authority.metadata_hash
        or identity.rights_hash != authority.rights_hash
        or identity.authority_hash != admission.accepted_digest
        or observed.credential_authority_hash != admission.accepted_digest
    ):
        raise Ds03Refusal("IDENTITY_DRIFT")
    return identity


class ActualDs03Process:
    """Typed static admission only; no caller-selected module/path/backend/account."""

    def __init__(self, admission: Ds03AuthorityAdmission) -> None:
        try:
            if type(admission) not in (Ds03AuthorityAdmission, Ds03OnboardingAdmission):
                raise Ds03Refusal("AUTHORITY_INVALID")
            admission.verify(datetime.now(UTC))
        except Exception as error:
            raise refusal(error, "AUTHORITY_INVALID") from None
        self._admission = admission
        # Reuse accepted pipe ownership, lock and kill/handle-disposal mechanics.
        # This holder never starts its synthetic backend and is never returned.
        self._life = Ds03Process()
        self._job: measured.ProviderJob | None = None
        self._expected: ActualIdentity | None = None

    def start(self) -> ActualDs03Process:
        life = self._life
        if not life._lock.acquire(blocking=False):
            self.close()
            raise Ds03Refusal("SESSION_CLOSED")
        try:
            self._admission.verify(datetime.now(UTC))
            if life._process is not None:
                raise Ds03Refusal("SESSION_CLOSED")
            try:
                bound = _measurement(self._admission.authority)
            except Exception as error:
                raise refusal(error, "BINDING_MISMATCH") from None
            if bound != self._admission.binding:
                raise Ds03Refusal("BINDING_MISMATCH")
            fixed_python = measured.runtime_root() / ".venv" / "Scripts" / "python.exe"
            if Path(sys.executable).absolute() != fixed_python:
                raise Ds03Refusal("INTERPRETER_MISMATCH")
            key, session, generation = new_pipe_key(), uuid4(), life._generation
            source = measured.source_binding()
            self._job = measured.provider_job()
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW | 0x00000004
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-m",
                    "auvexo_alpha.infrastructure.ds03_mt5_process",
                    "--actual-provider-child",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                cwd=measured.runtime_root(),
                env=_child_environment(),
                creationflags=flags,
                bufsize=0,
            )
            life._process, life._key, life._session = process, key, session
            life._sequence, life._seen = 1, set()
            self._job.assign(process)
            if process.stdin is None or process.stdout is None:
                raise Ds03Refusal("IPC_PROTOCOL")
            reader, writer = process.stdout, process.stdin
            context: dict[str, object] = {
                "authority": self._admission.authority.model_dump(mode="json"),
                "accepted_digest": self._admission.accepted_digest,
                "provider_job": self._job.name,
            }
            outgoing = bootstrap_frame(key, session, source, family=_FAMILY)
            outgoing += encode_frame(
                "REQUEST",
                context,
                key=key,
                session=session,
                sequence=0,
                request_id=None,
                family=_FAMILY,
            )
            raw = _bounded(lambda: _exchange(reader, writer, outgoing))
            if life._process is not process or life._generation != generation:
                raise Ds03Refusal("SESSION_CLOSED")
            hello = decode_outcome(
                raw, key=key, session=session, sequence=0, kind="HELLO", family=_FAMILY
            )
            if hello.kind == "ERROR":
                # The child's authenticated, closed reason for refusing before HELLO.
                raise Ds03Refusal(error_reason(hello))
            if hello.request_id is not None or set(hello.payload) != {
                "binding",
                "attestation",
                "rights",
            }:
                raise Ds03Refusal("IPC_PROTOCOL")
            if hello.payload["binding"] != source:
                raise Ds03Refusal("BINDING_MISMATCH")
            observed = ActualAttestation.model_validate_json(
                canonical(hello.payload["attestation"])
            )
            rights = ActualRights.model_validate_json(canonical(hello.payload["rights"]))
            if rights != _rights(self._admission):
                raise Ds03Refusal("RIGHTS_MISMATCH")
            self._expected = _pin_identity(observed, self._admission)
            self._require_current(process, session, generation, self._expected)
            return self
        except Exception as error:
            self.close()
            raise refusal(error, "IPC_PROTOCOL") from None
        finally:
            life._lock.release()

    def read(self, request: ActualRequest) -> ActualReply:
        life = self._life
        if not life._lock.acquire(blocking=False):
            self.close()
            raise Ds03Refusal("SESSION_CLOSED")
        deadline: float | None = None
        try:
            started = monotonic()
            self._admission.verify(datetime.now(UTC))
            process, session, key, generation = (
                life._process,
                life._session,
                life._key,
                life._generation,
            )
            expected = self._expected
            request = decode_actual_request(request.canonical_bytes())
            now = datetime.now(UTC)
            if (
                process is None
                or session is None
                or process.stdin is None
                or process.stdout is None
                or expected is None
                or process.poll() is not None
                or life._sequence > MAX_REQUESTS
                or request.request_id in life._seen
                or request.release_hash != expected.release_hash
                or request.config_hash != expected.config_hash
                or not request.created_at <= now < request.expires_at
            ):
                raise Ds03Refusal(
                    "SESSION_CLOSED"
                    if process is None or expected is None or process.poll() is not None
                    else "REQUEST_INVALID"
                )
            deadline = started + (request.expires_at - now).total_seconds()
            native_before = measured.probe_terminal_process(self._admission.binding)
            if (
                native_before.process_ref != expected.process_ref
                or native_before.profile_hash != expected.profile_hash
            ):
                raise Ds03Refusal("TERMINAL_IDENTITY")
            life._seen.add(request.request_id)
            sequence = life._sequence
            life._sequence += 1
            outgoing = encode_frame(
                "REQUEST",
                request.model_dump(mode="json"),
                key=key,
                session=session,
                sequence=sequence,
                request_id=request.request_id,
                family=_FAMILY,
            )
            reader, writer = process.stdout, process.stdin
            remaining = min(
                (request.expires_at - datetime.now(UTC)).total_seconds(), deadline - monotonic()
            )
            raw = _bounded(lambda: _exchange(reader, writer, outgoing), budget=remaining)
            if (
                life._process is not process
                or life._session != session
                or life._generation != generation
            ):
                raise Ds03Refusal("SESSION_CLOSED")
            frame = decode_outcome(
                raw, key=key, session=session, sequence=sequence, kind="REPLY", family=_FAMILY
            )
            if frame.request_id not in (request.request_id, None) or (
                frame.kind == "REPLY" and frame.request_id != request.request_id
            ):
                raise Ds03Refusal("IPC_PROTOCOL")
            if frame.kind == "ERROR":
                # The child closed its session; its closed reason is the diagnosis.
                raise Ds03Refusal(error_reason(frame))
            reply = decode_actual_reply(canonical(frame.payload))
            self._admission.verify(datetime.now(UTC))
            native_after = measured.probe_terminal_process(self._admission.binding)
            if native_after != native_before:
                raise Ds03Refusal("TERMINAL_IDENTITY")
            completed = datetime.now(UTC)
            if reply.envelope.identity != expected:
                raise Ds03Refusal("IDENTITY_DRIFT")
            if not request.created_at <= completed < request.expires_at or monotonic() >= deadline:
                raise Ds03Refusal("DEADLINE")
            if (
                reply.request_id != request.request_id
                or reply.operation != request.operation
                or reply.envelope.connector_hash != expected.release_hash
                or reply.envelope.synthetic is not False
                or reply.protocol_family != PROTOCOL_FAMILY
                or not request.created_at
                <= reply.envelope.received_at
                <= reply.envelope.available_at
                <= completed
            ):
                raise Ds03Refusal("REPLY_INVALID")
            self._require_current(process, session, generation, expected)
            if isinstance(request, ActualDisconnectRequest):
                remaining = min(
                    (request.expires_at - datetime.now(UTC)).total_seconds(), deadline - monotonic()
                )
                if remaining <= 0 or process.wait(timeout=remaining) != 0:
                    raise Ds03Refusal("DEADLINE" if remaining <= 0 else "SHUTDOWN_FAILED")
                if datetime.now(UTC) >= request.expires_at or monotonic() >= deadline:
                    raise Ds03Refusal("DEADLINE")
                self._require_current(process, session, generation, expected)
                self.close()
            else:
                self._require_current(process, session, generation, expected)
            return reply
        except Exception as error:
            expired = deadline is not None and monotonic() >= deadline
            self.close()
            if expired and isinstance(error, (Ds03ProtocolError, subprocess.TimeoutExpired)):
                raise Ds03Refusal("DEADLINE") from None
            raise refusal(error, "IPC_PROTOCOL") from None
        finally:
            life._lock.release()

    def _require_current(
        self,
        process: subprocess.Popen[bytes],
        session: UUID,
        generation: int,
        expected: ActualIdentity,
    ) -> None:
        life = self._life
        if (
            life._process is not process
            or life._session != session
            or life._generation != generation
            or self._expected != expected
        ):
            raise Ds03Refusal("SESSION_CLOSED")

    def _control(self, disconnect: bool) -> ActualRequest:
        expected = self._expected
        if expected is None:
            raise Ds03Refusal("SESSION_CLOSED")
        now = datetime.now(UTC)
        if disconnect:
            return ActualDisconnectRequest(
                request_id=uuid4(),
                created_at=now,
                expires_at=now + timedelta(seconds=10),
                release_hash=expected.release_hash,
                config_hash=expected.config_hash,
            )
        return ActualAttestRequest(
            request_id=uuid4(),
            created_at=now,
            expires_at=now + timedelta(seconds=10),
            release_hash=expected.release_hash,
            config_hash=expected.config_hash,
        )

    def attest(self) -> ActualAttestation:
        reply = self.read(self._control(False))
        if not isinstance(reply.payload, ActualAttestationPayload):
            self.close()
            raise Ds03Refusal("REPLY_INVALID")
        return reply.payload.attestation

    def measure_server_time(
        self,
        symbols: tuple[str, ...],
        *,
        samples: int,
        interval_ms: int,
        local_clock_evidence_hash: str,
    ) -> ServerTimeBasis:
        """Onboarding-only read: the child samples the allowlisted tick call and nothing else.

        The returned basis is re-derived from its raw samples and bound to this request; it
        confers no authority until an accepted authority binds it.
        """
        expected = self._expected
        try:
            if expected is None:
                raise Ds03Refusal("SESSION_CLOSED")
            now = datetime.now(UTC)
            request = ActualServerTimeRequest(
                request_id=uuid4(),
                created_at=now,
                expires_at=now + timedelta(seconds=10),
                release_hash=expected.release_hash,
                config_hash=expected.config_hash,
                symbols=symbols,
                samples=samples,
                interval_ms=interval_ms,
                local_clock_evidence_hash=local_clock_evidence_hash,
            )
        except Exception as error:
            self.close()
            raise refusal(error, "REQUEST_INVALID") from None
        reply = self.read(request)
        payload = reply.payload
        if not isinstance(payload, ActualServerTimePayload):
            self.close()
            raise Ds03Refusal("REPLY_INVALID")
        try:
            require_server_time_binding(request, payload, reply.envelope)
        except Exception as error:
            self.close()
            raise refusal(error, "REPLY_INVALID") from None
        return payload.basis

    def disconnect(self) -> None:
        if self._life._process is not None:
            self.read(self._control(True))

    def close(self) -> None:
        self._expected = None
        job, self._job = self._job, None
        try:
            self._life.close()
        finally:
            if job is not None:
                job.close()

    def __enter__(self) -> ActualDs03Process:
        return self.start()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()


def _write_refusal(
    writer: IO[bytes],
    error: BaseException,
    *,
    key: bytes,
    session: UUID,
    sequence: int,
    request_id: UUID | None,
) -> None:
    """Authenticated ERROR frame: fixed code plus one closed reason, never error text."""
    encoded = encode_frame(
        "ERROR",
        error_payload(refusal(error, "UNCLASSIFIED").reason),
        key=key,
        session=session,
        sequence=sequence,
        request_id=request_id,
        family=_FAMILY,
    )
    _bounded(partial(_write, writer, encoded))


def _serve_actual_session(
    reader: IO[bytes],
    writer: IO[bytes],
    *,
    key: bytes,
    session: UUID,
    port: ActualDs03ReadPort,
    rights: ActualRights,
    source_hash: str,
) -> int:
    """Private typed fake seam; native main below always supplies fixed production composition."""
    try:
        try:
            expected = port.attest()
            service = ActualDs03Reader(
                port, expected.identity, rights, clock=lambda: datetime.now(UTC)
            )
        except Exception as error:
            # Refused before HELLO: the parent receives the closed reason at sequence 0.
            _write_refusal(writer, error, key=key, session=session, sequence=0, request_id=None)
            return 2
        hello: dict[str, object] = {
            "binding": source_hash,
            "attestation": expected.model_dump(mode="json"),
            "rights": rights.model_dump(mode="json"),
        }
        encoded = encode_frame(
            "HELLO", hello, key=key, session=session, sequence=0, request_id=None, family=_FAMILY
        )
        _bounded(partial(_write, writer, encoded))
        seen: set[UUID] = set()
        for sequence in range(1, MAX_REQUESTS + 1):
            request_id: UUID | None = None
            try:
                incoming = _bounded(partial(_read, reader))
                frame = decode_frame(
                    incoming,
                    key=key,
                    session=session,
                    sequence=sequence,
                    kind="REQUEST",
                    family=_FAMILY,
                )
                request_id = frame.request_id
                request = decode_actual_request(canonical(frame.payload))
                if request_id != request.request_id or request.request_id in seen:
                    raise Ds03Refusal("REQUEST_INVALID")
                seen.add(request.request_id)
                reply = service.read(request, now=datetime.now(UTC))
                encoded = encode_frame(
                    "REPLY",
                    reply.model_dump(mode="json"),
                    key=key,
                    session=session,
                    sequence=sequence,
                    request_id=request_id,
                    family=_FAMILY,
                )
            except Exception as error:
                _write_refusal(
                    writer,
                    error,
                    key=key,
                    session=session,
                    sequence=sequence,
                    request_id=request_id,
                )
                return 2
            _bounded(partial(_write, writer, encoded))
            if isinstance(request, ActualDisconnectRequest):
                return 0
        return 0
    except (Exception, KeyboardInterrupt):
        return 2
    finally:
        port.disconnect()


def serve_actual_provider(reader: IO[bytes], writer: IO[bytes]) -> int:
    port: ActualDs03ReadPort | None = None
    try:
        source = measured.source_binding()
        key, session = read_bootstrap(_bounded(partial(_read, reader)), source, family=_FAMILY)
    except (Exception, KeyboardInterrupt):
        # No authenticated channel exists yet: exit status is the only possible signal.
        return 2
    try:
        context = decode_frame(
            _bounded(partial(_read, reader)),
            key=key,
            session=session,
            sequence=0,
            kind="REQUEST",
            family=_FAMILY,
        )
        if context.request_id is not None or set(context.payload) != {
            "authority",
            "accepted_digest",
            "provider_job",
        }:
            raise Ds03Refusal("IPC_PROTOCOL")
        authority = decode_authority(canonical(context.payload["authority"]))
        accepted = context.payload["accepted_digest"]
        if type(accepted) is not str:
            raise Ds03Refusal("AUTHORITY_INVALID")
        job_name = measured._validate_job_name(context.payload["provider_job"])
        measured._current_job_pids(job_name)
        binding = _measurement(authority)
        static = admit_authority(
            authority,
            independently_accepted_digest=accepted,
            binding=binding,
            now=datetime.now(UTC),
        )
        from auvexo_alpha.infrastructure.ds03_metadata import load_ds03_account_metadata

        metadata = load_ds03_account_metadata(static, now=datetime.now(UTC))
        admission = static.bind_metadata(metadata, now=datetime.now(UTC))
        from auvexo_alpha.infrastructure.ds03_mt5 import actual_rights, open_native_readonly

        port = open_native_readonly(admission, job_name=job_name)
    except Exception as error:
        try:
            _write_refusal(writer, error, key=key, session=session, sequence=0, request_id=None)
        except (Exception, KeyboardInterrupt):
            # The ERROR frame could not be delivered; the exit status still refuses.
            return 2
        return 2
    except KeyboardInterrupt:
        return 2
    try:
        return _serve_actual_session(
            reader,
            writer,
            key=key,
            session=session,
            port=port,
            rights=actual_rights(admission),
            source_hash=source,
        )
    except (Exception, KeyboardInterrupt):
        return 2
    finally:
        port.disconnect()


def main() -> int:
    if sys.argv[1:] != ["--actual-provider-child"]:
        return 2
    return serve_actual_provider(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
