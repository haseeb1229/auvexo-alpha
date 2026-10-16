"""Provision only the isolated GitHub service database with synthetic credentials."""

import os
import subprocess
import sys

import psycopg
from sqlalchemy import URL

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise RuntimeError("CI-only synthetic setup; use local_db.py for Windows")
with psycopg.connect(
    host="127.0.0.1",
    port=55432,
    user="auvexo_admin",
    password="ci-synthetic-ephemeral-only",
    dbname="auvexo_test",
    autocommit=True,
) as conn:
    conn.execute(
        "CREATE ROLE auvexo_app LOGIN PASSWORD 'ci-synthetic-app-only-not-a-secret-123' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE"
    )
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
env = os.environ.copy()
env["AUVEXO_MIGRATION_DSN"] = URL.create(
    "postgresql+psycopg",
    username="auvexo_admin",
    password="ci-synthetic-ephemeral-only",
    host="127.0.0.1",
    port=55432,
    database="auvexo_test",
).render_as_string(hide_password=False)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
