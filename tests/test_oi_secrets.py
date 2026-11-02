"""Synthetic secrets only; native DPAPI uses a disposable UUID leaf outside checkouts."""

import ast
import base64
import getpass
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from auvexo_alpha.infrastructure import oi_owner_secrets as owner
from auvexo_alpha.infrastructure import oi_secrets as implementation
from auvexo_alpha.infrastructure.oi_secrets import OISecretUnavailable


class MemoryFiles:
    def __init__(self):
        self.blob = None
        self.writes = 0

    def read(self):
        if self.blob is None:
            raise FileNotFoundError("synthetic missing blob")
        return self.blob

    def write(self, data):
        self.blob = data
        self.writes += 1

    def create(self, data):
        if self.blob is not None:
            raise FileExistsError("synthetic occupied slot")
        self.write(data)

    def delete(self):
        if self.blob is None:
            raise FileNotFoundError("synthetic missing blob")
        self.blob = None


class SyntheticCrypto:
    def protect(self, data):
        return b"synthetic:" + base64.b64encode(data)

    def unprotect(self, data):
        if not data.startswith(b"synthetic:"):
            raise ValueError("synthetic corrupt ciphertext")
        return base64.b64decode(data[10:], validate=True)


def make_store():
    files = MemoryFiles()
    return implementation._SecretStore(files, SyntheticCrypto()), files


def native_factory(slot):
    return {
        "writer": implementation.make_test_oi_secret_store,
        "admin": owner.make_test_oi_admin_secret_store,
        "app": owner.make_test_oi_app_secret_store,
    }[slot]


def check(condition):
    if not condition:
        raise AssertionError("synthetic secret assertion failed")


def failure(call):
    try:
        call()
    except Exception as error:
        check(type(error) is OISecretUnavailable)
        check(str(error) == "OI_DATABASE_SECRET_UNAVAILABLE")
        check(error.__suppress_context__)
    else:
        raise AssertionError("expected generic secret failure")


def tool():
    path = Path(__file__).resolve().parents[1] / "tools/oi_secret.py"
    spec = importlib.util.spec_from_file_location("synthetic_oi_secret_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "value",
    [
        None,
        32,
        b"a" * 64,
        "a" * 31,
        "a" * 129,
        "a" * 31 + "\x00",
        "a" * 31 + "\n",
        "a" * 31 + "\r",
        "a" * 31 + "\t",
        "a" * 31 + "\x7f",
        "a" * 31 + "\u0085",
        "a" * 31 + "\u200b",
    ],
)
def test_invalid_secret_fails_before_persistence_without_disclosure(value):
    store, files = make_store()
    failure(lambda: store.store(value))
    assert files.writes == 0


def test_explicit_synthetic_seam_roundtrip_rotation_deletion_and_stage_ignored():
    store, files = make_store()
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    store.store(first)
    first_blob = files.blob
    check(store.verify() and hmac.compare_digest(store.load(), first))
    store.store(second)
    check(files.blob != first_blob and hmac.compare_digest(store.load(), second))
    # An unselected old/stage blob cannot affect the active file backend's returned blob.
    old_stage = first_blob
    check(old_stage != files.blob)
    store.delete()
    failure(store.load)
    failure(store.verify)
    failure(store.delete)


def test_missing_corrupt_wrong_purpose_duplicate_and_backend_failures_are_generic():
    store, files = make_store()
    failure(store.load)
    for blob in (b"", b"wrong-header", implementation._MAGIC + b"bad", b"x" * 8193):
        files.blob = blob
        failure(store.load)
    secret = secrets.token_urlsafe(40)
    for payload in (
        {"purpose": "wrong-purpose", "version": 1, "password": secret},
        {"purpose": implementation._PURPOSE.decode(), "version": True, "password": secret},
        {"purpose": implementation._PURPOSE.decode(), "version": 1, "password": secret, "extra": 1},
    ):
        files.blob = implementation._MAGIC + SyntheticCrypto().protect(json.dumps(payload).encode())
        failure(store.load)
    duplicated = b'{"purpose":"one","purpose":"two","version":1,"password":"none"}'
    files.blob = implementation._MAGIC + SyntheticCrypto().protect(duplicated)
    failure(store.load)

    class FailedCrypto:
        def protect(self, data):
            raise RuntimeError(secret)

        def unprotect(self, data):
            raise RuntimeError(secret)

    failed = implementation._SecretStore(files, FailedCrypto())
    failure(lambda: failed.store(secret))
    failure(failed.load)


