"""Real native Windows PG17.11 stdin bootstrap on one disposable UUID target."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, text

from auvexo_alpha.infrastructure import oi_database as module
from auvexo_alpha.infrastructure.oi_database import (
    OIDatabaseUnavailable,
    OIRuntimeDatabase,
)
from auvexo_alpha.infrastructure.oi_migrations import (
    migrate_oi_database,
    validate_migration_connection,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "nt", reason="native Windows initdb/CREATE_NO_WINDOW proof"),
]
ROOT = Path(__file__).resolve().parents[1]


class _MemorySlots:
    def __init__(self):
        self.passwords = None

    def require_absent(self):
        if self.passwords is not None:
            raise OIDatabaseUnavailable()

    def store(self, passwords):
        self.require_absent()
        self.passwords = passwords

    def load(self):
        if self.passwords is None:
            raise OIDatabaseUnavailable()
        return self.passwords

    def load_admin(self):
        return self.load().admin


def _no_plaintext_file(root, passwords):
    tokens = [password.encode("ascii") for password in passwords]
    for path in root.rglob("*"):
        if path.is_file():
            tail = b""
            with path.open("rb") as file:
                while block := file.read(1024 * 1024):
                    combined = tail + block
                    if any(token in combined for token in tokens):
                        return False
                    tail = combined[-128:]
    return True


def test_native_pg1711_pwprompt_migrate_restart_privileges_and_cleanup(monkeypatch, tmp_path):
    identity = uuid4()
    slots = _MemorySlots()
    instance = OIRuntimeDatabase._for_test(
        identity, 55571, ROOT / ".local/toolchains/postgres/pgsql/bin", ROOT, slots
    )
    assert not instance.root.exists()
    with socket.socket() as available:
        available.bind(("127.0.0.1", instance.port))
    native_run = module._supervised_run
    invocations = []
    synthetic = module._Passwords.generate()
    known_passwords = [synthetic.admin, synthetic.app, synthetic.writer]
    monkeypatch.setattr(module._Passwords, "generate", classmethod(lambda cls: synthetic))
    complete, stopped = False, False
    receipt = {
        "test_id": identity.hex,
        "port": instance.port,
        "engineering_only": True,
        "native_calls": invocations,
        "diagnostic_exceptions": [],
    }
    started_ns = time.perf_counter_ns()
    previous_trace = sys.gettrace()

    def trace(frame, event, value):
        if event == "exception" and Path(frame.f_code.co_filename).name in {
            "oi_database.py",
            "oi_migrations.py",
            "env.py",
        }:
            kind, exception, _ = value
            if kind not in (StopIteration, GeneratorExit):
                message = str(exception)
                for password in known_passwords:
                    message = message.replace(password, "[REDACTED_SYNTHETIC_SECRET]")
                receipt["diagnostic_exceptions"].append(
                    {
                        "file": Path(frame.f_code.co_filename).name,
                        "line": frame.f_lineno,
                        "type": kind.__name__,
                        "message": message[:500],
                    }
                )
                if frame.f_code.co_name == "_verify_identity":
                    receipt["identity_observed_nonsecret"] = frame.f_locals.get("actual")
        return trace

    def observe_run(argv, **kwargs):
        password_input = kwargs.get("input")
        if password_input is not None:
            fields = password_input.decode("ascii").splitlines()
            assert len(fields) == 2 and fields[0] == fields[1]
            assert fields[0] == synthetic.admin
        environment = kwargs.get("env", {})
        argv_leak = any(password in item for password in known_passwords for item in argv)
        env_leak = any(
            password in item for password in known_passwords for item in environment.values()
        )
        assert not argv_leak and not env_leak
        assert "--pwfile" not in argv
        result = native_run(argv, **kwargs)
        output_leak = any(
            password.encode("ascii") in result.stdout + result.stderr
            for password in known_passwords
        )
        assert not output_leak
        invocations.append(
            {
                "executable": Path(argv[0]).name,
                "arguments": argv[1:],
                "returncode": result.returncode,
                "stdin_password": password_input is not None,
                "argv_secret": argv_leak,
                "env_secret": env_leak,
                "output_secret": output_leak,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                "create_no_window": kwargs.get("creationflags") == subprocess.CREATE_NO_WINDOW,
            }
        )
        return result

    monkeypatch.setattr(module, "_supervised_run", observe_run)
    monkeypatch.delenv("AUVEXO_MIGRATION_DSN", raising=False)
    sys.settrace(trace)
    try:
        instance.provision()
        complete = True
        instance.verify()
        passwords = slots.load()
        known_passwords[:] = [passwords.admin, passwords.app, passwords.writer]
        assert len(set(known_passwords)) == 3
        prompt_calls = [call for call in invocations if call["stdin_password"]]
        assert len(prompt_calls) == 1
        assert "--pwprompt" in prompt_calls[0]["arguments"]
        assert "--auth=scram-sha-256" in prompt_calls[0]["arguments"]
        assert prompt_calls[0]["create_no_window"]
        receipt["native_initdb_pwprompt"] = True
        receipt["native_prompt_mode"] = (
            "nonsecret child-only OSTYPE=msys selects controlled stdin/stderr"
        )
        receipt["prompt_primary_source"] = (
            "https://raw.githubusercontent.com/postgres/postgres/REL_17_11/src/common/sprompt.c"
        )
        receipt["programmatic_migration_env_absent"] = True

        # The exact same actual bound connection ignores a hostile inherited DSN.
        monkeypatch.setenv("AUVEXO_MIGRATION_DSN", "hostile-environment-must-not-be-read")
        engine = create_engine(instance._url("auvexo_admin", passwords.admin), hide_parameters=True)
        try:
            with engine.begin() as connection:
                attributes = {"oi_test_id": identity, "oi_test_port": instance.port}
                validate_migration_connection(connection, attributes)
                migrate_oi_database(connection, ROOT, _test_id=identity, _test_port=instance.port)
                original = engine.url
                for change in (
                    {"host": "localhost"},
                    {"username": "auvexo_app"},
                    {"database": "auvexo_dev_oiresearch"},
                    {"port": 55432},
                    {"port": 55433},
                ):
                    engine.url = original.set(**change)
                    with pytest.raises(ValueError, match="OI_MIGRATION_CONNECTION_INVALID"):
                        validate_migration_connection(connection, attributes)
                engine.url = original
        finally:
            engine.dispose()
        receipt["hostile_env_ignored_and_wrong_bound_url_refused"] = True

        # An untransactioned supplied Connection gets a committed env-owned transaction;
        # a caller-owned transaction remains active and can roll all migration DDL back.
        for caller_transaction in (False, True):
            transaction_id = uuid4()
            name = "auvexo_test_oi" + transaction_id.hex
            with instance._connect(passwords.admin) as connection:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                connection.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
                )
            transaction_engine = create_engine(
                instance._url("auvexo_admin", passwords.admin, database=name), hide_parameters=True
            )
            try:
                with transaction_engine.connect() as connection:
                    assert not connection.in_transaction()
                    transaction = connection.begin() if caller_transaction else None
                    migrate_oi_database(
                        connection, ROOT, _test_id=transaction_id, _test_port=instance.port
                    )
                    if transaction is not None:
                        assert transaction.is_active
                        assert (
                            connection.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0005_paper_core"
                        )
                        transaction.rollback()
                    else:
                        assert not connection.in_transaction()
                with transaction_engine.connect() as connection:
                    present = connection.scalar(
                        text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                    )
                    assert present is not caller_transaction
            finally:
                transaction_engine.dispose()
        receipt["env_owned_transaction_committed_caller_owned_rollback_preserved"] = True

        for role, password in (
            ("auvexo_app", passwords.app),
            ("auvexo_data_writer", passwords.writer),
        ):
            with psycopg.connect(
                host="127.0.0.1",
                port=instance.port,
                dbname=instance.database,
                user=role,
                password=password,
                connect_timeout=3,
                autocommit=True,
            ) as connection:
                for statement in (
                    "CREATE TABLE forbidden (id integer)",
                    "CREATE ROLE forbidden_role",
                    "SET ROLE auvexo_admin",
                    "SET ROLE auvexo_paper",
                    "SET ROLE auvexo_research",
                    "UPDATE foundation_policy SET execution_enabled=true",
                    "INSERT INTO paper_policy VALUES (repeat('0',64),'{}',now())",
                ):
                    with (
                        pytest.raises(psycopg.errors.InsufficientPrivilege),
                        connection.transaction(),
                    ):
                        connection.execute(statement)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("CREATE DATABASE forbidden_database")
                with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                    connection.execute(
                        "INSERT INTO data_manifest SELECT * FROM data_manifest"
                    ) if role == "auvexo_app" else connection.execute("DELETE FROM data_manifest")
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(
                    host="127.0.0.1",
                    port=instance.port,
                    dbname=instance.database,
                    user=role,
                    password="synthetic-wrong-password-not-a-real-secret",
                    connect_timeout=3,
                )
        receipt["scram_wrong_password_and_role_grant_negatives"] = True
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                host="127.0.0.1",
                port=instance.port,
                dbname=instance.database,
                user="auvexo_admin",
                password="synthetic-wrong-admin-password-only",
                connect_timeout=3,
            )

        instance.stop()
        stopped = True
        assert not (instance.data / "postmaster.pid").exists()
        assert _no_plaintext_file(instance.root, known_passwords)
        instance.start()
        stopped = False
        instance.verify()
        receipt["clean_restart_verification"] = True
        instance.stop()
        stopped = True
        assert _no_plaintext_file(instance.root, known_passwords)
        receipt["no_plaintext_argv_env_pwfile_output_or_cluster_file"] = True
        receipt["native_calls"] = invocations
        receipt["status"] = "PASS"
    finally:
        sys.settrace(previous_trace)
        if complete and not stopped:
            instance.stop()
            stopped = True
        # A failed provisioning state is retained if ownership/cleanup is ambiguous.
        if stopped or not instance.data.exists():
            assert instance.root.parent == Path(tempfile.gettempdir()).resolve()
            assert instance.root.name == "auvexo-oi-db-test-" + identity.hex
            instance._guard_target()
            if instance.root.exists():
                shutil.rmtree(instance.root)
            assert not instance.root.exists()
        receipt["cleanup_removed_disposable_root"] = not instance.root.exists()
        receipt["elapsed_monotonic_seconds"] = (time.perf_counter_ns() - started_ns) / 1e9
        (tmp_path / "native-pg-proof.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf8"
        )
        print("Native PostgreSQL proof receipt:", tmp_path / "native-pg-proof.json")


@pytest.mark.parametrize(
    "violation",
    [
        "foreign_spec",
        "foreign_event",
        "financial_table_grant",
        "financial_column_grant",
        "data_column_mutation_grant",
        "public_financial_read_grant",
        "nested_ingest_authority",
        "accepted_continuation_requires_supplied_authority",
    ],
)
def test_native_restart_refuses_foreign_rows_and_privilege_drift(violation, tmp_path):
    identity = uuid4()
    slots = _MemorySlots()
    instance = OIRuntimeDatabase._for_test(
        identity, 55571, ROOT / ".local/toolchains/postgres/pgsql/bin", ROOT, slots
    )
    complete, stopped = False, False
    review_authority = None
    proof = {"test_id": identity.hex, "case": violation, "port": 55571, "engineering_only": True}
    (tmp_path / "ownership.json").write_text(json.dumps(proof), encoding="utf8")
    try:
        instance.provision()
        complete = True
        passwords = slots.load()
        with instance._connect(passwords.admin) as connection:
            if violation == "foreign_spec":
                connection.execute("INSERT INTO data_spec VALUES (repeat('b',64),'{}','{}'::bytea)")
                check = "SELECT count(*) FROM data_spec"
            elif violation == "foreign_event":
                connection.execute(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                    "VALUES ('foreign','foreign',now(),'{}')"
                )
                check = "SELECT count(*) FROM data_event WHERE feed_key='foreign'"
            elif violation == "financial_table_grant":
                connection.execute("GRANT UPDATE ON paper_outbox TO auvexo_data_writer")
                check = (
                    "SELECT has_table_privilege("
                    "'auvexo_data_writer','paper_outbox','UPDATE')::integer"
                )
            elif violation == "financial_column_grant":
                connection.execute(
                    "GRANT UPDATE(execution_enabled) ON foundation_policy TO auvexo_data_writer"
                )
                check = (
                    "SELECT has_any_column_privilege("
                    "'auvexo_data_writer','foundation_policy','UPDATE')::integer"
                )
            elif violation == "data_column_mutation_grant":
                connection.execute("GRANT UPDATE(payload) ON data_manifest TO auvexo_data_writer")
                check = (
                    "SELECT has_any_column_privilege("
                    "'auvexo_data_writer','data_manifest','UPDATE')::integer"
                )
            elif violation == "public_financial_read_grant":
                connection.execute("GRANT SELECT ON paper_truth_event TO PUBLIC")
                check = (
                    "SELECT has_table_privilege("
                    "'auvexo_data_writer','paper_truth_event','SELECT')::integer"
                )
            elif violation == "nested_ingest_authority":
                connection.execute(
                    "GRANT auvexo_paper TO auvexo_ingest WITH INHERIT FALSE, SET TRUE"
                )
                check = "SELECT pg_has_role('auvexo_ingest','auvexo_paper','MEMBER')::integer"
            else:
                from test_oi_rights_review import authority

                review_authority = authority()
                continuation = review_authority.chain[0]
                connection.execute(
                    "INSERT INTO data_source_review VALUES (%s,%s)",
                    (continuation.content_hash(), continuation.canonical_bytes().decode("ascii")),
                )
                check = "SELECT count(*) FROM data_source_review"
            assert connection.execute(check).fetchone() == (1,)
        with pytest.raises(OIDatabaseUnavailable):
            instance.verify()
        with instance._connect(passwords.admin) as connection:
            assert connection.execute(check).fetchone() == (1,)
        if review_authority is not None:
            instance.verify(review_authority=review_authority)
            instance.stop()
            stopped = True
            instance.start(review_authority=review_authority)
            stopped = False
            instance.verify(review_authority=review_authority)
            with instance._connect(passwords.admin) as connection:
                assert connection.execute(check).fetchone() == (1,)
        # Qualification fails; explicit stop still contains only the attested server.
        instance.stop()
        stopped = True
        with pytest.raises(OIDatabaseUnavailable):
            instance.start()
        assert not (instance.data / "postmaster.pid").exists()
        assert json.loads(instance.state.read_text())["status"] == "RECOVERY_REQUIRED"
    finally:
        if complete and not stopped:
            instance.stop()
        if complete:
            instance._guard_target()
            assert instance.root.parent == Path(tempfile.gettempdir()).resolve()
            assert instance.root.name == "auvexo-oi-db-test-" + identity.hex
            assert not (instance.data / "postmaster.pid").exists()
            shutil.rmtree(instance.root)
        proof["cleanup_removed_disposable_root"] = not instance.root.exists()
        proof["status"] = (
            "PASS" if complete and stopped and not instance.root.exists() else "RECOVERY_REQUIRED"
        )
        (tmp_path / "case-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf8")


def test_native_prompt_timeout_kills_only_proven_owned_tree(monkeypatch, tmp_path):
    import psutil

    identity = uuid4()
    instance = OIRuntimeDatabase._for_test(
        identity, 55571, ROOT / ".local/toolchains/postgres/pgsql/bin", ROOT, _MemorySlots()
    )
    instance.local.mkdir(parents=True)
    proof = {"test_id": identity.hex, "case": "bounded_owned_prompt_timeout", "port": 55571}
    (tmp_path / "ownership.json").write_text(json.dumps(proof), encoding="utf8")
    owned_pids = []
    original_import = module.importlib.import_module

    class ProcessProxy:
        def __init__(self, pid):
            self.process = psutil.Process(pid)
            self.pid = pid
            owned_pids.append(pid)

        def create_time(self):
            return self.process.create_time()

        def exe(self):
            return self.process.exe()

        def children(self, recursive):
            children = self.process.children(recursive=recursive)
            owned_pids.extend(child.pid for child in children)
            return children

    class Processes:
        Process = ProcessProxy

    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda name: Processes() if name == "psutil" else original_import(name),
    )
    started = time.perf_counter()
    try:
        with pytest.raises(OIDatabaseUnavailable) as failure:
            module._supervised_run(
                [
                    str(instance._exe("initdb")),
                    "-D",
                    str(instance.data),
                    "-U",
                    "auvexo_admin",
                    "--pwprompt",
                    "--auth=scram-sha-256",
                    "--encoding=UTF8",
                    "--locale=C",
                ],
                input=None,
                capture_output=True,
                env=module._native_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=2,
                check=False,
            )
        proof["helper_cleanup_verified"] = failure.value.cleanup_verified
        states = []
        for pid in owned_pids:
            try:
                process = psutil.Process(pid)
                states.append(
                    {
                        "pid": pid,
                        "executable": process.exe(),
                        "status": process.status(),
                        "create_time": process.create_time(),
                    }
                )
            except psutil.NoSuchProcess:
                states.append({"pid": pid, "status": "GONE"})
        proof["owned_process_states"] = states
        (tmp_path / "observed-timeout.json").write_text(
            json.dumps(proof, indent=2), encoding="utf8"
        )
        assert time.perf_counter() - started < 8
        assert owned_pids
        assert not any(psutil.pid_exists(pid) for pid in owned_pids)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 55571))
    finally:
        instance._guard_target()
        assert instance.root.parent == Path(tempfile.gettempdir()).resolve()
        assert instance.root.name == "auvexo-oi-db-test-" + identity.hex
        assert not any(psutil.pid_exists(pid) for pid in owned_pids)
        shutil.rmtree(instance.root)
        proof["cleanup_removed_disposable_root"] = not instance.root.exists()
        proof["elapsed_monotonic_seconds"] = time.perf_counter() - started
        proof["status"] = "PASS"
        (tmp_path / "case-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf8")


@pytest.mark.parametrize("operation", ["provision", "start"])
def test_native_record_write_failure_cannot_skip_owned_server_stop(
    monkeypatch, tmp_path, operation
):
    identity = uuid4()
    instance = OIRuntimeDatabase._for_test(
        identity, 55571, ROOT / ".local/toolchains/postgres/pgsql/bin", ROOT, _MemorySlots()
    )
    proof = {
        "test_id": identity.hex,
        "operation": operation,
        "engineering_only": True,
        "port": 55571,
    }
    (tmp_path / "ownership.json").write_text(json.dumps(proof), encoding="utf8")
    original_record, original_verify = instance._record, instance._verify_server
    records = []
    baseline = None
    complete = False

    def failing_record(status, hashes):
        nonlocal baseline
        records.append(status)
        if status in ("READY", "RECOVERY_REQUIRED"):
            if baseline is None:
                baseline = instance.state.read_bytes()
            raise PermissionError("synthetic-state-write-failure")
        original_record(status, hashes)

    def post_start_failure(passwords, review_authority=None):
        original_verify(passwords, review_authority)
        raise OIDatabaseUnavailable()

    try:
        if operation == "start":
            instance.provision()
            instance.stop()
            baseline = instance.state.read_bytes()
            monkeypatch.setattr(instance, "_verify_server", post_start_failure)
        monkeypatch.setattr(instance, "_record", failing_record)
        with pytest.raises(OIDatabaseUnavailable) as failure:
            getattr(instance, operation)()
        assert str(failure.value) == "OI_DATABASE_RECOVERY_REQUIRED"
        assert not failure.value.cleanup_verified
        assert not (instance.data / "postmaster.pid").exists()
        with socket.socket() as available:
            available.bind(("127.0.0.1", 55571))
        assert baseline is not None and instance.state.read_bytes() == baseline
        assert json.loads(baseline)["status"] == (
            "PROVISIONING" if operation == "provision" else "READY"
        )
        assert records[-1] == "RECOVERY_REQUIRED"
        assert not (instance.local / "oi-database.lock").exists()
        proof["old_receipt_preserved"] = True
        proof["old_receipt_sha256"] = hashlib.sha256(baseline).hexdigest()
        proof["owned_server_stopped_before_failed_recovery_write"] = True
        proof["record_status_attempts"] = records
        complete = True
    finally:
        if complete:
            instance._guard_target()
            assert instance.root.parent == Path(tempfile.gettempdir()).resolve()
            assert instance.root.name == "auvexo-oi-db-test-" + identity.hex
            assert not (instance.data / "postmaster.pid").exists()
            shutil.rmtree(instance.root)
        proof["cleanup_removed_disposable_root"] = not instance.root.exists()
        proof["status"] = "PASS" if complete and not instance.root.exists() else "RECOVERY_REQUIRED"
        (tmp_path / "record-failure-proof.json").write_text(
            json.dumps(proof, indent=2), encoding="utf8"
        )
