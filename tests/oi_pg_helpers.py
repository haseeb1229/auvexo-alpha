"""OI PostgreSQL tests use the disposable test cluster, never 55432 or the OI runtime."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from auvexo_alpha.infrastructure.paper_identity import OI_RUNTIME_PORT, OPERATIONAL_PORT


def _test_port_allowed(port: int) -> bool:
    # The Operational and OI runtime ports are refused everywhere, as the disposable
    # cluster harness (tools/disposable_pg.py) also refuses them.
    return 1024 <= port <= 65535 and port not in (OPERATIONAL_PORT, OI_RUNTIME_PORT)


@contextmanager
def oi_test_server() -> Iterator[int]:
    """The port of the disposable cluster the OI storage tests write to."""
    name = "OI_TEST_PG_PORT" if "OI_TEST_PG_PORT" in os.environ else "TEST_PG_PORT"
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(
            "DISPOSABLE_TEST_CLUSTER_REQUIRED: run python tools/disposable_pg.py test"
        )
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError("OI_TEST_PORT_INVALID")
    port = int(value)
    if not _test_port_allowed(port):
        raise ValueError("OI_TEST_PORT_INVALID")
    yield port
