"""Inspect the fixed synthetic DS-03 child; no provider/account/credential arguments."""

import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from auvexo_alpha.domain.ds03 import Ds03Error, SymbolsPayload, SymbolsRequest
from auvexo_alpha.infrastructure.ds03_fake import synthetic_identity
from auvexo_alpha.infrastructure.ds03_process import Ds03Process


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    try:
        with Ds03Process() as connector:
            now, identity = datetime.now(UTC), synthetic_identity()
            reply = connector.read(
                SymbolsRequest(
                    request_id=uuid4(),
                    created_at=now,
                    expires_at=now + timedelta(seconds=10),
                    release_hash=identity.release_hash,
                    config_hash=identity.config_hash,
                )
            )
            if not isinstance(reply.payload, SymbolsPayload):
                raise Ds03Error()
            connector.disconnect()
        print("DS03_SYNTHETIC_READONLY_OK")
        return 0
    except (Exception, KeyboardInterrupt):
        print("DS03_UNAVAILABLE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
