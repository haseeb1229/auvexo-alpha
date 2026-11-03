"""D3-07: synthetic passwords only; native UUID leaves never select real slots."""

import ast
import base64
import hmac
import inspect
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from auvexo_alpha.infrastructure import ds03_secrets as secret
from auvexo_alpha.infrastructure import oi_secrets as oi

FIRST = "Ab3!synthetic"
SECOND = "Cd4@synthetic"


class MemoryFiles:
    def __init__(self):
        self.blob = None

    def read(self):
        if self.blob is None:
            raise FileNotFoundError("synthetic missing")
        return self.blob

    def write(self, data):
        self.blob = data

    def create(self, data):
        if self.blob is not None:
            raise FileExistsError("synthetic occupied")
        self.write(data)

    def delete(self):
        if self.blob is None:
            raise FileNotFoundError("synthetic missing")
        self.blob = None


class SyntheticCrypto:
    def protect(self, data):
        return b"synthetic:" + base64.b64encode(data)

    def unprotect(self, data):
        if not data.startswith(b"synthetic:"):
            raise ValueError("synthetic corrupt")
        return base64.b64decode(data[10:], validate=True)


def fixture_store():
    files = MemoryFiles()
    return secret._SecretStore(files, SyntheticCrypto()), files


def failure(call):
    with pytest.raises(secret.Ds03SecretUnavailable) as captured:
        call()
    assert str(captured.value) == "DS03_SECRET_UNAVAILABLE"
    assert captured.value.__suppress_context__


@pytest.mark.parametrize("value", ["Ab3!efgh", "Ab3!efghijklmno", FIRST, SECOND])
def test_provider_password_contract_accepts_eight_through_fifteen(value):
    store, files = fixture_store()
    store.create(value)
    assert files.blob.startswith(secret._MAGIC)
    assert store.verify() and hmac.compare_digest(store.load(), value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        12345678,
        b"Ab3!efgh",
        "Ab3!efg",
        "Ab3!efghijklmnop",
        "ab3!efgh",
        "AB3!EFGH",
        "Abc!efgh",
        "Ab34efgh",
        "Ab3 efgh",
        "Ab3!efg\n",
        "Ab3!efg\x00",
        "Ab3!efg\x7f",
        "Ab3!efg\t",
        "Ab3!efg\u00e9",
        "Ab3!efg\u200b",
        "A" * 32,
    ],
)
def test_provider_invalid_values_fail_before_encryption_or_persistence(value):
    store, files = fixture_store()
    failure(lambda: store.create(value))
    assert files.blob is None


def test_create_no_replace_rotation_deletion_and_missing_are_redacted(capsys):
    store, files = fixture_store()
    for operation in (store.load, store.verify, store.delete, lambda: store.rotate(SECOND)):
        failure(operation)
    store.create(FIRST)
    original = files.blob
    failure(lambda: store.create(SECOND))
    assert files.blob == original and hmac.compare_digest(store.load(), FIRST)
    store.rotate(SECOND)
    assert files.blob != original and hmac.compare_digest(store.load(), SECOND)
    failure(lambda: store.rotate("invalid"))
    assert hmac.compare_digest(store.load(), SECOND)
    store.delete()
    failure(store.load)
    captured = capsys.readouterr()
    assert FIRST not in captured.out + captured.err and SECOND not in captured.out + captured.err


@pytest.mark.parametrize("blob", [b"", b"bad", b"x" * 8193, secret._MAGIC, secret._MAGIC + b"bad"])
def test_corrupt_ciphertext_is_generic(blob):
    store, files = fixture_store()
    files.blob = blob
    failure(store.load)


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "wrong-purpose"},
        {"version": True},
        {"version": 2},
        {"version": "1"},
        {"password": "invalid"},
        {"extra": 1},
        {"purpose": oi._PURPOSE.decode()},
    ],
)
def test_envelope_rejects_wrong_purpose_types_unknown_fields(change):
    store, files = fixture_store()
    payload = {"purpose": secret._PURPOSE.decode(), "version": 1, "password": FIRST} | change
    files.blob = secret._MAGIC + SyntheticCrypto().protect(json.dumps(payload).encode())
    failure(store.load)


def test_duplicate_keys_and_oversized_plaintext_are_refused():
    store, files = fixture_store()
    for plain in (
        b'{"purpose":"one","purpose":"two","version":1,"password":"Ab3!synthetic"}',
        b" " * 4097,
        b"null",
        b"[]",
    ):
        files.blob = secret._MAGIC + SyntheticCrypto().protect(plain)
        failure(store.load)


def test_backend_failures_and_failed_rotation_never_disclose_or_destroy():
    store, files = fixture_store()
    store.create(FIRST)
    before = files.blob

    class FailedFiles(MemoryFiles):
        def write(self, data):
            raise OSError(SECOND)

        def delete(self):
            raise OSError(FIRST)

    failing = FailedFiles()
    failing.blob = before
    broken = secret._SecretStore(failing, SyntheticCrypto())
    failure(lambda: broken.rotate(SECOND))
    failure(broken.delete)
    assert failing.blob == before and hmac.compare_digest(broken.load(), FIRST)

    class FailedCrypto:
        def protect(self, data):
            raise RuntimeError(FIRST)

        def unprotect(self, data):
            raise RuntimeError(SECOND)

    broken = secret._SecretStore(files, FailedCrypto())
    failure(lambda: broken.create(FIRST))
    failure(broken.load)
    assert files.blob == before


