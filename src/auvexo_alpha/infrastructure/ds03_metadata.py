"""Fixed encrypted account metadata and reference key; admission precedes native access.

Account, server and ticket references are keyed HMAC-SHA256 digests. The 32-byte key is
generated here, held only in its own fixed CurrentUser DPAPI slot and never written to
Git, JSON, logs, arguments or the environment. No password is stored in metadata.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID

from auvexo_alpha.domain.ds03_actual import Ds03ReasonCode, Ds03Reasoned, Ds03Refusal, refusal
from auvexo_alpha.domain.ds03_authority import (
    REFERENCE_VERSION,
    Ds03AuthorityAdmission,
    Ds03LocalMetadata,
    Ds03OnboardingAdmission,
    Ds03RuntimeBinding,
    decode_metadata,
)
from auvexo_alpha.infrastructure.ds03_secrets import (
    _DS03DPAPI,
    _DS03WindowsFiles,
)
from auvexo_alpha.infrastructure.oi_secrets import _Crypto, _Files

_PURPOSE = b"auvexo-alpha:phase2:ds03:mt5-demo-account-metadata:v1"
_MAGIC = b"AUVEXO-DS03-METADATA-DPAPI-V1\x00"
_FILENAME = "mt5-demo-account.v1.dpapi"
_LIMIT = 8192
_KEY_PURPOSE = b"auvexo-alpha:phase2:ds03:mt5-reference-key:v1"
_KEY_MAGIC = b"AUVEXO-DS03-REFERENCE-KEY-DPAPI-V1\x00"
_KEY_FILENAME = "mt5-reference-key.v1.dpapi"
_KEY_BYTES = 32
type ReferenceKind = Literal["account", "server", "order", "position", "deal"]
_REFERENCE_KINDS = frozenset(("account", "server", "order", "position", "deal"))


class Ds03MetadataUnavailable(ValueError, Ds03Reasoned):
    def __init__(self, reason: Ds03ReasonCode = "METADATA_UNAVAILABLE") -> None:
        self.reason = reason
        super().__init__("DS03_METADATA_UNAVAILABLE")


class Ds03ReferenceKeyUnavailable(ValueError, Ds03Reasoned):
    reason: Ds03ReasonCode = "REFERENCE_KEY_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("DS03_REFERENCE_KEY_UNAVAILABLE")


def keyed_reference(key: bytes, kind: ReferenceKind, value: str) -> str:
    """Opaque 64-hex reference: HMAC-SHA256 over fixed purpose, version, kind and value.

    Without the private key a low-entropy login, server or ticket cannot be enumerated
    back from the digest, and one kind can never collide with another.
    """
    if (
        type(key) is not bytes
        or len(key) != _KEY_BYTES
        or kind not in _REFERENCE_KINDS
        or type(value) is not str
        or not 0 < len(value) <= 512
        or not value.isascii()
        or not value.isprintable()
    ):
        raise Ds03Refusal("REFERENCE_MISMATCH")
    message = json.dumps(
        [_KEY_PURPOSE.decode("ascii"), REFERENCE_VERSION, kind, value],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def metadata_references(key: bytes, *, login: int, assigned_server: str) -> tuple[str, str]:
    if type(login) is not int or login <= 0:
        raise Ds03Refusal("REFERENCE_MISMATCH")
    return keyed_reference(key, "account", str(login)), keyed_reference(
        key, "server", assigned_server
    )


def require_metadata_references(metadata: Ds03LocalMetadata, key: bytes) -> None:
    """Stored digests are recomputed from the raw private values, never trusted as given."""
    if type(metadata) is not Ds03LocalMetadata:
        raise Ds03Refusal("REFERENCE_MISMATCH")
    account, server = metadata_references(
        key, login=metadata.login, assigned_server=metadata.assigned_server
    )
    if (
        metadata.reference_version != REFERENCE_VERSION
        or not hmac.compare_digest(account, metadata.account_digest)
        or not hmac.compare_digest(server, metadata.server_digest)
    ):
        raise Ds03Refusal("REFERENCE_MISMATCH")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Ds03MetadataUnavailable()
        result[key] = value
    return result


class _MetadataStore:
    """Same bounded encrypted envelope/native mechanics for production and UUID tests."""

    def __init__(self, files: _Files, crypto: _Crypto) -> None:
        self._files, self._crypto = files, crypto

    def _save(self, metadata: Ds03LocalMetadata, *, create: bool) -> None:
        try:
            if type(metadata) is not Ds03LocalMetadata:
                raise Ds03MetadataUnavailable()
            checked = decode_metadata(metadata.canonical_bytes())
            plain = json.dumps(
                {"purpose": _PURPOSE.decode(), "version": 1, "metadata": checked.model_dump()},
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            if len(plain) > 4096:
                raise Ds03MetadataUnavailable()
            encrypted = self._crypto.protect(plain)
            if not encrypted or len(encrypted) + len(_MAGIC) > _LIMIT:
                raise Ds03MetadataUnavailable()
            if create:
                self._files.create(_MAGIC + encrypted)
            else:
                self._files.write(_MAGIC + encrypted)
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def create(self, metadata: Ds03LocalMetadata) -> None:
        self._save(metadata, create=True)

    def rotate(self, metadata: Ds03LocalMetadata) -> None:
        try:
            previous = self.load()
            if (
                previous.login != metadata.login
                or previous.assigned_server != metadata.assigned_server
                or previous.account_digest != metadata.account_digest
                or previous.server_digest != metadata.server_digest
            ):
                raise Ds03MetadataUnavailable()
            self._save(metadata, create=False)
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def load(self) -> Ds03LocalMetadata:
        try:
            blob = self._files.read()
            if not len(_MAGIC) < len(blob) <= _LIMIT or not blob.startswith(_MAGIC):
                raise Ds03MetadataUnavailable()
            plain = self._crypto.unprotect(blob[len(_MAGIC) :])
            if len(plain) > 4096:
                raise Ds03MetadataUnavailable()
            data = json.loads(plain, object_pairs_hook=_unique)
            if (
                type(data) is not dict
                or set(data) != {"purpose", "version", "metadata"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or type(data["purpose"]) is not str
                or not hmac.compare_digest(data["purpose"], _PURPOSE.decode())
            ):
                raise Ds03MetadataUnavailable()
            return decode_metadata(json.dumps(data["metadata"], allow_nan=False).encode())
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def delete(self) -> None:
        try:
            self._files.delete()
        except Exception:
            raise Ds03MetadataUnavailable() from None


class _ReferenceKeyStore:
    """Same bounded envelope mechanics; the key is generated here, never caller supplied.

    There is no rotate: a new key silently changes every reference. Replacement is an
    explicit delete, create, new metadata and a new independently accepted authority.
    """

    def __init__(self, files: _Files, crypto: _Crypto) -> None:
        self._files, self._crypto = files, crypto

    def create(self) -> None:
        try:
            plain = json.dumps(
                {
                    "purpose": _KEY_PURPOSE.decode("ascii"),
                    "version": 1,
                    "key": secrets.token_bytes(_KEY_BYTES).hex(),
                },
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            encrypted = self._crypto.protect(plain)
            if not encrypted or len(encrypted) + len(_KEY_MAGIC) > _LIMIT:
                raise Ds03ReferenceKeyUnavailable()
            self._files.create(_KEY_MAGIC + encrypted)
        except Exception:
            raise Ds03ReferenceKeyUnavailable() from None

    def load(self) -> bytes:
        try:
            blob = self._files.read()
            if not len(_KEY_MAGIC) < len(blob) <= _LIMIT or not blob.startswith(_KEY_MAGIC):
                raise Ds03ReferenceKeyUnavailable()
            plain = self._crypto.unprotect(blob[len(_KEY_MAGIC) :])
            if len(plain) > 4096:
                raise Ds03ReferenceKeyUnavailable()
            data = json.loads(plain, object_pairs_hook=_unique)
            if (
                type(data) is not dict
                or set(data) != {"purpose", "version", "key"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or type(data["purpose"]) is not str
                or not hmac.compare_digest(data["purpose"], _KEY_PURPOSE.decode())
                or type(data["key"]) is not str
                or len(data["key"]) != 2 * _KEY_BYTES
                or any(character not in "0123456789abcdef" for character in data["key"])
            ):
                raise Ds03ReferenceKeyUnavailable()
            return bytes.fromhex(data["key"])
        except Exception:
            raise Ds03ReferenceKeyUnavailable() from None

    def delete(self) -> None:
        try:
            self._files.delete()
        except Exception:
            raise Ds03ReferenceKeyUnavailable() from None


class _MetadataDPAPI(_DS03DPAPI):
    def _purpose(self) -> bytes:
        return _PURPOSE


class _MetadataWindowsFiles(_DS03WindowsFiles):
    def __init__(self, test_id: UUID | None = None) -> None:
        super().__init__(test_id)
        self.path = self.path.with_name(_FILENAME)


class _ReferenceKeyDPAPI(_DS03DPAPI):
    def _purpose(self) -> bytes:
        return _KEY_PURPOSE


class _ReferenceKeyWindowsFiles(_DS03WindowsFiles):
    def __init__(self, test_id: UUID | None = None) -> None:
        super().__init__(test_id)
        self.path = self.path.with_name(_KEY_FILENAME)


def make_test_ds03_reference_key_store(test_id: UUID) -> _ReferenceKeyStore:
    """UUID mandatory; identical production classes under a disposable leaf only."""
    try:
        if type(test_id) is not UUID:
            raise Ds03ReferenceKeyUnavailable()
        return _ReferenceKeyStore(_ReferenceKeyWindowsFiles(test_id), _ReferenceKeyDPAPI())
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def make_test_ds03_metadata_store(test_id: UUID) -> _MetadataStore:
    """UUID mandatory; identical production classes, fixed disposable leaf only."""
    try:
        if type(test_id) is not UUID:
            raise Ds03MetadataUnavailable()
        return _MetadataStore(_MetadataWindowsFiles(test_id), _MetadataDPAPI())
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _require_authority(
    admission: Ds03AuthorityAdmission | None, now: datetime | None
) -> Ds03AuthorityAdmission:
    try:
        if type(admission) not in (Ds03AuthorityAdmission, Ds03OnboardingAdmission):
            raise Ds03MetadataUnavailable()
        if admission is None or not isinstance(now, datetime):
            raise Ds03MetadataUnavailable()
        admission.verify(now)
        from auvexo_alpha.infrastructure.ds03_mt5_binding import verify_runtime_binding

        verify_runtime_binding(admission.binding)
        return admission
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _require_full(
    admission: Ds03OnboardingAdmission | None, now: datetime | None
) -> Ds03OnboardingAdmission:
    try:
        if type(admission) is not Ds03OnboardingAdmission:
            raise Ds03MetadataUnavailable()
        _require_authority(admission, now)
        return admission
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _production_store() -> _MetadataStore:
    return _MetadataStore(_MetadataWindowsFiles(), _MetadataDPAPI())


def _production_key_store() -> _ReferenceKeyStore:
    return _ReferenceKeyStore(_ReferenceKeyWindowsFiles(), _ReferenceKeyDPAPI())


def _require_measured(binding: Ds03RuntimeBinding | None) -> Ds03RuntimeBinding:
    """The reference key must precede the authority that binds its digests, so its
    creation is gated on the measured fixed runtime instead. The key alone grants no
    account, credential or session access.
    """
    try:
        if type(binding) is not Ds03RuntimeBinding:
            raise Ds03ReferenceKeyUnavailable()
        checked = Ds03RuntimeBinding.model_validate_json(binding.canonical_bytes())
        from auvexo_alpha.infrastructure.ds03_mt5_binding import verify_runtime_binding

        verify_runtime_binding(checked)
        return checked
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def require_ds03_reference_key_absent(binding: Ds03RuntimeBinding | None = None) -> None:
    try:
        _require_measured(binding)
        _ReferenceKeyWindowsFiles().require_absent()
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def create_ds03_reference_key(binding: Ds03RuntimeBinding | None = None) -> None:
    try:
        _require_measured(binding)
        _production_key_store().create()
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def ds03_reference_digests(
    binding: Ds03RuntimeBinding | None = None, *, login: int, assigned_server: str
) -> tuple[str, str]:
    """Owner onboarding input: the keyed account/server digests to put in metadata/authority."""
    try:
        _require_measured(binding)
        return metadata_references(
            _production_key_store().load(), login=login, assigned_server=assigned_server
        )
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def load_ds03_reference_key(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> bytes:
    try:
        _require_authority(admission, now)
        return _production_key_store().load()
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def verify_ds03_reference_key(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> bool:
    load_ds03_reference_key(admission, now=now)
    return True


def delete_ds03_reference_key(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        _require_authority(admission, now)
        store = _production_key_store()
        store.load()
        store.delete()
    except Exception:
        raise Ds03ReferenceKeyUnavailable() from None


def require_ds03_account_metadata_absent(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        _require_authority(admission, now)
        _MetadataWindowsFiles().require_absent()
    except Exception:
        raise Ds03MetadataUnavailable() from None


def create_ds03_account_metadata(
    admission: Ds03OnboardingAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_full(admission, now)
        _production_store().create(checked.metadata)
    except Exception:
        raise Ds03MetadataUnavailable() from None


def load_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> Ds03LocalMetadata:
    try:
        checked = _require_authority(admission, now)
        metadata = _production_store().load()
        checked.require_metadata(metadata)
        require_metadata_references(metadata, _production_key_store().load())
        return metadata
    except Exception as error:
        raise Ds03MetadataUnavailable(refusal(error, "METADATA_UNAVAILABLE").reason) from None


def verify_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> bool:
    load_ds03_account_metadata(admission, now=now)
    return True


def rotate_ds03_account_metadata(
    admission: Ds03OnboardingAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_full(admission, now)
        _production_store().rotate(checked.metadata)
    except Exception:
        raise Ds03MetadataUnavailable() from None


def delete_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_authority(admission, now)
        store = _production_store()
        checked.require_metadata(store.load())
        store.delete()
    except Exception:
        raise Ds03MetadataUnavailable() from None
