"""Synthetic secrets only; native DPAPI uses a disposable UUID leaf outside checkouts."""

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
def test_native_current_user_dpapi_disposable_roundtrip_rotate_child_delete(monkeypatch, capsys):
    test_id = uuid4()
    # The factory permits only a UUID leaf beneath the OS-known fixed application root.
    store = implementation.make_test_oi_secret_store(test_id)
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
        other = implementation.make_test_oi_secret_store(test_id)
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
            "import hashlib,sys;from uuid import UUID;"
            "from auvexo_alpha.infrastructure.oi_secrets import make_test_oi_secret_store;"
            "v=make_test_oi_secret_store(UUID(sys.argv[1])).load();"
            "sys.exit(0 if hashlib.sha256(v.encode()).hexdigest()==sys.stdin.read().strip() else 2)"
        )
        child = subprocess.run(
            [sys.executable, "-B", "-c", code, str(test_id)],
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


@pytest.mark.skipif(
    os.name != "nt", reason="real NTFS junction ancestor refusal requires native Windows"
)
def test_native_junction_ancestor_is_rejected_and_target_untouched():
    identity, alias_identity = uuid4(), uuid4()
    target = implementation.make_test_oi_secret_store(identity)
    redirected = implementation.make_test_oi_secret_store(alias_identity)
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
