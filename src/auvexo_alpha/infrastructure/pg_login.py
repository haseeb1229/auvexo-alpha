"""LOGIN role DDL whose password never reaches the PostgreSQL server."""

from __future__ import annotations

from typing import Any, LiteralString

import psycopg
from psycopg import sql

_SCRAM_PREFIX = "SCRAM-SHA-256$4096:"


def scram_verifier(conn: psycopg.Connection[Any], role: str, password: str) -> str:
    """Salted SCRAM-SHA-256 verifier computed by libpq on this side of the connection."""
    verifier = conn.pgconn.encrypt_password(
        password.encode(), role.encode(), b"scram-sha-256"
    ).decode("ascii")
    if not verifier.startswith(_SCRAM_PREFIX) or password in verifier:
        raise RuntimeError("SCRAM_VERIFIER_UNAVAILABLE")
    return verifier


def login_role_sql(
    conn: psycopg.Connection[Any], role: str, password: str, attributes: LiteralString
) -> sql.Composed:
    """CREATE ROLE for a LOGIN whose password never reaches the server.

    The statement carries only the verifier, so a failed or logged statement cannot
    disclose the password; the server stores the verifier as-is.
    """
    return sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} " + attributes).format(
        sql.Identifier(role), sql.Literal(scram_verifier(conn, role, password))
    )
