"""Future fixed third-runtime OI database owner tool; no collection/START authority."""

import argparse
from pathlib import Path
from typing import Never

from auvexo_alpha.infrastructure.oi_database import OIDatabaseUnavailable, OIRuntimeDatabase


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise OIDatabaseUnavailable()


def main() -> int:
    try:
        parser = _Parser(description=__doc__, exit_on_error=False)
        parser.add_argument("operation", choices=("provision", "verify", "start", "stop"))
        arguments = parser.parse_args()
        database = OIRuntimeDatabase(Path(__file__).resolve().parents[1])
        if arguments.operation == "provision":
            database.provision()
        elif arguments.operation == "verify":
            database.verify()
        elif arguments.operation == "start":
            database.start()
        else:
            database.stop()
        print("OI_DATABASE_" + arguments.operation.upper() + "_OK")
        return 0
    except (Exception, KeyboardInterrupt):
        print("OI_DATABASE_RECOVERY_REQUIRED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
