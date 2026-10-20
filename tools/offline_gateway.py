"""Run the fake inspection gateway on inherited anonymous pipes, never a listener."""

import sys

from auvexo_alpha.infrastructure.gateway_ipc import serve_inspection


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    return serve_inspection(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
