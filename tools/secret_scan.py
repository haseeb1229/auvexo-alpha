"""High-signal source scan; never print matched secret text. Complements full Gitleaks."""

import re
import subprocess
from pathlib import Path

PATTERNS = [
    rb"gh[pousr]_[A-Za-z0-9]{30,}",
    rb"github_pat_[A-Za-z0-9_]{40,}",
    rb"AKIA[A-Z0-9]{16}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    rb"(?:sk-proj-|sk-ant-)[A-Za-z0-9_-]{30,}",
    rb"[a-z]+://[^\s:/]+:[^\s@{}]+@(?:[a-zA-Z0-9.-]+)",
]


def main() -> None:
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )
        .decode()
        .split("\0")
    )
    failures = []
    for name in sorted(set(files) - {""}):
        path = Path(name)
        if path.is_symlink():
            failures.append(f"{name}: source symlink forbidden")
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        for index, pattern in enumerate(PATTERNS):
            if re.search(pattern, data):
                failures.append(f"{name}: high-signal pattern {index + 1}")
    if failures:
        raise SystemExit("FAIL\n" + "\n".join(failures))
    print(f"PASS: high-signal scan of {len(set(files) - {''})} source files; no matched secrets")


if __name__ == "__main__":
    main()
