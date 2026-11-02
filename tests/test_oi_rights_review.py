"""Synthetic continuity receipts only. No real review, renewal, START or collection."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from auvexo_alpha.domain.oi_rights_review import (
    OIReviewAuthority,
    OIReviewContinuation,
    require_oi_rights,
)
from auvexo_alpha.domain.oi_schedule import (
    OICollectionConfig,
    OIStartEnvelope,
    require_scheduled_start,
    scheduled_slot,
)
from auvexo_alpha.domain.open_interest import (
    OIManifest,
    OIRights,
    accepted_oi_rights,
    oi_classify_manifest,
    oi_dataset_version,
)
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.oi_parser import parse_oi

BASE = accepted_oi_rights()
DUE = BASE.review_due
AFTER = DUE + timedelta(hours=12)
INITIAL = BASE.reviewed_at + timedelta(hours=1)


def receipt(previous=None, **changes):
    previous_due = BASE.review_due if previous is None else previous.next_review_due
    args = dict(
        base_rights_hash=BASE.content_hash(),
        previous_review_hash=BASE.content_hash() if previous is None else previous.content_hash(),
        source_hash=BASE.source.content_hash(),
        reviewed_at=previous_due - timedelta(days=2),
        accepted_at=previous_due - timedelta(days=1),
        next_review_due=previous_due + timedelta(days=30),
        review_ref="synthetic-review",
        independent_acceptance_ref="synthetic-accepted-review",
    )
    args.update(changes)
    return OIReviewContinuation(**args)


def authority(chain=None, **changes):
    chain = (receipt(),) if chain is None else chain
    args = dict(
        base=BASE,
        chain=chain,
        accepted_digests=tuple(r.content_hash() for r in chain),
        now=max(r.accepted_at for r in chain),
    )
    args.update(changes)
    return OIReviewAuthority(**args)


def manifest(at, stamp=None):
    slot = at.replace(minute=0, second=0, microsecond=0)
    raw = json.dumps(
        {
            "openInterest": "100.0001",
            "symbol": "BTCUSDT",
            "time": (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
        },
        separators=(",", ":"),
    ).encode("ascii")
    observation = parse_oi(
        raw,
        symbol="BTCUSDT",
        slot_at=slot,
        request_sent_at=at,
        first_seen_at=at,
        received_at=at,
        processed_at=at,
        code_revision="synthetic",
        code_hash="a" * 64,
        review_receipt_hash=stamp,
    )
    return OIManifest(
        dataset_version=oi_dataset_version(observation),
        logical_key=f"ds04-a1:BTCUSDT:{observation.provider_time_ms}:oi-snapshot.v1",
        observation=observation,
        rights=BASE,
        raw_relative_path=f"oi/raw/{observation.raw_hash}.raw",
        normalized_relative_path=f"oi/normalized/{observation.content_hash()}.json",
        raw_bytes=len(raw),
        normalized_bytes=len(observation.canonical_bytes()),
        normalized_hash=observation.content_hash(),
        created_at=at,
        processed_at=at,
        classification=DataUseClass.PERSONAL_RESEARCH,
    )


def configuration():
    return OICollectionConfig(
        enabled=True,
        git_revision="a" * 40,
        code_hash="b" * 64,
        lock_hash="c" * 64,
        preregistration_hash="d" * 64,
        study_id="synthetic-fixed-study",
        clock_source="synthetic-clock",
    )


def test_initial_snapshot_hash_due_and_scope_are_never_extended():
    before = BASE.canonical_bytes()
    review = authority()
    require_oi_rights(BASE, INITIAL)
    require_oi_rights(BASE, DUE - timedelta(microseconds=1), review)
    require_oi_rights(BASE, DUE, review)
    assert review.receipt_hash_at(INITIAL) is None
    assert review.receipt_hash_at(DUE) == review.chain[0].content_hash()
    assert BASE.canonical_bytes() == before
    assert BASE.review_due == datetime(2026, 11, 27, tzinfo=UTC)
    assert BASE.version == "ds04-a1-rights.20261027.v1"
    with pytest.raises(ValueError, match="RIGHTS"):
        BASE.require_research(DUE)
    with pytest.raises(ValueError, match="RIGHTS"):
        require_oi_rights(BASE, DUE)
    with pytest.raises(ValueError, match="RIGHTS"):
        review.require(review.chain[-1].next_review_due)


def test_hash_chain_multiple_periods_preserve_base_and_initial_receipt_identity():
    one = receipt()
    two = receipt(one)
    three = receipt(two)
    review = authority((one, two, three))
    assert review.receipt_hash_at(DUE + timedelta(days=1)) == one.content_hash()
    assert review.receipt_hash_at(one.next_review_due) == two.content_hash()
    assert review.receipt_hash_at(two.next_review_due) == three.content_hash()
    assert review.receipt_hash_at(INITIAL) is None
    assert review.base.content_hash() == BASE.content_hash()
    assert review.chain_hash() == authority((one, two, three)).chain_hash()
    assert review.chain_hash() != authority((one, two)).chain_hash()
    assert len(review.chain_hash()) == 64


@pytest.mark.parametrize("digests", [(), ("0" * 64,), ("0" * 64, "1" * 64)])
def test_external_accepted_digest_required_no_self_acceptance_default(digests):
    with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
        authority(accepted_digests=digests)


def test_extra_duplicate_or_reordered_external_acceptance_is_not_a_grant():
    one, two = receipt(), receipt(receipt())
    with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
        authority((one, two), accepted_digests=(two.content_hash(), one.content_hash()))
    with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
        authority((one,), accepted_digests=(one.content_hash(), "0" * 64))
    with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
        authority((one, one))
    with pytest.raises(ValueError, match="CHAIN_REQUIRED"):
        OIReviewAuthority(BASE, (), (), INITIAL)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("terms_hash", "0" * 64),
        ("procedures_hash", "0" * 64),
        ("rules_hash", "0" * 64),
        ("evidence_urls", ("https://unreviewed.invalid",)),
        ("symbols", ("ETHUSDT", "BTCUSDT")),
        ("permitted_use", "PROMOTION_ELIGIBLE"),
        ("redistribution", "AUTHORIZED"),
        ("live_promotion", "AUTHORIZED"),
        ("same_scope", False),
        ("same_evidence", False),
        ("kind", "BROAD_DS04_RENEWAL"),
    ],
)
def test_changed_evidence_or_expanded_scope_rejected(field, bad):
    with pytest.raises(ValueError):
        receipt(**{field: bad})


@pytest.mark.parametrize(
    "field,bad",
    [
        ("base_rights_hash", "0" * 64),
        ("source_hash", "0" * 64),
        ("previous_review_hash", "0" * 64),
    ],
)
def test_wrong_base_source_or_predecessor_rejected(field, bad):
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        authority((receipt(**{field: bad}),))


def test_review_chronology_future_acceptance_and_nonadvancing_due_rejected():
    with pytest.raises(ValueError, match="CHRONOLOGY"):
        receipt(reviewed_at=DUE)
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        authority(now=DUE - timedelta(days=2))
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        authority((receipt(next_review_due=DUE - timedelta(hours=1)),))
    one = receipt()
    invalid = receipt(one, reviewed_at=BASE.reviewed_at, accepted_at=DUE - timedelta(days=2))
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        authority((one, invalid))


def test_late_review_preserves_gap_and_cannot_backdate_observation_admission():
    late = receipt(reviewed_at=DUE + timedelta(hours=1), accepted_at=DUE + timedelta(days=1))
    review = authority((late,))
    for at in (DUE, DUE + timedelta(hours=23), late.accepted_at - timedelta(microseconds=1)):
        with pytest.raises(ValueError, match="GAP_BLOCKED"):
            review.require(at)
    review.require(late.accepted_at)
    assert review.receipt_hash_at(INITIAL) is None
    assert (
        oi_classify_manifest(
            manifest(DUE + timedelta(hours=1), late.content_hash()),
            late.accepted_at,
            review_authority=review,
        )
        == DataUseClass.BLOCKED
    )


def test_revoked_unknown_or_mutated_base_blocks_even_with_chain():
    review = authority()
    with pytest.raises(ValueError, match="REVOKED"):
        require_oi_rights(OIRights(revoked=True), AFTER, review)
    with pytest.raises(ValueError, match="REVOKED"):
        authority(base=OIRights(revoked=True))
    with pytest.raises(ValueError):
        authority(base=BASE.model_copy(update={"review_due": BASE.review_due + timedelta(days=1)}))
    with pytest.raises(ValueError):
        require_oi_rights(BASE.model_copy(update={"version": "unknown"}), AFTER, review)


def test_observation_stamp_is_causal_exact_and_bound_into_manifest():
    review = authority()
    stamp = review.receipt_hash_at(AFTER)
    current = manifest(AFTER, stamp)
    assert current.observation.review_receipt_hash == stamp
    assert (
        oi_classify_manifest(current, AFTER, review_authority=review)
        == DataUseClass.PERSONAL_RESEARCH
    )
    assert (
        oi_classify_manifest(current, AFTER, "PROMOTION", review_authority=review)
        == DataUseClass.BLOCKED
    )
    assert oi_classify_manifest(current, AFTER) == DataUseClass.BLOCKED
    for wrong in (None, "0" * 64):
        changed = manifest(AFTER, wrong)
        assert changed.content_hash() != current.content_hash()
        assert oi_classify_manifest(changed, AFTER, review_authority=review) == DataUseClass.BLOCKED
    initial = manifest(INITIAL)
    assert (
        oi_classify_manifest(initial, AFTER, review_authority=review)
        == DataUseClass.PERSONAL_RESEARCH
    )
    assert (
        oi_classify_manifest(manifest(INITIAL, stamp), AFTER, review_authority=review)
        == DataUseClass.BLOCKED
    )
    assert (
        current.raw_hash
        == hashlib.sha256(
            json.dumps(
                {
                    "openInterest": "100.0001",
                    "symbol": "BTCUSDT",
                    "time": (AFTER - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
                },
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
    )


def test_schedule_cheap_slot_gate_separate_from_current_review_authority():
    config = configuration()
    assert scheduled_slot(config, AFTER) == AFTER
    with pytest.raises(ValueError, match="RIGHTS"):
        require_scheduled_start(config, AFTER)
    assert require_scheduled_start(config, AFTER, authority()) == AFTER
    with pytest.raises(ValueError, match="PROTECTED_WINDOW"):
        scheduled_slot(config, AFTER.replace(hour=16))


def test_conditional_start_expiry_cannot_exceed_fixed_90day_evaluation_end():
    config = configuration()
    start = datetime(2026, 10, 27, 12, tzinfo=UTC)
    fixed_end = start.replace(hour=0) + timedelta(days=93)
    envelope = OIStartEnvelope(
        owner_authorization_ref="synthetic-owner",
        independent_review_ref="synthetic-review",
        implementation_revision=config.git_revision,
        config_hash=config.content_hash(),
        code_hash=config.code_hash,
        source_hash=config.source.content_hash(),
        rights_hash=config.rights.content_hash(),
        preregistration_hash=config.preregistration_hash,
        issued_at=start,
        owner_start_at=start,
        expires_at=fixed_end,
    )
    envelope.require_start(config, envelope.content_hash(), start)
    with pytest.raises(ValueError, match="RIGHTS"):
        envelope.require_start(config, envelope.content_hash(), AFTER)
    envelope.require_start(config, envelope.content_hash(), AFTER, authority())
    later = OIStartEnvelope.model_validate(
        {
            **envelope.model_dump(mode="python"),
            "expires_at": fixed_end + timedelta(microseconds=1),
        }
    )
    with pytest.raises(ValueError, match="START_AUTHORITY_INVALID"):
        later.require_start(config, later.content_hash(), start)


def review_loader():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools/run_oi_collection.py"
    spec = importlib.util.spec_from_file_location("synthetic_oi_review_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_review_authority


def test_cli_review_loader_positive_exact_chain_and_no_receipt_default(tmp_path):
    load = review_loader()
    config = configuration()
    assert load(config, None, [], INITIAL) is None
    first = receipt()
    second = receipt(first)
    path = tmp_path / "synthetic-reviews.json"
    path.write_text(
        json.dumps(
            [
                first.model_dump(mode="json"),
                second.model_dump(mode="json"),
            ]
        ),
        encoding="utf8",
    )
    context = load(config, path, [first.content_hash(), second.content_hash()], second.accepted_at)
    assert context.base.content_hash() == BASE.content_hash()
    assert context.receipt_hash_at(AFTER) == first.content_hash()
    assert context.chain_hash() == authority((first, second)).chain_hash()


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"[",
        b"{}",
        b"null",
        b"[]",
        b"[1]",
        b"[null]",
        b"[true]",
        b'[{"review_ref":"one","review_ref":"two"}]',
        b'[{"review_ref":"one","extra":{"same_scope":true,"same_scope":true}}]',
    ],
)
def test_cli_review_loader_malformed_or_duplicate_keys_fail_closed(raw, tmp_path):
    path = tmp_path / "synthetic-invalid-reviews.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        review_loader()(configuration(), path, [receipt().content_hash()], AFTER)


def test_cli_review_loader_requires_external_acceptance_and_rejects_extras(tmp_path):
    load = review_loader()
    original = receipt()
    path = tmp_path / "synthetic-reviews.json"
    path.write_text(json.dumps([original.model_dump(mode="json")]), encoding="utf8")
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        load(configuration(), path, [], AFTER)
    with pytest.raises(ValueError, match="ACCEPTANCE_WITHOUT_CHAIN"):
        load(configuration(), None, [original.content_hash()], AFTER)
    for accepted in (
        ["0" * 64],
        [original.content_hash(), "0" * 64],
        [original.content_hash(), original.content_hash()],
    ):
        with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
            load(configuration(), path, accepted, AFTER)


def test_cli_review_loader_changed_unaccepted_receipt_cannot_reuse_old_digest(tmp_path):
    original = receipt()
    changed = receipt(review_ref="synthetic-changed-review")
    path = tmp_path / "synthetic-changed-reviews.json"
    path.write_text(json.dumps([changed.model_dump(mode="json")]), encoding="utf8")
    with pytest.raises(ValueError, match="EXTERNAL_ACCEPTANCE_REQUIRED"):
        review_loader()(configuration(), path, [original.content_hash()], AFTER)
    expanded = original.model_dump(mode="json")
    expanded["terms_hash"] = "0" * 64
    path.write_text(json.dumps([expanded]), encoding="utf8")
    with pytest.raises(ValueError):
        review_loader()(configuration(), path, [original.content_hash()], AFTER)


def test_cli_review_loader_size_count_and_future_acceptance_budgets(tmp_path):
    path = tmp_path / "synthetic-budget-reviews.json"
    original = receipt()
    path.write_bytes(b" " * 262145)
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        review_loader()(configuration(), path, [original.content_hash()], AFTER)
    path.write_text(json.dumps([original.model_dump(mode="json")] * 33), encoding="utf8")
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        review_loader()(configuration(), path, [original.content_hash()] * 33, AFTER)
    path.write_text(json.dumps([original.model_dump(mode="json")]), encoding="utf8")
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        review_loader()(
            configuration(),
            path,
            [original.content_hash()],
            original.accepted_at - timedelta(microseconds=1),
        )


def test_review_loader_excessive_json_depth_is_stable_refusal(tmp_path):
    from test_oi_collection import NOW, configuration, tool

    path = tmp_path / "deep-review.json"
    path.write_text("[" * 2000 + "]" * 2000)
    with pytest.raises(ValueError, match="OI_REVIEW_CHAIN_DEPTH"):
        tool("run_oi_collection").load_review_authority(configuration(), path, ["a" * 64], NOW)
