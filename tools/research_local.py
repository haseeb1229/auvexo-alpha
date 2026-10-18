"""Provision a least-privilege owner-local research identity; no venue credentials."""

import json
import secrets
import sys

import psycopg
from local_db import LOCAL, PORT, credentials, write_private
from psycopg import sql


def main():
    if sys.argv[1:] != ["provision"]:
        raise SystemExit("Usage: python tools/research_local.py provision")
    path = LOCAL / "research-secrets.json"
    if not path.exists():
        write_private(path, json.dumps({"research_worker": secrets.token_hex(32)}))
    password = json.loads(path.read_text())["research_worker"]
    with psycopg.connect(
        host="127.0.0.1",
        port=PORT,
        user="auvexo_admin",
        password=credentials()["admin"],
        dbname="postgres",
        autocommit=True,
    ) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='auvexo_research_worker'"
        ).fetchone():
            conn.execute(
                sql.SQL(
                    "CREATE ROLE auvexo_research_worker LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT"
                ).format(sql.Literal(password))
            )
        conn.execute("GRANT auvexo_research TO auvexo_research_worker")
        conn.execute("GRANT CONNECT ON DATABASE auvexo_dev,auvexo_test TO auvexo_research_worker")
    print("Dedicated local research identity provisioned; no ingestion or policy-write grants")


if __name__ == "__main__":
    main()
