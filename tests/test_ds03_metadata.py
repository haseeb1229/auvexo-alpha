"""M5-07 synthetic metadata/native lifecycle only; never invokes production APIs."""

import ast
import inspect
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from test_ds03_authority import admitted_fixture, authority_fixture
from test_ds03_secrets import FIRST, MemoryFiles, SyntheticCrypto

from auvexo_alpha.infrastructure import ds03_metadata as metadata
from auvexo_alpha.infrastructure import ds03_secrets as secret
from auvexo_alpha.infrastructure import oi_secrets as oi


def fixture_store():
    files = MemoryFiles()
    return metadata._MetadataStore(files, SyntheticCrypto()), files


def failure(call):
    with pytest.raises(metadata.Ds03MetadataUnavailable) as captured:
        call()
    assert str(captured.value) == "DS03_METADATA_UNAVAILABLE"
    assert captured.value.__suppress_context__


def test_synthetic_metadata_atomic_create_rotate_delete_and_no_account_switch():
    authority, info, binding, now = authority_fixture()
    store, files = fixture_store()
    failure(store.load)
    failure(store.delete)
    store.create(info)
    first = files.blob
    failure(lambda: store.create(info))
    assert files.blob == first and store.load() == info
    changed = info.model_copy(update={"owner_readonly_selection_ref": "synthetic.renewed"})
    store.rotate(changed)
    assert store.load() == changed
    before = files.blob
    failure(lambda: store.rotate(info.model_copy(update={"login": 987654321})))
    failure(lambda: store.rotate(info.model_copy(update={"assigned_server": "synthetic.other"})))
    assert files.blob == before and store.load() == changed
    store.delete()
    failure(store.load)


@pytest.mark.parametrize(
    "blob", [b"", b"bad", b"x" * 8193, metadata._MAGIC, metadata._MAGIC + b"bad"]
)
def test_missing_corrupt_and_wrong_ciphertext_refuse(blob):
    store, files = fixture_store()
    files.blob = blob
    failure(store.load)


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "wrong"},
        {"purpose": secret._PURPOSE.decode()},
        {"version": True},
        {"version": 2},
        {"extra": 1},
        {"metadata": {"login": 1}},
    ],
)
def test_metadata_envelope_wrong_purpose_unknown_and_invalid_fields_refuse(change):
    authority, info, binding, now = authority_fixture()
    store, files = fixture_store()
    payload = {"purpose": metadata._PURPOSE.decode(), "version": 1, "metadata": info.model_dump()}
    files.blob = metadata._MAGIC + SyntheticCrypto().protect(json.dumps(payload | change).encode())
    failure(store.load)


def test_duplicate_oversized_private_backend_failures_and_atomic_old_value_retained(monkeypatch):
    authority, info, binding, now = authority_fixture()
    store, files = fixture_store()
    for plain in (b'{"purpose":"a","purpose":"b"}', b" " * 4097):
        files.blob = metadata._MAGIC + SyntheticCrypto().protect(plain)
        failure(store.load)
    files.blob = None
    store.create(info)
    original = files.blob

    class FailedFiles(MemoryFiles):
        def write(self, data):
            raise OSError(str(info.login) + info.assigned_server)

    failed = FailedFiles()
    failed.blob = original
    broken = metadata._MetadataStore(failed, SyntheticCrypto())
    failure(lambda: broken.rotate(info))
    assert failed.blob == original and broken.load() == info
    static, full, now = admitted_fixture()
    from auvexo_alpha.infrastructure import ds03_mt5_binding

    monkeypatch.setattr(ds03_mt5_binding, "measure_binding", lambda **kwargs: static.binding)
    for invalid in (None, True, object(), static):
        failure(lambda value=invalid: metadata._require_full(value, now))
    failure(lambda: metadata._require_authority(static, now.replace(tzinfo=None)))
    assert metadata._require_authority(static, now) is static
    assert metadata._require_full(full, now) is full


def test_native_fixed_metadata_slot_and_password_slot_are_distinct(monkeypatch):
    base = Path(Path.cwd().anchor) / "synthetic-os-localappdata"

    class NativeAPISeam:
        def known_local_appdata(self):
            return base

        def current_sid(self):
            return "synthetic-owner"

    monkeypatch.setattr(secret, "_WindowsAPI", NativeAPISeam)
    identity = uuid4()
    store = metadata.make_test_ds03_metadata_store(identity)
    assert store._files.path == (
        base / "AuvexoAlpha/phase2/ds03" / ("test-" + str(identity)) / metadata._FILENAME
    )
    assert store._crypto._purpose() == metadata._PURPOSE
    assert store._crypto._purpose() != secret._PURPOSE
    assert metadata._MetadataWindowsFiles._write is oi._WindowsFiles._write
    for invalid in (None, "arbitrary/path", b"purpose", Path.cwd()):
        failure(lambda value=invalid: metadata.make_test_ds03_metadata_store(value))
    assert secret._DS03WindowsFiles().path == base / "AuvexoAlpha/phase2/ds03" / secret._FILENAME
    assert metadata._MetadataWindowsFiles().path == (
        base / "AuvexoAlpha/phase2/ds03" / metadata._FILENAME
    )


