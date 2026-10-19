"""Run pytest with disposable synthetic cache state outside managed storage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    # Pytest atomically creates its cache using a private temporary directory.
    # On Windows that ACL can remain private after the rename. Cross-identity
    # development runs must never put this transient state in managed .local.
    with TemporaryDirectory(prefix="auvexo-pytest-") as temporary:
        cache = Path(temporary) / "cache"
        return subprocess.call(
            [sys.executable, "-m", "pytest", *sys.argv[1:], "-o", f"cache_dir={cache}"]
        )


if __name__ == "__main__":
    raise SystemExit(main())
