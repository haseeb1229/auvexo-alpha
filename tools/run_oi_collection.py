"""Future explicit START-gated DS04-A1 job. Defaults disabled; no registration or issuer."""

import argparse
import json
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Never

from sqlalchemy import URL, create_engine
from sqlalchemy.exc import SQLAlchemyError

from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, OIReviewContinuation
from auvexo_alpha.domain.oi_schedule import (
    OICollectionConfig,
    OIStartEnvelope,
    require_scheduled_start,
    scheduled_slot,
)
from auvexo_alpha.infrastructure.oi_collection import OICollectionJob
from auvexo_alpha.infrastructure.oi_http import OIHTTP
from auvexo_alpha.infrastructure.oi_runtime import inspect_clock, require_build, resources_ready
from auvexo_alpha.infrastructure.oi_secrets import load_oi_database_password
from auvexo_alpha.infrastructure.oi_store import OIStore
from auvexo_alpha.infrastructure.public_http import SourceError


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError("OI_CLI_ARGUMENTS_INVALID") from None


def load_review_authority(
    config: OICollectionConfig,
    path: Path | None,
    accepted: list[str],
    now: datetime,
) -> OIReviewAuthority | None:
    if path is None:
        if accepted:
            raise ValueError("OI_REVIEW_ACCEPTANCE_WITHOUT_CHAIN")
        return None
    if not accepted or path.stat().st_size > 262144:
        raise ValueError("OI_REVIEW_CHAIN_INVALID")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("OI_REVIEW_DUPLICATE_KEY")
            result[key] = value
        return result

    raw = path.read_bytes()
    depth, in_string, escaped = 0, False, False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
        elif byte == 34:
            in_string = True
        elif byte in (91, 123):
            depth += 1
            if depth > 32:
                raise ValueError("OI_REVIEW_CHAIN_DEPTH")
        elif byte in (93, 125):
            depth -= 1
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except RecursionError as error:
        raise ValueError("OI_REVIEW_CHAIN_DEPTH") from error
    if not isinstance(data, list) or not 1 <= len(data) <= 32:
        raise ValueError("OI_REVIEW_CHAIN_INVALID")
    chain = tuple(OIReviewContinuation.model_validate_json(json.dumps(item)) for item in data)
    return OIReviewAuthority(config.rights, chain, tuple(accepted), now)


def main() -> int:
    parser = _RedactedArgumentParser(description=__doc__, exit_on_error=False)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--start-envelope", type=Path)
    parser.add_argument("--accepted-start-hash")
    parser.add_argument("--review-chain", type=Path)
    parser.add_argument("--accepted-review-hash", action="append", default=[])
    parser.add_argument("--database", default="auvexo_dev_oiresearch")
    parser.add_argument("--port", type=int, default=55433)
    engine = None
    try:
        args = parser.parse_args(sys.argv[1:])
        root = Path(__file__).resolve().parents[1]
        cancel = Event()
        signal.signal(signal.SIGINT, lambda *_: cancel.set())
        if args.config.stat().st_size > 16384:
            raise ValueError("OI_CONFIG_INVALID")
        config = OICollectionConfig.model_validate_json(args.config.read_bytes())
        # Reject protected/late/default-disabled launches before clock, build or DB work.
        scheduled_slot(config, datetime.now(UTC))
        review_authority = load_review_authority(
            config, args.review_chain, args.accepted_review_hash, datetime.now(UTC)
        )
        require_scheduled_start(config, datetime.now(UTC), review_authority)
        if not args.scheduled or args.start_envelope is None or args.accepted_start_hash is None:
            raise ValueError("OI_OWNER_START_REQUIRED")
        if args.start_envelope.stat().st_size > 16384:
            raise ValueError("OI_START_AUTHORITY_INVALID")
        envelope = OIStartEnvelope.model_validate_json(args.start_envelope.read_bytes())
        envelope.require_start(
            config, args.accepted_start_hash, datetime.now(UTC), review_authority
        )
        require_build(root, config)
        clock = inspect_clock(config.clock_source)
        clock.require_trusted(config, datetime.now(UTC))
        if (
            not 1 <= args.port <= 65535
            or args.port == 55432
            or not re.fullmatch(r"auvexo_dev_oi[a-z0-9]+", args.database)
        ):
            raise ValueError("OI_DATABASE_SCOPE")
        # Build/clock inspection can consume the launch or authorization interval.
        # Recheck every time-sensitive gate together before decrypting a persistent secret.
        decrypt_at = datetime.now(UTC)
        scheduled_slot(config, decrypt_at)
        require_scheduled_start(config, decrypt_at, review_authority)
        envelope.require_start(config, args.accepted_start_hash, decrypt_at, review_authority)
        clock.require_trusted(config, decrypt_at)
        # Only the current-user Windows OS store supplies a real scheduled DB secret.
        # No plaintext environment/config/task/CLI fallback and no interactive prompt.
        password = load_oi_database_password()
        engine = create_engine(
            URL.create(
                "postgresql+psycopg",
                username="auvexo_data_writer",
                password=password,
                host="127.0.0.1",
                port=args.port,
                database=args.database,
            ),
            pool_size=2,
            max_overflow=0,
            pool_timeout=2,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 2,
                "options": "-c statement_timeout=3000 -c lock_timeout=1000",
            },
        )
        managed_root = root / ".local/phase6/oi-managed"
        store = OIStore(
            engine, managed_root / "artifacts", managed_root, review_authority=review_authority
        )

        def before_attempt(at: datetime) -> None:
            envelope.require_start(config, args.accepted_start_hash, at, review_authority)
            clock.require_trusted(config, at)
            if not resources_ready(root):
                raise ValueError("OI_RESOURCE_YIELD")

        http = OIHTTP(
            cancel,
            state=store.load_transport_state(datetime.now(UTC)),
            persist=store.save_transport_state,
            before_attempt=before_attempt,
        )
        job = OICollectionJob(
            config,
            store,
            http,
            cancel=cancel,
            resources_ready=lambda: resources_ready(root),
            review_authority=review_authority,
        )
        result = job.run(
            envelope=envelope, accepted_start_digest=args.accepted_start_hash, clock=clock
        )
        print(
            json.dumps(
                {
                    "status": result.code,
                    "reason": result.reason,
                    "manifest_hashes": result.manifests,
                    "forward_days": 0,
                }
            )
        )
        return result.exit_code
    except (argparse.ArgumentError, ValueError, OSError, SQLAlchemyError, SourceError):
        # Never print DSNs, driver output, tokens, raw provider values or untrusted exceptions.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "OI_PREFLIGHT_OR_PERSISTENCE_FAILED",
                    "forward_days": 0,
                }
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