def test_file_backend_failures_never_propagate_details():
    secret = secrets.token_urlsafe(40)

    class FailedFiles:
        def read(self):
            raise OSError(secret)

        def write(self, _):
            raise OSError(secret)

        def delete(self):
            raise OSError(secret)

    store = implementation._SecretStore(FailedFiles(), SyntheticCrypto())
    failure(lambda: store.store(secret))
    failure(store.load)
    failure(store.delete)


def test_production_never_selects_environment_backend_or_password(monkeypatch):
    secret = secrets.token_urlsafe(40)
    monkeypatch.setenv("AUVEXO_OI_DB_PASSWORD", secret)
    monkeypatch.setenv("LOCALAPPDATA", str(Path.cwd()))
    calls = []

    def denied():
        calls.append("native")
        raise OISecretUnavailable()

    monkeypatch.setattr(implementation, "_production_store", denied)
    failure(implementation.load_oi_database_password)
    assert calls == ["native"]


@pytest.mark.skipif(os.name == "nt", reason="non-Windows production refusal is Linux-specific")
def test_non_windows_production_loader_is_fail_closed():
    failure(implementation.load_oi_database_password)
    failure(implementation.verify_oi_database_password)
    failure(lambda: implementation.store_oi_database_password(secrets.token_urlsafe(40)))
    failure(implementation.delete_oi_database_password)


