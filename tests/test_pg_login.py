"""LOGIN role DDL carries only a client-side SCRAM verifier, never the password."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from auvexo_alpha.infrastructure.pg_login import login_role_sql, scram_verifier

_PASSWORD = "synthetic-password-0123456789abcdef"
_VERIFIER = "SCRAM-SHA-256$4096:c2FsdHNhbHRzYWx0$c3RvcmVkLWtleQ==:c2VydmVyLWtleQ=="


def _connection(verifier: str, calls: list[tuple[bytes, bytes, bytes]]) -> SimpleNamespace:
    def encrypt_password(password: bytes, user: bytes, algorithm: bytes) -> bytes:
        calls.append((password, user, algorithm))
        return verifier.encode("ascii")

    return SimpleNamespace(pgconn=SimpleNamespace(encrypt_password=encrypt_password))


def test_statement_carries_the_scram_verifier_and_never_the_password():
    calls: list[tuple[bytes, bytes, bytes]] = []
    conn = _connection(_VERIFIER, calls)
    statement = login_role_sql(conn, "auvexo_app", _PASSWORD, "NOSUPERUSER NOCREATEDB")
    sent = statement.as_string(None)
    assert sent == (
        f"CREATE ROLE \"auvexo_app\" LOGIN PASSWORD '{_VERIFIER}' NOSUPERUSER NOCREATEDB"
    )
    assert _PASSWORD not in sent
    # The verifier is salted for this exact role with the SCRAM algorithm, client-side.
    assert calls == [(_PASSWORD.encode(), b"auvexo_app", b"scram-sha-256")]


@pytest.mark.parametrize(
    "result",
    [
        "md5" + "0" * 32,
        _PASSWORD,
        "SCRAM-SHA-256$1:c2FsdA==$a2V5:a2V5",
        "SCRAM-SHA-256$4096:" + _PASSWORD,
    ],
)
def test_non_scram_or_password_bearing_result_is_refused(result):
    conn = _connection(result, [])
    with pytest.raises(RuntimeError, match="^SCRAM_VERIFIER_UNAVAILABLE$"):
        scram_verifier(conn, "auvexo_app", _PASSWORD)
    with pytest.raises(RuntimeError, match="^SCRAM_VERIFIER_UNAVAILABLE$"):
        login_role_sql(conn, "auvexo_app", _PASSWORD, "NOSUPERUSER")
