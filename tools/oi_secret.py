"""Owner-invoked OI database DPAPI provisioning only; no plaintext arguments/export."""

import argparse
import getpass
import sys
import warnings
from typing import Never

from auvexo_alpha.infrastructure.oi_secrets import (
    OISecretUnavailable,
    delete_oi_database_password,
    store_oi_database_password,
    verify_oi_database_password,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise OISecretUnavailable()


def main() -> int:
    parser = _Parser(description=__doc__, exit_on_error=False)
    parser.add_argument("operation", choices=("store", "rotate", "verify", "delete"))
    try:
        args = parser.parse_args()
        if args.operation in ("store", "rotate"):
            if not sys.stdin.isatty():
                raise OISecretUnavailable()
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                secret = getpass.getpass("OI database password (not echoed): ")
            store_oi_database_password(secret)
            print("OI_DATABASE_SECRET_STORED")
        elif args.operation == "verify":
            verify_oi_database_password()
            print("OI_DATABASE_SECRET_DECRYPTABLE")
        else:
            delete_oi_database_password()
            print("OI_DATABASE_SECRET_DELETED")
        return 0
    except (Exception, KeyboardInterrupt):
        print("OI_DATABASE_SECRET_UNAVAILABLE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