def test_cli_non_tty_store_never_prompts_or_echoes(monkeypatch, capsys):
    module = tool()
    monkeypatch.setattr(sys, "argv", ["oi_secret", "store"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        module.getpass, "getpass", lambda *_: pytest.fail("non-TTY prompt forbidden")
    )
    assert module.main() == 2
    assert capsys.readouterr().out == "OI_DATABASE_SECRET_UNAVAILABLE\n"


def test_cli_warning_fallback_echo_is_forbidden(monkeypatch, capsys):
    import warnings

    module = tool()
    monkeypatch.setattr(sys, "argv", ["oi_secret", "rotate"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def warn(*_):
        warnings.warn("synthetic no console", getpass.GetPassWarning, stacklevel=1)
        pytest.fail("fallback must not return")

    monkeypatch.setattr(module.getpass, "getpass", warn)
    assert module.main() == 2
    assert capsys.readouterr().out == "OI_DATABASE_SECRET_UNAVAILABLE\n"


@pytest.mark.parametrize(
    "operation,status",
    [("store", "STORED"), ("rotate", "STORED"), ("verify", "DECRYPTABLE"), ("delete", "DELETED")],
)
def test_cli_only_generic_status_no_secret_arguments(operation, status, monkeypatch, capsys):
    module = tool()
    secret = secrets.token_urlsafe(40)
    monkeypatch.setattr(sys, "argv", ["oi_secret", operation])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(module.getpass, "getpass", lambda *_: secret)

    def store(value):
        check(hmac.compare_digest(value, secret))

    monkeypatch.setattr(module, "store_oi_database_password", store)
    monkeypatch.setattr(module, "verify_oi_database_password", lambda: True)
    monkeypatch.setattr(module, "delete_oi_database_password", lambda: None)
    assert module.main() == 0
    captured = capsys.readouterr()
    check(secret not in captured.out and secret not in captured.err)
    assert captured.out == "OI_DATABASE_SECRET_" + status + "\n"


@pytest.mark.skipif(
    os.name != "nt",
    reason="real CurrentUser DPAPI and NTFS handle/ACL proof requires native Windows",
)
@pytest.mark.parametrize("slot", ["writer", "admin", "app"])
def test_native_current_user_dpapi_disposable_roundtrip_rotate_child_delete(
    slot, monkeypatch, capsys
):
    test_id = uuid4()
    # The factory permits only a UUID leaf beneath the OS-known fixed application root.
    factory = native_factory(slot)
    store = factory(test_id)
    files = store._files
    secret, rotated = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    created = False
    try:
        store.store(secret)
        created = True
        check(store.verify() and hmac.compare_digest(store.load(), secret))
        first = files.path.read_bytes()
        alias = files.path.parent / ".synthetic-hardlink.stage"
        os.link(files.path, alias)
        try:
            failure(store.verify)
        finally:
            alias.unlink()
        # Corruption is refused; restore only the original disposable encrypted bytes.
        damaged = bytearray(first)
        damaged[-1] ^= 1
        files.path.write_bytes(damaged)
        failure(store.load)
        files.path.write_bytes(first)
        check(store.verify())
        monkeypatch.setenv("LOCALAPPDATA", str(Path.cwd()))
        other = factory(test_id)
        check(hmac.compare_digest(other.load(), secret))
        check(not files.path.is_relative_to(Path.cwd()))
        original_information = files.api.kernel.SetFileInformationByHandle

        def fail_rotation(handle, operation, data, size):
            if operation == 3:
                return False
            return original_information(handle, operation, data, size)

        with monkeypatch.context() as atomic_failure:
            atomic_failure.setattr(files.api.kernel, "SetFileInformationByHandle", fail_rotation)
            failure(lambda: store.store(rotated))
        check(hmac.compare_digest(store.load(), secret))
        check(list(files.path.parent.iterdir()) == [files.path])
        store.store(rotated)
        check(files.path.read_bytes() != first)
        check(hmac.compare_digest(store.load(), rotated))
        expected = hashlib.sha256(rotated.encode()).hexdigest()
        code = (
            "import hashlib,sys;from uuid import UUID;from importlib import import_module;"
            "factory=getattr(import_module(sys.argv[2]),sys.argv[3]);"
            "v=factory(UUID(sys.argv[1])).load();"
            "sys.exit(0 if hashlib.sha256(v.encode()).hexdigest()==sys.stdin.read().strip() else 2)"
        )
        module_name = factory.__module__
        factory_name = factory.__name__
        child = subprocess.run(
            [sys.executable, "-B", "-c", code, str(test_id), module_name, factory_name],
            input=expected,
            capture_output=True,
            text=True,
            timeout=15,
            env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
        )
        check(child.returncode == 0 and not child.stdout and not child.stderr)
        store.delete()
        created = False
        failure(store.load)
        check(not files.path.exists())
        captured = capsys.readouterr()
        check(
            secret not in captured.out + captured.err and rotated not in captured.out + captured.err
        )
    finally:
        if created or files.path.exists():
            store.delete()
        # Remove only this explicitly named, verified disposable UUID directory when empty.
        if files.path.parent.name == "test-" + str(test_id) and files.path.parent.exists():
            files.path.parent.rmdir()


@pytest.mark.parametrize("case", ["reparse", "hardlink", "directory", "oversize", "redirect"])
def test_native_path_check_seam_rejects_unsafe_handles(case):
    from types import SimpleNamespace

    path = Path.cwd() / "synthetic-oi-handle-only"
    files = object.__new__(implementation._WindowsFiles)

    def information(_handle, result):
        info = result._obj
        info.attributes = 0x400 if case == "reparse" else 0x10 if case == "directory" else 0
        info.links = 2 if case == "hardlink" else 1
        info.low_size = 8193 if case == "oversize" else 128
        return True

    def final_path(_handle, output, _length, _flags):
        output.value = str(path.parent / "redirected" if case == "redirect" else path)
        return len(output.value)

    files.api = SimpleNamespace(
        kernel=SimpleNamespace(
            GetFileInformationByHandle=information,
            GetFinalPathNameByHandleW=final_path,
        )
    )
    with pytest.raises(OISecretUnavailable, match="OI_DATABASE_SECRET_UNAVAILABLE"):
        files._check(1, path, directory=False)


def test_cli_unknown_arguments_cannot_echo_accidentally_supplied_secret(monkeypatch, capsys):
    module = tool()
    secret = secrets.token_urlsafe(40)
    monkeypatch.setattr(sys, "argv", ["oi_secret", "store", "--password", secret])
    assert module.main() == 2
    output = capsys.readouterr()
    check(secret not in output.out + output.err)
    assert output.out == "OI_DATABASE_SECRET_UNAVAILABLE\n" and not output.err


@pytest.mark.skipif(os.name != "nt", reason="native DPAPI purpose entropy proof requires Windows")
def test_native_dpapi_wrong_entropy_is_rejected_without_disclosure(monkeypatch):
    crypto = implementation._DPAPI()
    secret = secrets.token_bytes(64)
    encrypted = crypto.protect(secret)
    check(hmac.compare_digest(crypto.unprotect(encrypted), secret))
    monkeypatch.setattr(implementation, "_PURPOSE", b"synthetic-unaccepted-purpose")
    with pytest.raises(OISecretUnavailable, match="OI_DATABASE_SECRET_UNAVAILABLE"):
        crypto.unprotect(encrypted)


def test_knownfolder_location_rule_never_reads_environment_or_checkout(monkeypatch):

    expected = Path.cwd().anchor
    base = Path(expected) / "synthetic-os-known-localappdata"

    class NativeAPISeam:
        def known_local_appdata(self):
            return base

        def current_sid(self):
            return "synthetic-user-sid"

    monkeypatch.setattr(implementation, "_WindowsAPI", NativeAPISeam)
    monkeypatch.setenv("LOCALAPPDATA", str(Path.cwd()))
    production = implementation._WindowsFiles()
    assert production.path == base / "AuvexoAlpha/phase6/oi-db-password.v1.dpapi"
    identity = uuid4()
    test = implementation._WindowsFiles(identity)
    assert (
        test.path
        == base / "AuvexoAlpha/phase6" / ("test-" + str(identity)) / "oi-db-password.v1.dpapi"
    )
    with pytest.raises(OISecretUnavailable):
        implementation.make_test_oi_secret_store("caller-controlled-path")
    for slot in implementation._Slot:
        files = implementation._WindowsFiles(slot=slot)
        assert files.path == base / "AuvexoAlpha/phase6" / slot.filename
    failure(lambda: owner.make_test_oi_admin_secret_store("caller-controlled-path"))
    failure(lambda: owner.make_test_oi_app_secret_store("caller-controlled-path"))


def test_only_three_fixed_slots_preserve_writer_and_reject_arbitrary_values():
    assert set(implementation._Slot.__members__) == {"WRITER", "ADMIN", "APP"}
    assert implementation._Slot.WRITER.purpose == implementation._PURPOSE
    assert implementation._Slot.WRITER.filename == "oi-db-password.v1.dpapi"
    assert implementation._Slot.ADMIN.purpose == (
        b"auvexo-alpha:phase6:ds04-a1:oi-db-admin-password:v1"
    )
    assert implementation._Slot.APP.purpose == b"auvexo-alpha:phase6:ds04-a1:oi-db-app-password:v1"
    assert len({slot.filename for slot in implementation._Slot}) == 3
    for invalid in (None, "admin", "writer", b"custom-purpose", Path("custom")):
        failure(
            lambda value=invalid: implementation._SecretStore(
                MemoryFiles(), SyntheticCrypto(), value
            )
        )
        failure(lambda value=invalid: implementation._DPAPI(value))
        failure(lambda value=invalid: implementation._WindowsFiles(slot=value))


def test_reviewed_writer_v1_envelope_remains_readable_without_recreation():
    store, files = make_store()
    secret = secrets.token_urlsafe(40)
    # Construct the exact reviewed pre-three-slot envelope independently of the new
    # slot selector. No real credential or host-dependent ciphertext is retained.
    reviewed = json.dumps(
        {
            "purpose": "auvexo-alpha:phase6:ds04-a1:oi-db-password:v1",
            "version": 1,
            "password": secret,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    files.blob = b"AUVEXO-OI-DPAPI-V1\x00" + SyntheticCrypto().protect(reviewed)
    before = files.blob
    check(hmac.compare_digest(store.load(), secret))
    check(files.blob == before and files.writes == 0)


@pytest.mark.parametrize("slot", list(implementation._Slot))
def test_each_slot_envelope_rejects_other_slot_even_with_synthetic_crypto(slot):
    files = MemoryFiles()
    secret = secrets.token_urlsafe(40)
    store = implementation._SecretStore(files, SyntheticCrypto(), slot)
    store.store(secret)
    check(hmac.compare_digest(store.load(), secret))
    for other_slot in implementation._Slot:
        if other_slot is not slot:
            other = implementation._SecretStore(files, SyntheticCrypto(), other_slot)
            failure(other.load)


def test_owner_apis_have_fixed_slots_and_generic_failures(monkeypatch):
    calls = []

    class Unavailable:
        def create(self, _secret):
            raise RuntimeError("synthetic-backend-detail")

        def store(self, _secret):
            raise RuntimeError("synthetic-backend-detail")

        def load(self):
            raise RuntimeError("synthetic-backend-detail")

        def verify(self):
            raise RuntimeError("synthetic-backend-detail")

        def delete(self):
            raise RuntimeError("synthetic-backend-detail")

    def fixed(slot):
        calls.append(slot)
        return Unavailable()

    monkeypatch.setattr(owner, "_owner_store", fixed)
    for name, slot in (("admin", implementation._Slot.ADMIN), ("app", implementation._Slot.APP)):
        failure(
            lambda slot_name=name: getattr(owner, f"create_oi_database_{slot_name}_password")(
                "synthetic"
            )
        )
        failure(
            lambda slot_name=name: getattr(owner, f"store_oi_database_{slot_name}_password")(
                "synthetic"
            )
        )
        failure(getattr(owner, f"load_oi_database_{name}_password"))
        failure(getattr(owner, f"verify_oi_database_{name}_password"))
        failure(getattr(owner, f"delete_oi_database_{name}_password"))
        assert calls[-5:] == [slot] * 5
    monkeypatch.setattr(owner, "_production_store", Unavailable)
    failure(lambda: owner.create_oi_database_writer_password("synthetic"))


def test_create_only_secret_operation_does_not_overwrite_or_remove_prior_secret():
    store, files = make_store()
    secret, candidate = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    store.create(secret)
    before = files.blob
    failure(lambda: store.create(candidate))
    check(files.blob == before and files.writes == 1)
    check(hmac.compare_digest(store.load(), secret))
    # Explicit reviewed rotation retains its separate overwrite semantics.
    store.store(candidate)
    check(hmac.compare_digest(store.load(), candidate))


@pytest.mark.skipif(os.name != "nt", reason="atomic native no-replace rename requires Windows")
@pytest.mark.parametrize("slot", ["writer", "admin", "app"])
def test_native_create_only_refuses_preexisting_and_snapshot_race(slot, monkeypatch, capsys):
    identity = uuid4()
    store = native_factory(slot)(identity)
    competing = native_factory(slot)(identity)
    files = store._files
    first, candidate, raced = (secrets.token_urlsafe(40) for _ in range(3))
    try:
        files.require_absent()
        store.create(first)
        before = files.path.read_bytes()
        failure(lambda: store.create(candidate))
        check(files.path.read_bytes() == before and hmac.compare_digest(store.load(), first))
        store.delete()
        files.require_absent()
        native_information = files.api.kernel.SetFileInformationByHandle
        introduced = False

        def race_at_atomic_commit(handle, operation, data, size):
            nonlocal introduced
            if operation == 3 and not introduced:
                introduced = True
                # A different explicitly owned test writer creates the slot after
                # the absence snapshot and native precheck but before commit.
                competing.create(raced)
            return native_information(handle, operation, data, size)

        with monkeypatch.context() as race:
            race.setattr(files.api.kernel, "SetFileInformationByHandle", race_at_atomic_commit)
            failure(lambda: store.create(candidate))
        check(introduced and hmac.compare_digest(store.load(), raced))
        check(list(files.path.parent.iterdir()) == [files.path])
        output = capsys.readouterr()
        check(all(secret not in output.out + output.err for secret in (first, candidate, raced)))
    finally:
        # The competing write is also this test's own disposable fixture, and is
        # removed only after assertions prove failed create left it intact.
        if files.path.exists():
            store.delete()
        if files.path.parent.exists():
            files.path.parent.rmdir()


def test_owner_absent_preflight_checks_exact_three_slots_without_decryption(monkeypatch):
    calls = []

    class Absent:
        def __init__(self, *, slot):
            calls.append(slot)

        def require_absent(self):
            return None

    monkeypatch.setattr(owner, "_WindowsFiles", Absent)
    owner.require_oi_database_credentials_absent()
    assert calls == [
        implementation._Slot.ADMIN,
        implementation._Slot.APP,
        implementation._Slot.WRITER,
    ]

    class Occupied(Absent):
        def require_absent(self):
            raise RuntimeError("synthetic-existing-or-corrupt-secret")

    monkeypatch.setattr(owner, "_WindowsFiles", Occupied)
    failure(owner.require_oi_database_credentials_absent)


def test_collector_imports_writer_loader_only_and_no_owner_secret_module():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "tools/run_oi_collection.py",
        root / "src/auvexo_alpha/infrastructure/oi_collection.py",
        root / "src/auvexo_alpha/infrastructure/oi_runtime.py",
        root / "src/auvexo_alpha/infrastructure/oi_store.py",
    ]
    secret_imports = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "oi_owner_secrets" not in source
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module and "oi_secrets" in node.module:
                secret_imports.extend(alias.name for alias in node.names)
    assert secret_imports == ["load_oi_database_password"]


@pytest.mark.skipif(os.name != "nt", reason="native cross-slot CurrentUser DPAPI requires Windows")
def test_native_three_slots_refuse_cross_slot_ciphertext_and_cleanup(capsys):
    identity = uuid4()
    stores = [native_factory(name)(identity) for name in ("writer", "admin", "app")]
    created = []
    secrets_by_slot = [secrets.token_urlsafe(40) for _ in stores]
    try:
        for store, secret in zip(stores, secrets_by_slot, strict=True):
            store._files.require_absent()
            store.store(secret)
            created.append(store)
            failure(store._files.require_absent)
        blobs = [store._files.path.read_bytes() for store in stores]
        for index, store in enumerate(stores):
            for other_index, blob in enumerate(blobs):
                if index == other_index:
                    continue
                # Copy only synthetic ciphertext into this test UUID's fixed slot.
                store._files.path.write_bytes(blob)
                failure(store.load)
                store._files.path.write_bytes(blobs[index])
            check(hmac.compare_digest(store.load(), secrets_by_slot[index]))
        captured = capsys.readouterr()
        check(all(secret not in captured.out + captured.err for secret in secrets_by_slot))
    finally:
        for store in created:
            if store._files.path.exists():
                store.delete()
        parent = stores[0]._files.path.parent
        if parent.exists() and parent.name == "test-" + str(identity):
            parent.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="native fixed-slot absence checks require Windows")
def test_native_absence_preflight_refuses_existing_corrupt_slot_without_repair():
    identity = uuid4()
    store = owner.make_test_oi_admin_secret_store(identity)
    files = store._files
    try:
        files.require_absent()
        check(not files.path.parent.exists())
        store.store(secrets.token_urlsafe(40))
        files.path.write_bytes(b"synthetic-corrupt-ciphertext")
        before = files.path.read_bytes()
        failure(files.require_absent)
        check(files.path.read_bytes() == before)
        failure(store.load)
    finally:
        if files.path.exists():
            store.delete()
        if files.path.parent.exists():
            files.path.parent.rmdir()


@pytest.mark.skipif(
    os.name != "nt", reason="real NTFS junction ancestor refusal requires native Windows"
)
@pytest.mark.parametrize("slot", ["writer", "admin", "app"])
def test_native_junction_ancestor_is_rejected_and_target_untouched(slot):
    identity, alias_identity = uuid4(), uuid4()
    target = native_factory(slot)(identity)
    redirected = native_factory(slot)(alias_identity)
    target_files, alias_files = target._files, redirected._files
    secret = secrets.token_urlsafe(40)
    linked = False
    created = False
    try:
        target.store(secret)
        created = True
        before = target_files.path.read_bytes()
        result = subprocess.run(
            [
                "cmd",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(alias_files.path.parent),
                str(target_files.path.parent),
            ],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        check(result.returncode == 0)
        linked = True
        failure(alias_files.require_absent)
        failure(redirected.load)
        failure(lambda: redirected.store(secrets.token_urlsafe(40)))
        failure(redirected.delete)
        check(
            target_files.path.read_bytes() == before and hmac.compare_digest(target.load(), secret)
        )
    finally:
        if linked:
            metadata = alias_files.path.parent.lstat()
            check(bool(getattr(metadata, "st_file_attributes", 0) & 0x400))
            os.rmdir(alias_files.path.parent)
        if created or target_files.path.exists():
            target.delete()
        if target_files.path.parent.exists():
            target_files.path.parent.rmdir()
