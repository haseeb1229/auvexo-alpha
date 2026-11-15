"""Provision the hosted-CI PostgreSQL container through the disposable-cluster harness.

The container listens on a non-operational port and carries a per-run marker, so CI
exercises the same refusal of 55432/55433 and the same marker proof as local runs.
"""

import os

from disposable_pg import ROLES, harness_cluster, provision

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise RuntimeError("CI-only synthetic setup; use tools/disposable_pg.py locally")
cluster = harness_cluster()
passwords = {role: os.environ[f"TEST_PG_{role.upper()}_PASSWORD"] for role in ROLES}
provision(
    dict(
        host="127.0.0.1",
        port=cluster.port,
        user="auvexo_admin",
        password=passwords["admin"],
        connect_timeout=3,
    ),
    passwords,
    cluster,
)
print(f"CI disposable cluster provisioned on 127.0.0.1:{cluster.port}")
