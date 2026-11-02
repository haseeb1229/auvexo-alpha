"""Synthetic DS-04-A1 source/parser/admission proofs; no provider data or OOS access."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from auvexo_alpha.domain.market_data import Candle, SourceIdentity
from auvexo_alpha.domain.open_interest import (
    OI_REVIEW_DUE,
    OIManifest,
    OIRights,
    OISourceIdentity,
    accepted_oi_rights,
    oi_classify_manifest,
    oi_dataset_version,
)
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.oi_parser import parse_oi

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def raw(value="100.123456789012345678", symbol="BTCUSDT", provider=NOW):
    return json.dumps(
        {
            "openInterest": value,
            "symbol": symbol,
            "time": (provider - EPOCH) // timedelta(milliseconds=1),
        },
        separators=(",", ":"),
    ).encode()


def observation(body=None, **overrides):
    args = dict(
        symbol="BTCUSDT",
        slot_at=NOW,
        request_sent_at=NOW,
        first_seen_at=NOW + timedelta(seconds=1),
        received_at=NOW + timedelta(seconds=2),
        processed_at=NOW + timedelta(seconds=3),
        code_revision="synthetic",
        code_hash="a" * 64,
    )
    args.update(overrides)
    return parse_oi(raw() if body is None else body, **args)


def manifest(obs=None, classification=DataUseClass.PERSONAL_RESEARCH):
    obs = observation() if obs is None else obs
    return OIManifest(
        dataset_version=oi_dataset_version(obs),
        logical_key=f"ds04-a1:{obs.symbol}:{obs.provider_time_ms}:{obs.parser_version}",
        observation=obs,
        rights=accepted_oi_rights(),
        raw_relative_path=f"oi/raw/{obs.raw_hash}.raw",
        normalized_relative_path=f"oi/normalized/{obs.content_hash()}.json",
        raw_bytes=len(raw()),
        normalized_bytes=len(obs.canonical_bytes()),
        normalized_hash=obs.content_hash(),
        created_at=obs.available_at,
        processed_at=obs.available_at,
        classification=classification,
    )


def test_exact_decimal_raw_hash_and_causal_chronology():
    body = raw()
    obs = observation(body)
    assert obs.raw_open_interest == "100.123456789012345678"
    assert obs.value == Decimal("100.123456789012345678")
    assert obs.raw_hash == hashlib.sha256(body).hexdigest()
    assert obs.normalized_hash == obs.content_hash()
    assert obs.provider_at == NOW
    assert obs.first_seen_at != obs.provider_at
    assert (
        obs.request_sent_at
        <= obs.first_seen_at
        <= obs.received_at
        <= obs.processed_at
        == obs.available_at
    )
    assert obs.unit == "PROVIDER_NATIVE_OI_UNSPECIFIED"
    with pytest.raises(ValidationError):
        obs.value = Decimal("2")


@pytest.mark.parametrize(
    "bad",
    [
        b"{}",
        b"[]",
        b"null",
        b"not-json",
        b"\xff",
        b"x" * 4097,
        b'{"openInterest":"1","openInterest":"2","symbol":"BTCUSDT","time":1793102400000}',
        b'{"openInterest":"1","symbol":"BTCUSDT","time":1793102400000,"x":1}',
        b'{"openInterest":"1","symbol":"BTCUSDT"}',
    ],
)
def test_strict_untrusted_schema(bad):
    with pytest.raises(ValueError):
        observation(bad)


@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        1.1,
        None,
        "-1",
        "-0",
        "NaN",
        "Infinity",
        "1e1000000",
        "+1",
        "01",
        "1.",
        " 1",
        "1" * 1000,
    ],
)
def test_decimal_rejections(value):
    with pytest.raises(ValueError):
        observation(raw(value=value))


@pytest.mark.parametrize(
    "provider_time", [True, None, "1793102400000", -1, 1.2, 1793102400000000, 10**30]
)
def test_integer_millisecond_time_only(provider_time):
    body = json.loads(raw())
    body["time"] = provider_time
    with pytest.raises(ValueError):
        observation(json.dumps(body).encode())


def test_wrong_symbol_future_stale_zero_and_timestamp_boundaries():
    with pytest.raises(ValueError, match="SYMBOL"):
        observation(raw(symbol="ETHUSDT"))
    with pytest.raises(ValueError, match="FUTURE"):
        observation(raw(provider=NOW + timedelta(seconds=3)))
    with pytest.raises(ValueError, match="STALE"):
        observation(raw(provider=NOW - timedelta(seconds=119)))
    assert observation(raw(provider=NOW - timedelta(seconds=118))).value > 0
    assert observation(raw(value="0")).value == 0
    with pytest.raises(ValueError, match="CHRONOLOGY"):
        observation(processed_at=NOW)
    with pytest.raises(ValueError, match="SLOT_BOUNDARY"):
        observation(slot_at=NOW + timedelta(seconds=1))


@given(st.integers(min_value=0, max_value=10**12), st.integers(min_value=0, max_value=999999))
def test_decimal_property_preserves_plain_provider_truth(whole, fraction):
    value = f"{whole}.{fraction:06d}"
    assert observation(raw(value=value)).value == Decimal(value)


def test_exact_rights_hashes_review_boundary_and_revocation():
    rights = accepted_oi_rights()
    assert rights.version == "ds04-a1-rights.20261027.v1"
    assert len(rights.evidence_urls) == 3
    rights.require_research(NOW)
    rights.require_research(OI_REVIEW_DUE - timedelta(microseconds=1))
    for at in (OI_REVIEW_DUE, OI_REVIEW_DUE + timedelta(days=1), NOW - timedelta(days=1)):
        with pytest.raises(ValueError, match="RIGHTS"):
            rights.require_research(at)
    for key, value in (
        ("terms_hash", "0" * 64),
        ("procedures_hash", "0" * 64),
        ("rules_hash", "0" * 64),
        ("version", "unreviewed.v2"),
        ("review_due", OI_REVIEW_DUE + timedelta(days=1)),
        ("evidence_urls", ("https://other.invalid",)),
    ):
        with pytest.raises(ValueError):
            OIRights.model_validate({**rights.model_dump(mode="python"), key: value})
    revoked = OIRights(revoked=True)
    with pytest.raises(ValueError, match="RIGHTS"):
        revoked.require_research(NOW)


def test_admission_personal_engineering_no_promotion_or_cross_product_transfer():
    m = manifest()
    now = NOW + timedelta(seconds=3)
    assert oi_classify_manifest(m, now) == DataUseClass.PERSONAL_RESEARCH
    assert oi_classify_manifest(m, now, "ENGINEERING") == DataUseClass.ENGINEERING_ONLY
    assert oi_classify_manifest(m, now, "PROMOTION") == DataUseClass.BLOCKED
    assert oi_classify_manifest(m, OI_REVIEW_DUE) == DataUseClass.BLOCKED
    assert oi_classify_manifest(m, NOW) == DataUseClass.BLOCKED
    assert (
        oi_classify_manifest(
            manifest(classification=DataUseClass.ENGINEERING_ONLY), OI_REVIEW_DUE, "ENGINEERING"
        )
        == DataUseClass.BLOCKED
    )
    with pytest.raises(ValueError):
        manifest(classification=DataUseClass.PROMOTION_ELIGIBLE)
    with pytest.raises(ValueError):
        OISourceIdentity(product="SPOT")
    with pytest.raises(ValueError):
        OISourceIdentity(endpoint="https://data-api.binance.vision")
    with pytest.raises(ValueError):
        SourceIdentity.model_validate(m.source.model_dump(mode="python"))
    with pytest.raises(ValueError):
        Candle.model_validate(m.observation.model_dump(mode="python"))
    assert (
        oi_classify_manifest(
            m.model_copy(update={"rights": OIRights.model_construct(version="unknown")}), now
        )
        == DataUseClass.BLOCKED
    )


def test_manifest_hash_artifact_and_lineage_binding():
    m = manifest()
    for key, value in (
        ("dataset_version", "0" * 64),
        ("normalized_hash", "0" * 64),
        ("normalized_relative_path", "../escape.json"),
        ("raw_relative_path", "oi/raw/" + "0" * 64 + ".raw"),
        ("logical_key", "spot-transfer"),
        ("normalized_bytes", 1),
        ("created_at", NOW),
        ("conflict_raw_hash", "0" * 64),
    ):
        with pytest.raises(ValueError):
            OIManifest.model_validate({**m.model_dump(mode="python"), key: value})
    data = m.observation.model_dump(mode="python")
    data.update(quality="QUARANTINED", reason="IDENTITY_CONFLICT", prior_raw_hash="b" * 64)
    from auvexo_alpha.domain.open_interest import OIObservation

    q = OIObservation.model_validate(data)
    args = m.model_dump(mode="python")
    args.update(
        observation=q,
        normalized_hash=q.content_hash(),
        normalized_bytes=len(q.canonical_bytes()),
        normalized_relative_path=f"oi/normalized/{q.content_hash()}.json",
        classification=DataUseClass.BLOCKED,
        supersedes="c" * 64,
        conflict_raw_hash="b" * 64,
    )
    assert (
        oi_classify_manifest(OIManifest.model_validate(args), NOW + timedelta(seconds=4))
        == DataUseClass.BLOCKED
    )
