"""R12-6: keyed HMAC account/server/ticket references and their fixed DPAPI key slot.

Synthetic keys and disposable UUID leaves only; production key APIs are never invoked.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from mt5_fixtures import fixture, nt, prepared, request
from pydantic import TypeAdapter
from test_ds03_authority import REFERENCE_KEY, admitted_fixture, synthetic_metadata
from test_ds03_secrets import MemoryFiles, SyntheticCrypto

from auvexo_alpha.domain import ds03_authority
from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.domain.ds03_actual import AccountRef, ServerRef
from auvexo_alpha.infrastructure import ds03_metadata as metadata
from auvexo_alpha.infrastructure import ds03_secrets as secret
from auvexo_alpha.infrastructure import oi_secrets as oi
from auvexo_alpha.infrastructure.ds03_mt5 import _Mt5ReadPort

OTHER_KEY = bytes(range(1, 33))


def key_failure(call):
    with pytest.raises(metadata.Ds03ReferenceKeyUnavailable) as captured:
        call()
    assert str(captured.value) == "DS03_REFERENCE_KEY_UNAVAILABLE"
    assert captured.value.reason == "REFERENCE_KEY_UNAVAILABLE"
    assert captured.value.__suppress_context__


def test_references_are_keyed_opaque_and_keep_the_fixed_shape():
    info = synthetic_metadata()
    account, server = metadata.metadata_references(
        REFERENCE_KEY, login=info.login, assigned_server=info.assigned_server
    )
    assert (account, server) == (info.account_digest, info.server_digest)
    TypeAdapter(AccountRef).validate_python(info.account_ref)
    TypeAdapter(ServerRef).validate_python(info.server_ref)
    # The reviewed defect: unsalted SHA-256 of the low-entropy values.
    assert account != hashlib.sha256(str(info.login).encode()).hexdigest()
    assert server != hashlib.sha256(info.assigned_server.encode()).hexdigest()
    other = metadata.metadata_references(
        OTHER_KEY, login=info.login, assigned_server=info.assigned_server
    )
    assert other[0] != account and other[1] != server
    # Kinds are domain separated: the same value never yields the same reference.
    assert metadata.keyed_reference(REFERENCE_KEY, "account", "7") != metadata.keyed_reference(
        REFERENCE_KEY, "server", "7"
    )


def test_enumerating_the_low_entropy_space_without_the_key_finds_nothing():
    info = synthetic_metadata(login=1234)
    unsalted = {hashlib.sha256(str(login).encode()).hexdigest() for login in range(10000)}
    assert hashlib.sha256(b"1234").hexdigest() in unsalted
    assert info.account_digest not in unsalted
    guessed_key = {
        metadata.keyed_reference(OTHER_KEY, "account", str(login)) for login in range(10000)
    }
    assert info.account_digest not in guessed_key


@pytest.mark.parametrize(
    "key,kind,value",
    [
        (b"short", "account", "1"),
        (bytearray(REFERENCE_KEY), "account", "1"),
        ("0" * 64, "account", "1"),
        (REFERENCE_KEY, "login", "1"),
        (REFERENCE_KEY, "account", ""),
        (REFERENCE_KEY, "account", "x" * 513),
        (REFERENCE_KEY, "account", "café"),
        (REFERENCE_KEY, "account", "line\nbreak"),
        (REFERENCE_KEY, "account", 1),
    ],
)
def test_reference_inputs_are_bounded(key, kind, value):
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REFERENCE_MISMATCH$"):
        metadata.keyed_reference(key, kind, value)


@pytest.mark.parametrize("login", [0, -1, True, "123"])
def test_metadata_reference_login_must_be_a_positive_integer(login):
    with pytest.raises(Ds03Error, match="REFERENCE_MISMATCH"):
        metadata.metadata_references(REFERENCE_KEY, login=login, assigned_server="s.invalid")


@pytest.mark.parametrize("field", ["account_digest", "server_digest"])
def test_stored_digests_are_recomputed_never_trusted(field):
    info = synthetic_metadata()
    metadata.require_metadata_references(info, REFERENCE_KEY)
    with pytest.raises(Ds03Error, match="REFERENCE_MISMATCH"):
        metadata.require_metadata_references(info, OTHER_KEY)
    tampered = info.model_copy(update={field: "0" * 64})
    with pytest.raises(Ds03Error, match="REFERENCE_MISMATCH"):
        metadata.require_metadata_references(tampered, REFERENCE_KEY)
    with pytest.raises(Ds03Error, match="REFERENCE_MISMATCH"):
        metadata.require_metadata_references(object(), REFERENCE_KEY)


def test_port_refuses_a_wrong_key_before_any_provider_call_and_keys_ticket_refs():
    f = fixture(initialize=False)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REFERENCE_MISMATCH$"):
        _Mt5ReadPort(f.sdk, f.admission, f.observer, OTHER_KEY)
    assert f.sdk.calls == []
    f = prepared(fixture())
    at = f.sdk.msc
    f.sdk.orders = (
        nt(
            {
                "ticket": 8,
                "symbol": f.sdk.symbols[0],
                "type": 0,
                "state": 1,
                "volume_initial": 1.0,
                "volume_current": 1.0,
                "price_open": 100.0,
                "time_setup": at // 1000,
                "time_setup_msc": at,
                "time_done": 0,
                "time_done_msc": 0,
            }
        ),
    )
    order = f.port.execute(request(f, "ORDERS")).payload.orders[0]
    digest = order.order_ref.removeprefix("ds03.order.")
    old = f.admission.metadata.account_ref + ":order:8"
    assert digest != hashlib.sha256(old.encode()).hexdigest()
    assert digest == metadata.keyed_reference(
        REFERENCE_KEY, "order", f.admission.metadata.account_digest + ":8"
    )
    assert order.setup_time_msc_raw == at and order.done_time_msc_raw == 0
    f.port.disconnect()


def test_domain_holds_no_key_and_hashes_no_low_entropy_value():
    tree = ast.parse(Path(inspect.getsourcefile(ds03_authority)).read_text(encoding="utf8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "hashlib" not in imported and "secrets" not in imported
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in ("new", "sha256", "token_bytes")
        for node in ast.walk(tree)
    )
    for name in ("login_digest", "server_digest_of"):
        assert not hasattr(ds03_authority.Ds03LocalMetadata, name)


def key_store():
    files = MemoryFiles()
    return metadata._ReferenceKeyStore(files, SyntheticCrypto()), files


def test_key_store_generates_fixed_size_key_once_and_has_no_rotation():
    store, files = key_store()
    key_failure(store.load)
    store.create()
    key = store.load()
    assert type(key) is bytes and len(key) == 32 and key == store.load()
    blob = files.blob
    key_failure(store.create)
    assert files.blob == blob
    other, _ = key_store()
    other.create()
    assert other.load() != key
    assert not hasattr(store, "rotate") and not hasattr(store, "write")
    store.delete()
    key_failure(store.load)
    key_failure(store.delete)


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "wrong"},
        {"purpose": metadata._PURPOSE.decode()},
        {"purpose": secret._PURPOSE.decode()},
        {"version": True},
        {"version": 2},
        {"extra": 1},
        {"key": "0" * 62},
        {"key": "A" * 64},
        {"key": 1},
    ],
)
def test_key_envelope_wrong_purpose_version_extra_and_shape_refuse(change):
    store, files = key_store()
    payload = {"purpose": metadata._KEY_PURPOSE.decode(), "version": 1, "key": "0" * 64}
    files.blob = metadata._KEY_MAGIC + SyntheticCrypto().protect(
        json.dumps(payload | change).encode()
    )
    key_failure(store.load)


@pytest.mark.parametrize(
    "blob", [b"", b"bad", b"x" * 8193, metadata._KEY_MAGIC, metadata._MAGIC + b"bad"]
)
def test_missing_corrupt_or_foreign_magic_key_blob_refuses(blob):
    store, files = key_store()
    files.blob = blob
    key_failure(store.load)


def test_fixed_key_slot_is_distinct_and_test_leaves_require_a_uuid(monkeypatch):
    base = Path(Path.cwd().anchor) / "synthetic-os-localappdata"

    class NativeAPISeam:
        def known_local_appdata(self):
            return base

        def current_sid(self):
            return "synthetic-owner"

    monkeypatch.setattr(secret, "_WindowsAPI", NativeAPISeam)
    identity = uuid4()
    store = metadata.make_test_ds03_reference_key_store(identity)
    assert store._files.path == (
        base / "AuvexoAlpha/phase2/ds03" / ("test-" + str(identity)) / metadata._KEY_FILENAME
    )
    purposes = {metadata._KEY_PURPOSE, metadata._PURPOSE, secret._PURPOSE}
    assert len(purposes) == 3 and store._crypto._purpose() == metadata._KEY_PURPOSE
    assert metadata._ReferenceKeyWindowsFiles().path == (
        base / "AuvexoAlpha/phase2/ds03" / metadata._KEY_FILENAME
    )
    assert metadata._ReferenceKeyWindowsFiles._write is oi._WindowsFiles._write
    for invalid in (None, "arbitrary/path", b"purpose", Path.cwd(), str(identity)):
        key_failure(lambda value=invalid: metadata.make_test_ds03_reference_key_store(value))


def test_every_production_key_effect_is_gated_and_never_invoked_here(monkeypatch):
    gates = {
        "require_ds03_reference_key_absent": "_require_measured",
        "create_ds03_reference_key": "_require_measured",
        "ds03_reference_digests": "_require_measured",
        "load_ds03_reference_key": "_require_authority",
        "delete_ds03_reference_key": "_require_authority",
    }
    for name, gate in gates.items():
        tree = ast.parse(inspect.getsource(vars(metadata)[name]))
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert calls.index(gate) == 0, name
    source = inspect.getsource(metadata.load_ds03_account_metadata)
    assert source.index("require_metadata") < source.index("require_metadata_references(")
    from auvexo_alpha.infrastructure import ds03_mt5_binding

    static, full, now = admitted_fixture()
    measured = []
    monkeypatch.setattr(
        ds03_mt5_binding, "measure_binding", lambda **kw: measured.append(kw) or static.binding
    )
    assert metadata._require_measured(static.binding) == static.binding
    assert len(measured) == 1
    for invalid in (None, static, full, static.binding.model_dump()):
        key_failure(lambda value=invalid: metadata._require_measured(value))
    changed = static.binding.model_copy(update={"terminal_binary_hash": "0" * 64})
    monkeypatch.setattr(ds03_mt5_binding, "measure_binding", lambda **kw: changed)
    key_failure(lambda: metadata._require_measured(static.binding))


def test_metadata_rotation_cannot_switch_account_server_or_reference():
    store = metadata._MetadataStore(MemoryFiles(), SyntheticCrypto())
    info = synthetic_metadata()
    store.create(info)
    for changed in (
        synthetic_metadata(login=987654321),
        synthetic_metadata(assigned_server="synthetic-other.invalid"),
        info.model_copy(update={"account_digest": "0" * 64}),
    ):
        with pytest.raises(metadata.Ds03MetadataUnavailable):
            store.rotate(changed)
    assert store.load() == info


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI/ACL proof requires native Windows")
def test_native_disposable_reference_key_slot_and_cross_purpose_isolation(capsys):
    identity = uuid4()
    store = metadata.make_test_ds03_reference_key_store(identity)
    info_store = metadata.make_test_ds03_metadata_store(identity)
    files = store._files
    try:
        files.require_absent()
        store.create()
        key = store.load()
        raw = files.path.read_bytes()
        assert key.hex().encode() not in raw and key not in raw
        key_failure(store.create)
        info_store.create(synthetic_metadata())
        with pytest.raises(oi.OISecretUnavailable):
            info_store._crypto.unprotect(raw[len(metadata._KEY_MAGIC) :])
        with pytest.raises(oi.OISecretUnavailable):
            store._crypto.unprotect(info_store._files.path.read_bytes()[len(metadata._MAGIC) :])
        alias = files.path.parent / ".synthetic-key-hardlink.stage"
        os.link(files.path, alias)
        try:
            key_failure(store.load)
        finally:
            alias.unlink()
        assert store.load() == key
        store.delete()
        info_store.delete()
        key_failure(store.load)
        output = capsys.readouterr()
        assert key.hex() not in output.out + output.err
    finally:
        for candidate in (store, info_store):
            if candidate._files.path.exists():
                candidate.delete()
        if files.path.parent.name == "test-" + str(identity) and files.path.parent.exists():
            files.path.parent.rmdir()
