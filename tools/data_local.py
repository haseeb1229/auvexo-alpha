"""Owner-side DEV provisioning and credential-free command line; no broker access."""

import json
import os
import secrets
import subprocess
import sys

import psycopg
from local_db import LOCAL, PORT, ROOT, credentials, write_private
from psycopg import sql


def main() -> None:
    secret_path = LOCAL / "data-secrets.json"
    if sys.argv[1:] == ["provision"]:
        if not secret_path.exists():
            write_private(secret_path, json.dumps({"data_writer": secrets.token_hex(32)}))
        password = json.loads(secret_path.read_text())["data_writer"]
        with psycopg.connect(
            host="127.0.0.1",
            port=PORT,
            user="auvexo_admin",
            password=credentials()["admin"],
            dbname="postgres",
            autocommit=True,
        ) as conn:
            if not conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='auvexo_data_writer'"
            ).fetchone():
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE auvexo_data_writer LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT"
                    ).format(sql.Literal(password))
                )
            conn.execute("GRANT auvexo_ingest TO auvexo_data_writer")
            conn.execute("GRANT CONNECT ON DATABASE auvexo_dev, auvexo_test TO auvexo_data_writer")
        print("Dedicated data writer provisioned; no foundation-policy or migration grants")
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUVEXO_")}
    env["DATA_DB_PASSWORD"] = json.loads(secret_path.read_text())["data_writer"]
    result = subprocess.run(
        [sys.executable, "-m", "auvexo_alpha.data_cli", *sys.argv[1:]], env=env, cwd=ROOT
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
