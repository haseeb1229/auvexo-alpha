"""M5-05/06: synthetic accepted-digest fixtures only; no authority issuer or native access."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from auvexo_alpha.domain.ds03_authority import (
    Ds03AuthorityError,
    Ds03LocalMetadata,
    Ds03OnboardingAuthority,
    Ds03RuntimeBinding,
    admit_authority,
    admit_onboarding,
    decode_authority,
    decode_metadata,
)


def authority_fixture():
    now = datetime(2026, 11, 3, 12, tzinfo=UTC)
    metadata = Ds03LocalMetadata(
        login=123456789,
        assigned_server="synthetic-server.invalid",
        account_type="SyntheticStandard",
        currency="USD",
        leverage=100,
        owner_readonly_selection_ref="synthetic.owner.readonly",
        terminal_path_hash="1" * 64,
        profile_path_hash="2" * 64,
    )
    binding = Ds03RuntimeBinding(
        release_sha="1" * 40,
        release_tree="2" * 40,
        connector_source_hash="3" * 64,
        interpreter_hash="4" * 64,
        package_manifest_hash="5" * 64,
        terminal_binary_hash="6" * 64,
        terminal_build=4755,
        terminal_version="synthetic.mt5.v500",
        fixed_runtime_path_hash="7" * 64,
        fixed_terminal_path_hash=metadata.terminal_path_hash,
        fixed_profile_path_hash=metadata.profile_path_hash,
        profile_identity_hash="8" * 64,
    )
    authority = Ds03OnboardingAuthority(
        authority_id=uuid4(),
        runtime=binding,
        metadata_hash=metadata.content_hash(),
        account_digest=metadata.login_digest,
        server_digest=metadata.server_digest,
        account_type=metadata.account_type,
        currency=metadata.currency,
        leverage=metadata.leverage,
        rights_hash="9" * 64,
        rights_valid_until=now + timedelta(hours=2),
        owner_readonly_selection_ref=metadata.owner_readonly_selection_ref,
        private_attested_at=now - timedelta(minutes=1),
        authorized_at=now - timedelta(seconds=30),
        expires_at=now + timedelta(hours=1),
        owner_authorization_ref="synthetic.owner.authorization",
    )
    return authority, metadata, binding, now


def admitted_fixture():
    authority, metadata, binding, now = authority_fixture()
    # Synthetic trust input only: production code never issues or accepts its own digest.
    accepted = authority.content_hash()
    static = admit_authority(
        authority, independently_accepted_digest=accepted, binding=binding, now=now
    )
    return static, static.bind_metadata(metadata, now=now), now


def failure(call):
    with pytest.raises(Ds03AuthorityError) as captured:
        call()
    assert str(captured.value) == "DS03_AUTHORITY_UNAVAILABLE"
    assert captured.value.__suppress_context__


def test_static_then_metadata_then_onboarding_has_no_observed_readonly_claim():
    authority, metadata, binding, now = authority_fixture()
    static = admit_authority(
        authority, independently_accepted_digest=authority.content_hash(), binding=binding, now=now
    )
    static.verify(now)
    full = static.bind_metadata(metadata, now=now)
    full.verify(now)
    assert full.metadata == metadata
    assert metadata.account_ref == "ds03.account." + metadata.login_digest
    assert metadata.server_ref == "ds03.server." + metadata.server_digest
    assert not hasattr(static, "metadata")
    assert not hasattr(full, "account_trade_allowed")
    assert not hasattr(full, "terminal_trade_allowed")
    assert decode_authority(authority.canonical_bytes()) == authority
    assert decode_metadata(metadata.canonical_bytes()) == metadata
    assert (
        admit_onboarding(
            authority,
            independently_accepted_digest=authority.content_hash(),
            metadata=metadata,
            binding=binding,
            now=now,
        )
        == full
    )
    with pytest.raises((AttributeError, TypeError)):
        full.accepted_digest = "0" * 64


@pytest.mark.parametrize("digest", ["", "0" * 64, "not-a-digest", "x" * 64, None, True])
def test_unaccepted_digest_refuses(digest):
    authority, metadata, binding, now = authority_fixture()
    failure(
        lambda: admit_authority(
            authority, independently_accepted_digest=digest, binding=binding, now=now
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_sha", "a" * 40),
        ("release_tree", "b" * 40),
        ("connector_source_hash", "a" * 64),
        ("interpreter_hash", "b" * 64),
        ("package_manifest_hash", "c" * 64),
        ("terminal_binary_hash", "d" * 64),
        ("terminal_build", 4756),
        ("terminal_version", "synthetic.changed"),
        ("fixed_runtime_path_hash", "a" * 64),
        ("fixed_terminal_path_hash", "b" * 64),
        ("fixed_profile_path_hash", "c" * 64),
        ("profile_identity_hash", "d" * 64),
    ],
)
def test_every_measured_runtime_binding_mismatch_refuses(field, value):
    authority, metadata, binding, now = authority_fixture()
    changed = binding.model_copy(update={field: value})
    failure(
        lambda: admit_authority(
            authority,
            independently_accepted_digest=authority.content_hash(),
            binding=changed,
            now=now,
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("login", 987654321),
        ("assigned_server", "synthetic-other.invalid"),
        ("account_type", "SyntheticOther"),
        ("currency", "EUR"),
        ("leverage", 200),
        ("owner_readonly_selection_ref", "synthetic.changed"),
        ("terminal_path_hash", "a" * 64),
        ("profile_path_hash", "b" * 64),
    ],
)
def test_metadata_account_server_provenance_and_profile_mismatch_refuse(field, value):
    authority, metadata, binding, now = authority_fixture()
    static = admit_authority(
        authority, independently_accepted_digest=authority.content_hash(), binding=binding, now=now
    )
    changed = metadata.model_copy(update={field: value})
    failure(lambda: static.bind_metadata(changed, now=now))


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository_visibility", "PUBLIC"),
        ("mode", "REAL"),
        ("credential_kind", "TRADING_PASSWORD"),
        ("credential_purpose", "wrong-purpose"),
        ("credential_version", True),
        ("scope", "GENERIC_ENABLE"),
    ],
)
def test_forged_constructed_models_do_not_bypass_closed_contract(field, value):
    authority, metadata, binding, now = authority_fixture()
    changed = authority.model_copy(update={field: value})
    failure(
        lambda: admit_authority(
            changed, independently_accepted_digest=changed.content_hash(), binding=binding, now=now
        )
    )


def test_expiry_future_private_staleness_and_invalid_runtime_literals_refuse():
    static, full, now = admitted_fixture()
    failure(lambda: static.verify(now - timedelta(minutes=2)))
    failure(lambda: full.verify(now + timedelta(hours=1)))
    failure(lambda: full.verify(now.replace(tzinfo=None)))
    for change in (
        {"expires_at": now + timedelta(hours=25)},
        {"private_attested_at": now - timedelta(hours=25)},
        {"rights_valid_until": now},
    ):
        bad = static.authority.model_copy(update=change)
        failure(
            lambda value=bad: replace(
                static, authority=value, accepted_digest=value.content_hash()
            ).verify(now)
        )
    for change in ({"package_version": "0"}, {"wheel_hash": "0" * 64}, {"terminal_build": True}):
        bad_binding = static.binding.model_copy(update=change)
        bad_authority = static.authority.model_copy(update={"runtime": bad_binding})
        failure(
            lambda authority=bad_authority, binding=bad_binding: replace(
                static,
                authority=authority,
                accepted_digest=authority.content_hash(),
                binding=binding,
            ).verify(now)
        )
    late = static.authority.model_copy(
        update={"private_attested_at": now - timedelta(hours=24) + timedelta(seconds=10)}
    )
    failure(
        lambda: replace(static, authority=late, accepted_digest=late.content_hash()).verify(
            now + timedelta(seconds=20)
        )
    )


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b'{"x":NaN}', b'{"x":1,"x":2}', b"x" * 16385])
def test_malformed_duplicate_unknown_and_nonfinite_decode_refuses(raw):
    failure(lambda: decode_authority(raw))
    failure(lambda: decode_metadata(raw))


def test_metadata_repr_and_parse_errors_never_disclose_raw_identity():
    authority, metadata, binding, now = authority_fixture()
    for shown in (
        repr(metadata),
        str(metadata),
        repr(
            admit_onboarding(
                authority,
                independently_accepted_digest=authority.content_hash(),
                metadata=metadata,
                binding=binding,
                now=now,
            )
        ),
    ):
        assert str(metadata.login) not in shown
        assert metadata.assigned_server not in shown
    raw = metadata.model_dump() | {"login": "synthetic-private-value"}
    import json

    failure(lambda: decode_metadata(json.dumps(raw).encode()))


@pytest.mark.parametrize(
    "sentinel", ["UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "UNSPECIFIED", "NA"]
)
def test_unknown_currency_or_terminal_version_cannot_admit_even_constructed_models(sentinel):
    authority, metadata, binding, now = authority_fixture()
    invalid_metadata = metadata.model_copy(update={"currency": sentinel})
    failure(lambda: decode_metadata(invalid_metadata.canonical_bytes()))
    invalid_binding = binding.model_copy(update={"terminal_version": sentinel})
    invalid_authority = authority.model_copy(update={"runtime": invalid_binding})
    failure(
        lambda: admit_authority(
            invalid_authority,
            independently_accepted_digest=invalid_authority.content_hash(),
            binding=invalid_binding,
            now=now,
        )
    )