def test_production_admission_gate_and_wrapper_order_before_native_or_environment_access(
    monkeypatch,
):
    calls = []

    def deny():
        calls.append(True)
        raise AssertionError("production must not construct native APIs")

    monkeypatch.setattr(secret, "_WindowsAPI", deny)
    monkeypatch.setenv("AUVEXO_DS03_PASSWORD", FIRST)
    monkeypatch.setenv("AUVEXO_DS03_ENABLE", "true")
    monkeypatch.setenv("LOCALAPPDATA", str(Path.cwd()))
    # PR12 prohibits even public verification invoking a production API. Preserve
    # denied-admission/no-effects proof at the shared private gate, and statically
    # prove every thin production wrapper reaches that gate before native access.
    for invalid in (None, True, object(), FIRST):
        failure(lambda value=invalid: secret._require_admission(value, None))
    for name in (
        "create_ds03_readonly_password",
        "rotate_ds03_readonly_password",
        "load_ds03_readonly_password",
        "verify_ds03_readonly_password",
        "delete_ds03_readonly_password",
    ):
        source = inspect.getsource(vars(secret)[name])
        parsed = ast.parse(source)
        direct = [
            node.func.id
            for node in ast.walk(parsed)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_require_admission" in direct
        assert "_bound_production_store" in direct
        assert source.index("_require_admission(") < source.index("_bound_production_store(")
    source = inspect.getsource(secret.require_ds03_readonly_password_absent)
    assert source.index("_require_admission(") < source.index("_DS03WindowsFiles()")
    for invalid in (None, "custom/path", b"purpose", Path.cwd(), 0):
        failure(lambda value=invalid: secret.make_test_ds03_secret_store(value))
    assert calls == []


def test_fixed_native_constructor_has_no_oi_slot_or_arbitrary_path(monkeypatch):
    base = Path(Path.cwd().anchor) / "synthetic-os-known-localappdata"

    class NativeAPISeam:
        def known_local_appdata(self):
            return base

        def current_sid(self):
            return "synthetic-owner"

    monkeypatch.setattr(secret, "_WindowsAPI", NativeAPISeam)
    monkeypatch.setenv("LOCALAPPDATA", str(Path.cwd()))
    identity = uuid4()
    native = secret.make_test_ds03_secret_store(identity)
    assert native._files.path == (
        base / "AuvexoAlpha/phase2/ds03" / ("test-" + str(identity)) / secret._FILENAME
    )
    assert native._crypto._purpose() == secret._PURPOSE
    assert not hasattr(native._crypto, "_slot")
    assert secret._DS03WindowsFiles._write is oi._WindowsFiles._write
    assert secret._DS03WindowsFiles._check is oi._WindowsFiles._check
    assert secret._DS03WindowsFiles._parent is oi._WindowsFiles._parent
    assert secret._DS03DPAPI._transform is oi._DPAPI._transform


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI/NTFS proof requires Windows")
def test_native_ds03_disposable_roundtrip_hardlink_atomic_rotation_corrupt_delete(
    monkeypatch, capsys
):
    identity = uuid4()
    store = secret.make_test_ds03_secret_store(identity)
    files = store._files
    created = False
    try:
        store.create(FIRST)
        created = True
        original = files.path.read_bytes()
        assert FIRST.encode() not in original
        assert hmac.compare_digest(store.load(), FIRST)
        failure(lambda: store.create(SECOND))
        assert files.path.read_bytes() == original
        alias = files.path.parent / ".synthetic-hardlink.stage"
        os.link(files.path, alias)
        try:
            failure(store.load)
        finally:
            alias.unlink()
        damaged = bytearray(original)
        damaged[-1] ^= 1
        files.path.write_bytes(damaged)
        failure(store.load)
        files.path.write_bytes(original)
        original_information = files.api.kernel.SetFileInformationByHandle

        def deny_rotation(handle, operation, data, size):
            if operation == 3:
                return False
            return original_information(handle, operation, data, size)

        with monkeypatch.context() as context:
            context.setattr(files.api.kernel, "SetFileInformationByHandle", deny_rotation)
            failure(lambda: store.rotate(SECOND))
        assert hmac.compare_digest(store.load(), FIRST)
        assert list(files.path.parent.iterdir()) == [files.path]
        store.rotate(SECOND)
        assert files.path.read_bytes() != original
        assert hmac.compare_digest(store.load(), SECOND)
        # Different CurrentUser entropy cannot decrypt even under the same Windows user.
        with pytest.raises(oi.OISecretUnavailable):
            oi._DPAPI().unprotect(files.path.read_bytes()[len(secret._MAGIC) :])
        store.delete()
        created = False
        failure(store.load)
        captured = capsys.readouterr()
        assert (
            FIRST not in captured.out + captured.err and SECOND not in captured.out + captured.err
        )
    finally:
        if created or files.path.exists():
            store.delete()
        if files.path.parent.name == "test-" + str(identity) and files.path.parent.exists():
            files.path.parent.rmdir()
