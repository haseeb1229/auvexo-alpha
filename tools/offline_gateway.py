"""Run the fake inspection gateway on inherited anonymous pipes, never a listener."""

import sys

from auvexo_alpha.infrastructure.gateway_ipc import serve_inspection


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    # Unbuffered stdin: an idle exit may leave the pipe pump blocked in a read.
    stdin = open(sys.stdin.fileno(), "rb", buffering=0, closefd=False)
    return serve_inspection(stdin, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
