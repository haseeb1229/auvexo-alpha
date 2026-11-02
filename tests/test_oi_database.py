"""Owner provisioner unit negatives; no production resource is created."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from auvexo_alpha.infrastructure import oi_database as module
from auvexo_alpha.infrastructure.oi_database import (
    OIDatabaseUnavailable,
    OIRuntimeDatabase,
    _Passwords,
    _WindowsSlots,
)

ROOT = Path(__file__).resolve().parents[1]


class MemorySlots:
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


def disposable():
    return OIRuntimeDatabase._for_test(
        uuid4(), 55571, ROOT / ".local/toolchains/postgres/pgsql/bin", ROOT, MemorySlots()
    )


def test_production_tool_refuses_development_and_operational_without_writes():
    for source in (ROOT, ROOT.parent / "Auvexo Alpha"):
        with pytest.raises(OIDatabaseUnavailable):
            OIRuntimeDatabase(source)


@pytest.mark.parametrize("port", [55432, 55433, 55434, 1, 65536, "55551", True])
def test_disposable_target_refuses_every_unsafe_port(port):
    with pytest.raises(OIDatabaseUnavailable):
        OIRuntimeDatabase._for_test(uuid4(), port, ROOT, ROOT, MemorySlots())


def test_disposable_target_cannot_use_production_secret_store():
    with pytest.raises(OIDatabaseUnavailable):
        OIRuntimeDatabase._for_test(uuid4(), 55571, ROOT, ROOT, _WindowsSlots())


@pytest.mark.parametrize(
    "change",
    [
        {"port": 55432},
        {"port": 55433},
        {"database": "auvexo_dev_oiresearch"},
        {"root": ROOT},
        {"test_id": None},
    ],
)
@pytest.mark.parametrize("operation", ["provision", "verify", "start", "stop"])
def test_mutated_test_seam_cannot_become_production_escape(change, operation):
    instance = disposable()
    original = instance.root
    for name, value in change.items():
        setattr(instance, name, value)
    with pytest.raises(OIDatabaseUnavailable):
        getattr(instance, operation)()
    assert not original.exists()


def test_password_generation_distinct_strong_and_repr_redacted():
    passwords = _Passwords.generate()
    values = [passwords.admin, passwords.app, passwords.writer]
    assert len(set(values)) == 3
    assert all(32 <= len(value) <= 128 and value.isprintable() for value in values)
    leaked = any(value in repr(passwords) for value in values)
    assert not leaked


def test_native_environment_excludes_password_dsn_and_service(monkeypatch):
    for name in ("PGPASSWORD", "PGPASSFILE", "PGSERVICE", "AUVEXO_MIGRATION_DSN", "OI_TEST_SECRET"):
        monkeypatch.setenv(name, "synthetic-sensitive-test-only")
    environment = module._native_environment()
    assert not set(environment).intersection(
        {"PGPASSWORD", "PGPASSFILE", "PGSERVICE", "AUVEXO_MIGRATION_DSN", "OI_TEST_SECRET"}
    )


def test_native_pwprompt_only_stdin_and_redacted_failure(monkeypatch, tmp_path):
    executable = tmp_path / "initdb.exe"
    executable.write_bytes(b"synthetic-test-not-run")
    password = _Passwords.generate().admin
    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, b"prompt without secret", b"")

    monkeypatch.setattr(module, "_supervised_run", fake_run)
    assert module._run(executable, ["--pwprompt"], password=password) == b"prompt without secret"
    assert recorded["input"] == (password + "\n" + password + "\n").encode("ascii")
    leaked = any(password in item for item in [*recorded["argv"], *recorded["env"].values()])
    assert not leaked
    assert "--pwfile" not in recorded["argv"]

    def failed_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1, output=password)

    monkeypatch.setattr(module, "_supervised_run", failed_run)
    with pytest.raises(OIDatabaseUnavailable) as failure:
        module._run(executable, ["--pwprompt"], password=password)
    assert str(failure.value) == "OI_DATABASE_RECOVERY_REQUIRED"
    assert failure.value.__suppress_context__


def test_native_rejects_secret_echo(monkeypatch, tmp_path):
    executable = tmp_path / "initdb.exe"
    executable.write_bytes(b"synthetic-test-not-run")
    password = _Passwords.generate().admin
    monkeypatch.setattr(
        module,
        "_supervised_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, password.encode(), b""),
    )
    with pytest.raises(OIDatabaseUnavailable):
        module._run(executable, ["--pwprompt"], password=password)


def test_fixed_cli_has_no_test_or_target_override():
    for arguments in (
        ["provision", "--port", "55432"],
        ["verify", "--database", "auvexo_dev"],
        ["provision", "--test"],
        ["verify"],
    ):
        result = subprocess.run(
            [sys.executable, "tools/oi_runtime_db.py", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert result.stdout.strip() == "OI_DATABASE_RECOVERY_REQUIRED"
        assert result.stderr == ""


def test_existing_lock_refuses_and_preserves_owner_record():
    instance = disposable()
    instance.local.mkdir(parents=True)
    lock = instance.local / "oi-database.lock"
    content = json.dumps({"test-owned": True})
    lock.write_text(content)
    try:
        with pytest.raises(OIDatabaseUnavailable):
            with instance._exclusive():
                pytest.fail("existing lock must refuse")
        assert lock.read_text() == content
    finally:
        lock.unlink()
        instance.local.rmdir()
        instance.root.rmdir()


def test_exclusive_lock_only_removes_own_file():
    instance = disposable()
    try:
        with instance._exclusive():
            assert (instance.local / "oi-database.lock").is_file()
        assert not (instance.local / "oi-database.lock").exists()
    finally:
        instance.local.rmdir()
        instance.root.rmdir()


def test_no_generic_production_target_api():
    import inspect

    assert list(inspect.signature(OIRuntimeDatabase).parameters) == ["source_root"]
    assert not hasattr(OIRuntimeDatabase, "reset")
    assert not hasattr(OIRuntimeDatabase, "delete")


@pytest.mark.parametrize("failed_slot", ["app", "writer"])
def test_windows_partial_create_keeps_success_and_concurrent_slot(monkeypatch, failed_slot):
    from auvexo_alpha.infrastructure import oi_owner_secrets

    retained = {failed_slot: "synthetic-concurrent-owner-blob"}
    calls = []

    def create(slot):
        def operation(secret):
            calls.append(slot)
            if slot in retained:
                raise OIDatabaseUnavailable()
            retained[slot] = "synthetic-created-encrypted-blob"

        return operation

    for slot in ("admin", "app", "writer"):
        monkeypatch.setattr(
            oi_owner_secrets, "create_oi_database_" + slot + "_password", create(slot)
        )
    with pytest.raises(OIDatabaseUnavailable):
        _WindowsSlots().store(_Passwords.generate())
    assert retained[failed_slot] == "synthetic-concurrent-owner-blob"
    assert retained["admin"] == "synthetic-created-encrypted-blob"
    assert calls == (["admin", "app"] if failed_slot == "app" else ["admin", "app", "writer"])
    assert "writer" not in retained if failed_slot == "app" else "app" in retained


@pytest.mark.skipif(
    os.name != "nt", reason="native Windows production clock path with synthetic failure"
)
@pytest.mark.parametrize("operation", ["provision", "start"])
def test_production_clock_failure_precedes_every_mutating_effect(monkeypatch, operation):
    from auvexo_alpha.infrastructure import oi_runtime

    expected = Path.home() / "Desktop" / "Auvexo Alpha OI Runtime"
    assert not expected.exists()

    instance = OIRuntimeDatabase(expected)
    monkeypatch.setattr(
        module.subprocess, "check_output", lambda *args, **kwargs: "Local CMOS Clock"
    )
    monkeypatch.setattr(
        oi_runtime, "inspect_clock", MagicMock(side_effect=ValueError("OI_CLOCK_UNTRUSTED"))
    )
    exclusive, tools, native, slots = (MagicMock() for _ in range(4))
    monkeypatch.setattr(instance, "_exclusive", exclusive)
    monkeypatch.setattr(instance, "_toolchain", tools)
    monkeypatch.setattr(module, "_run", native)
    monkeypatch.setattr(instance.slots, "require_absent", slots)
    with pytest.raises(OIDatabaseUnavailable):
        getattr(instance, operation)()
    for effect in (exclusive, tools, native, slots):
        effect.assert_not_called()
    assert not expected.exists()


@pytest.mark.parametrize("inspection", ["initial_process", "children"])
def test_supervisor_inspection_failure_still_kills_exact_parent(monkeypatch, tmp_path, inspection):
    executable = tmp_path / "initdb.exe"
    executable.write_bytes(b"synthetic-not-executed")
    parent = MagicMock()
    parent.pid = 123456
    parent.poll.return_value = None
    parent.communicate.side_effect = [subprocess.TimeoutExpired([str(executable)], 1), (b"", b"")]
    monkeypatch.setattr(module.subprocess, "Popen", MagicMock(return_value=parent))
    process = MagicMock()
    process.create_time.return_value = 123.0
    process.exe.return_value = str(executable)
    process.children.side_effect = PermissionError("synthetic-access-denied")
    factory = MagicMock()
    factory.Process.side_effect = (
        PermissionError("synthetic-access-denied") if inspection == "initial_process" else None
    )
    factory.Process.return_value = process
    monkeypatch.setattr(module.importlib, "import_module", lambda name: factory)
    with pytest.raises(OIDatabaseUnavailable) as failure:
        module._supervised_run(
            [str(executable)],
            input=None,
            capture_output=True,
            env={},
            creationflags=0,
            timeout=1,
            check=False,
        )
    parent.kill.assert_called_once()
    assert parent.communicate.call_count == 2
    assert parent.communicate.call_args.kwargs["timeout"] == 3
    assert not failure.value.cleanup_verified


@pytest.mark.parametrize(
    "name", ["postgresql.conf", "postgresql.auto.conf", "pg_hba.conf", "pg_ident.conf"]
)
def test_configuration_hardlink_refused_before_tool_or_process(monkeypatch, name):
    import shutil

    instance = disposable()
    instance.data.mkdir(parents=True)
    try:
        instance.state.write_text("{}")
        (instance.data / "PG_VERSION").write_text("17")
        for item in module._CONFIGURATION:
            (instance.data / item).write_text("synthetic-test-configuration")
        outside = instance.local / "synthetic-link-target"
        outside.write_text("synthetic-test-configuration")
        (instance.data / name).unlink()
        os.link(outside, instance.data / name)
        tool = MagicMock()
        monkeypatch.setattr(instance, "_toolchain", tool)
        with pytest.raises(OIDatabaseUnavailable):
            instance._attest_files()
        tool.assert_not_called()
        assert outside.read_text() == "synthetic-test-configuration"
    finally:
        instance._guard_target()
        assert instance.root.name == "auvexo-oi-db-test-" + instance.test_id.hex
        shutil.rmtree(instance.root)


@pytest.mark.parametrize("operation", ["provision", "start"])
@pytest.mark.parametrize("failure_type", [PermissionError, FileNotFoundError, OSError])
def test_owned_cleanup_precedes_failing_recovery_receipt(monkeypatch, operation, failure_type):
    import shutil

    instance = disposable()
    events = []
    original_record = instance._record
    instance.slots.passwords = _Passwords.generate() if operation == "start" else None

    def record(status, hashes):
        events.append("record:" + status)
        if status == "RECOVERY_REQUIRED":
            raise failure_type("synthetic-receipt-write-failure")
        original_record(status, hashes)

    def native(executable, arguments, **kwargs):
        assert (instance.local / "oi-database.lock").exists()
        if executable.stem == "initdb":
            instance.data.mkdir(parents=True)
            for name in module._CONFIGURATION:
                (instance.data / name).write_bytes(b"synthetic-configuration")
        else:
            events.append("native:" + arguments[-1])
        return b""

    monkeypatch.setattr(instance, "_toolchain", lambda: {})
    monkeypatch.setattr(instance, "_record", record)
    monkeypatch.setattr(module, "_run", native)
    monkeypatch.setattr(
        instance, "_connect", MagicMock(side_effect=ValueError("synthetic-failure"))
    )
    monkeypatch.setattr(
        instance, "_verify_server", MagicMock(side_effect=ValueError("synthetic-failure"))
    )
    if operation == "start":
        instance.local.mkdir(parents=True)
        instance.state.write_bytes(b'{"status":"READY","tools":{}}')
        monkeypatch.setattr(instance, "_attest_files", lambda: None)
    try:
        with pytest.raises(OIDatabaseUnavailable) as failure:
            getattr(instance, operation)()
        assert "native:stop" in events
        assert events.index("native:stop") < events.index("record:RECOVERY_REQUIRED")
        assert str(failure.value) == "OI_DATABASE_RECOVERY_REQUIRED"
        assert not failure.value.cleanup_verified
        assert json.loads(instance.state.read_bytes())["status"] == (
            "PROVISIONING" if operation == "provision" else "READY"
        )
        assert not (instance.local / "oi-database.lock").exists()
    finally:
        instance._guard_target()
        assert instance.root.name == "auvexo-oi-db-test-" + instance.test_id.hex
        shutil.rmtree(instance.root)