def test_all_public_effects_have_admission_gates_without_invoking_production():
    # Inspect delegation only: public engineering never invokes a production API/path.
    for name in (
        "require_ds03_account_metadata_absent",
        "create_ds03_account_metadata",
        "load_ds03_account_metadata",
        "rotate_ds03_account_metadata",
        "delete_ds03_account_metadata",
    ):
        function = vars(metadata)[name]
        tree = ast.parse(inspect.getsource(function))
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_require_authority" in calls or "_require_full" in calls
    tree = ast.parse(inspect.getsource(metadata.verify_ds03_account_metadata))
    assert any(
        isinstance(node, ast.Name) and node.id == "load_ds03_account_metadata"
        for node in ast.walk(tree)
    )
    for name in (
        "create_ds03_readonly_password",
        "load_ds03_readonly_password",
        "verify_ds03_readonly_password",
        "rotate_ds03_readonly_password",
        "delete_ds03_readonly_password",
    ):
        tree = ast.parse(inspect.getsource(vars(secret)[name]))
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_require_admission" in calls and "_bound_production_store" in calls
    source = inspect.getsource(secret._bound_production_store)
    assert source.index("_require_admission") < source.index("load_ds03_account_metadata(checked")
    assert source.index("load_ds03_account_metadata(checked") < source.index(
        "return _production_store()"
    )


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI/ACL proof requires native Windows")
def test_native_disposable_metadata_production_mechanics_acl_hardlink_cross_purpose(
    monkeypatch, capsys
):
    authority, info, binding, now = authority_fixture()
    identity = uuid4()
    store = metadata.make_test_ds03_metadata_store(identity)
    password = secret.make_test_ds03_secret_store(identity)
    files = store._files
    try:
        files.require_absent()
        password._files.require_absent()
        store.create(info)
        password.create(FIRST)
        original = files.path.read_bytes()
        assert (
            str(info.login).encode() not in original
            and info.assigned_server.encode() not in original
        )
        assert store.load() == info
        failure(lambda: store.create(info))
        alias = files.path.parent / ".synthetic-metadata-hardlink.stage"
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

        rotated = info.model_copy(update={"owner_readonly_selection_ref": "synthetic.renewed"})
        with monkeypatch.context() as context:
            context.setattr(files.api.kernel, "SetFileInformationByHandle", deny_rotation)
            failure(lambda: store.rotate(rotated))
        assert store.load() == info and files.path.read_bytes() == original
        store.rotate(rotated)
        assert store.load() == rotated
        # Same Windows user cannot interchange the two fixed entropy purposes.
        with pytest.raises(oi.OISecretUnavailable):
            password._crypto.unprotect(files.path.read_bytes()[len(metadata._MAGIC) :])
        with pytest.raises(oi.OISecretUnavailable):
            store._crypto.unprotect(password._files.path.read_bytes()[len(secret._MAGIC) :])
        assert password.load() == FIRST
        store.delete()
        password.delete()
        failure(store.load)
        output = capsys.readouterr()
        assert str(info.login) not in output.out + output.err
        assert info.assigned_server not in output.out + output.err
        assert FIRST not in output.out + output.err
    finally:
        if files.path.exists():
            store.delete()
        if password._files.path.exists():
            password.delete()
        if files.path.parent.name == "test-" + str(identity) and files.path.parent.exists():
            files.path.parent.rmdir()


def test_private_storage_admission_remeasures_runtime_before_any_native_effect(monkeypatch):
    from auvexo_alpha.infrastructure import ds03_mt5_binding, ds03_secrets

    static, full, now = admitted_fixture()
    calls = []

    def measurement(**kwargs):
        calls.append(kwargs)
        return static.binding

    monkeypatch.setattr(ds03_mt5_binding, "measure_binding", measurement)
    assert metadata._require_authority(static, now) is static
    assert ds03_secrets._require_admission(full, now) is full
    assert len(calls) == 2
    changed = static.binding.model_copy(update={"terminal_binary_hash": "0" * 64})
    monkeypatch.setattr(ds03_mt5_binding, "measure_binding", lambda **kwargs: changed)
    failure(lambda: metadata._require_authority(static, now))
    with pytest.raises(ds03_secrets.Ds03SecretUnavailable, match="^DS03_SECRET_UNAVAILABLE$"):
        ds03_secrets._require_admission(full, now)
