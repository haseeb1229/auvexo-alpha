"""Job-to-ledger proofs through the real store recompute logic; no database or endpoint.

Only the SQL primitives of ``OIStore`` are replaced by in-memory rows. Feature,
forecast and score binding run the production ``append_*`` methods unchanged, so a
job/store disagreement cannot hide behind a fake that never recomputes.
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event

import pytest

from auvexo_alpha.application.oi_research import compute_oi_features
from auvexo_alpha.domain.oi_schedule import OIClockProof, OICollectionConfig, OIStartEnvelope
from auvexo_alpha.domain.open_interest import OIManifest, oi_dataset_version
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.oi_collection import OICollectionJob
from auvexo_alpha.infrastructure.oi_http import OIReceipt
from auvexo_alpha.infrastructure.oi_parser import parse_oi
from auvexo_alpha.infrastructure.oi_store import OILedgerEntry, OIStore

DAY = datetime(2026, 10, 30, tzinfo=UTC)
HOUR = timedelta(hours=1)


def at_hour(hour):
    return DAY + hour * HOUR


class MemoryStore(OIStore):
    """Real ledger binding over in-memory rows; never a database, artifact or START."""

    def __init__(self):
        self.review_authority = None
        self.by_hash = {}
        self.history = {"BTCUSDT": [], "ETHUSDT": []}
        self.events = {}
        self.research_failures = []
        self.quarantines = []

    @contextmanager
    def collection_lease(self):
        yield True

    def checkpoint(self, symbol):
        return self.history[symbol][-1] if self.history[symbol] else None

    def _prior_checkpoint(self, current):
        earlier = [
            m
            for m in self.history[current.observation.symbol]
            if m.observation.slot_at < current.observation.slot_at
        ]
        return earlier[-1] if earlier else None

    def publish(self, observation, raw, rights=None, classification=None, *, now=None):
        manifest = OIManifest(
            dataset_version=oi_dataset_version(observation),
            logical_key=(
                f"ds04-a1:{observation.symbol}:{observation.provider_time_ms}:"
                f"{observation.parser_version}"
            ),
            observation=observation,
            rights=rights,
            raw_relative_path=f"oi/raw/{observation.raw_hash}.raw",
            normalized_relative_path=f"oi/normalized/{observation.content_hash()}.json",
            raw_bytes=len(raw),
            normalized_bytes=len(observation.canonical_bytes()),
            normalized_hash=observation.content_hash(),
            created_at=observation.available_at,
            processed_at=observation.available_at,
            classification=classification,
        )
        self.by_hash[manifest.content_hash()] = manifest
        self.history[observation.symbol].append(manifest)
        return manifest

    def manifest_by_hash(self, digest):
        if digest not in self.by_hash:
            raise ValueError("OI_LEDGER_PARENT_MISSING")
        return self.by_hash[digest]

    def quarantine(self, raw, now, reason):
        self.quarantines.append((hashlib.sha256(raw).hexdigest(), now, reason))

    def _append_ledger(
        self, kind, identity, record, recorded_at, required_hashes=(), forecast_hash=None
    ):
        envelope = OILedgerEntry(
            kind=kind,
            identity_hash=hashlib.sha256(identity.encode("ascii")).hexdigest(),
            record_hash=record.content_hash(),
            record_json=record.canonical_bytes().decode("ascii"),
        )
        key = f"oi-ledger:{kind}:{envelope.identity_hash}"
        if key in self.events:
            if self.events[key] != envelope:
                raise ValueError("OI_IMMUTABLE_LEDGER_CONFLICT")
            return envelope.record_hash
        for digest in required_hashes:
            self.manifest_by_hash(digest)
        if forecast_hash is not None and not any(
            entry.kind == "FORECAST" and entry.record_hash == forecast_hash
            for entry in self.events.values()
        ):
            raise ValueError("OI_FORECAST_MISSING")
        self.events[key] = envelope
        return envelope.record_hash

    def _record_by_hash(self, kind, digest):
        rows = [e for e in self.events.values() if e.kind == kind and e.record_hash == digest]
        if len(rows) != 1:
            raise ValueError("OI_LEDGER_RECORD_MISSING")
        return rows[0].record_json

    def ledger(self, kind):
        return [entry for entry in self.events.values() if entry.kind == kind]

    def record_research_failure(self, symbol, slot_at, manifest_hash, code, recorded_at):
        self.research_failures.append((symbol, slot_at, manifest_hash, code, recorded_at))


class Clock:
    def __init__(self, at):
        self.at, self.seconds = at, 0.0

    def now(self):
        return self.at + timedelta(seconds=self.seconds)

    def mono(self):
        return self.seconds

    def wait(self, delay):
        self.seconds += delay
        return False

    def move(self, at):
        self.at, self.seconds = at, 0.0


class HTTP:
    def __init__(self, clock, values=None):
        self.clock, self.values, self.calls = clock, values or {}, []

    def fetch(self, symbol, *, slot_deadline):
        at = self.clock.now()
        self.calls.append((symbol, at))
        body = json.dumps(
            {
                "openInterest": self.values.get((symbol, at.hour), str(100 + at.hour)),
                "symbol": symbol,
                "time": (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
            }
        ).encode()
        return OIReceipt(body, at, at, at)


def configuration():
    return OICollectionConfig(
        enabled=True,
        git_revision="a" * 40,
        code_hash="b" * 64,
        lock_hash="c" * 64,
        preregistration_hash="d" * 64,
        study_id="synthetic-oi-ledger",
        clock_source="synthetic-ntp",
    )


def start_envelope(config):
    # Synthetic test document only: never written, issued or accepted as a real START.
    return OIStartEnvelope(
        owner_authorization_ref="synthetic-owner-ref",
        independent_review_ref="synthetic-review-ref",
        implementation_revision=config.git_revision,
        config_hash=config.content_hash(),
        code_hash=config.code_hash,
        source_hash=config.source.content_hash(),
        rights_hash=config.rights.content_hash(),
        preregistration_hash=config.preregistration_hash,
        issued_at=DAY - timedelta(days=3, minutes=2),
        owner_start_at=DAY - timedelta(days=3, minutes=1),
        expires_at=DAY + timedelta(days=2),
    )


class Harness:
    def __init__(self, store=None, values=None):
        self.config = configuration()
        self.envelope = start_envelope(self.config)
        self.clock = Clock(at_hour(13))
        self.store = store or MemoryStore()
        self.http = HTTP(self.clock, values)
        self.job = OICollectionJob(
            self.config,
            self.store,
            self.http,
            cancel=Event(),
            now=self.clock.now,
            monotonic=self.clock.mono,
            wait=self.clock.wait,
            resources_ready=lambda: True,
        )

    def run(self, hour):
        self.clock.move(at_hour(hour))
        proof = OIClockProof(
            source="synthetic-ntp",
            inspected_at=at_hour(hour),
            time_since_sync_seconds=2,
            offset_bound_ms=5,
            evidence_hash="e" * 64,
        )
        return self.job.run(
            envelope=self.envelope,
            accepted_start_digest=self.envelope.content_hash(),
            clock=proof,
        )

    def fetched(self, hour):
        return [symbol for symbol, at in self.http.calls if at.hour == hour]

    def feature(self, symbol, hour):
        return next(
            f for f in self.store.features() if (f.symbol, f.slot_at) == (symbol, at_hour(hour))
        )


def observed(store, hour, symbol="BTCUSDT", value="100"):
    slot = at_hour(hour)
    raw = json.dumps(
        {
            "openInterest": value,
            "symbol": symbol,
            "time": (slot - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
        }
    ).encode()
    observation = parse_oi(
        raw,
        symbol=symbol,
        slot_at=slot,
        request_sent_at=slot,
        first_seen_at=slot,
        received_at=slot,
        processed_at=slot,
        code_revision="a" * 40,
        code_hash="b" * 64,
    )
    return store.publish(
        observation,
        raw,
        rights=configuration().rights,
        classification=DataUseClass.ENGINEERING_ONLY,
        now=slot,
    )


@pytest.mark.parametrize(
    "hours,reasons,inputs",
    [
        ((14, 15), (), 2),
        ((15, 19), ("NONADJACENT_SLOT",), 1),
        ((20, 22), ("NONADJACENT_SLOT",), 1),
        ((13,), ("INSUFFICIENT_HISTORY",), 1),
    ],
    ids=["adjacent", "daily_protected_gap_15_to_19", "missed_slot", "first_snapshot"],
)
def test_store_recompute_reproduces_job_feature_for_every_prior_checkpoint(hours, reasons, inputs):
    store = MemoryStore()
    manifests = [observed(store, hour, value=str(100 + hour)) for hour in hours]
    current = manifests[-1]
    previous = manifests[0] if len(manifests) == 2 else None
    # Exactly the job's inputs: the checkpoint read before publishing the current slot.
    feature = compute_oi_features(current, previous, at=current.observation.available_at)
    assert feature.reasons == reasons and len(feature.input_manifest_hashes) == inputs
    assert store.append_feature(feature) == feature.content_hash()
    assert store.features() == (feature,)
    assert store.append_feature(feature) == feature.content_hash()


def test_store_recompute_derives_history_and_never_trusts_the_caller_claim():
    store = MemoryStore()
    older, prior, current = (observed(store, hour, value=str(100 + hour)) for hour in (13, 14, 15))
    at = current.observation.available_at
    # A caller hiding the adjacent checkpoint cannot record "no history".
    with pytest.raises(ValueError, match="OI_LEDGER_FEATURE_BINDING"):
        store.append_feature(compute_oi_features(current, None, at=at))
    # A caller cannot select a different earlier snapshot as the feature's history.
    with pytest.raises(ValueError, match="OI_LEDGER_FEATURE_BINDING"):
        store.append_feature(compute_oi_features(current, older, at=at))
    forged = compute_oi_features(current, prior, at=at).model_copy(
        update={"reasons": ("NONADJACENT_SLOT",)}
    )
    with pytest.raises(ValueError, match="OI_LEDGER_FEATURE_BINDING"):
        store.append_feature(forged)
    assert store.features() == ()
    gap = MemoryStore()
    observed(gap, 15)
    late = observed(gap, 19, value="119")
    # Nor may a caller claim "no history" across the daily protected gap.
    with pytest.raises(ValueError, match="OI_LEDGER_FEATURE_BINDING"):
        gap.append_feature(compute_oi_features(late, None, at=late.observation.available_at))


def test_job_collects_both_symbols_across_daily_gap_and_missed_slot():
    harness = Harness()
    for hour in (13, 14, 15, 19, 20, 22):
        result = harness.run(hour)
        assert (result.code, result.exit_code) == ("COMPLETE", 0), (hour, result)
        assert harness.fetched(hour) == ["BTCUSDT", "ETHUSDT"]
        assert len(result.manifests) == 2 and not result.research_failures
    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert harness.feature(symbol, 13).reasons == ("INSUFFICIENT_HISTORY",)
        assert harness.feature(symbol, 14).reasons == ()
        assert harness.feature(symbol, 15).reasons == ()
        # 16:00-18:00 UTC are protected, so 19:00 follows the 15:00 checkpoint every day.
        assert harness.feature(symbol, 19).reasons == ("NONADJACENT_SLOT",)
        assert harness.feature(symbol, 19).fractional_change is None
        assert harness.feature(symbol, 20).reasons == ()
        assert harness.feature(symbol, 22).reasons == ("NONADJACENT_SLOT",)
    assert not harness.store.research_failures
    forecasts = harness.store.forecasts()
    # Centers need h-1, h and h+1 outside protected windows: 14 and 20 only here.
    assert sorted((f.symbol, f.slot_at.hour) for f in forecasts) == [
        ("BTCUSDT", 14),
        ("BTCUSDT", 20),
        ("ETHUSDT", 14),
        ("ETHUSDT", 20),
    ]
    scores = {(s.symbol, s.slot_at.hour): s for s in harness.store.scores()}
    assert len(scores) == 4
    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert scores[(symbol, 14)].eligible and scores[(symbol, 14)].reason == "SCORED"
        # The 21:00 target was never collected: the prediction is retained and flagged.
        assert not scores[(symbol, 20)].eligible
        assert scores[(symbol, 20)].reason == "MISSING_TARGET"


class DivergentHistoryStore(MemoryStore):
    """One symbol's stored history disagrees with the job; the other is healthy."""

    def _prior_checkpoint(self, current):
        if current.observation.symbol == "BTCUSDT":
            return None
        return super()._prior_checkpoint(current)


def test_one_symbol_ledger_failure_never_prevents_the_other_symbol_acquisition():
    harness = Harness(DivergentHistoryStore())
    assert harness.run(13).code == "COMPLETE"
    result = harness.run(14)
    assert harness.fetched(14) == ["BTCUSDT", "ETHUSDT"]
    assert len(result.manifests) == 2
    assert (result.code, result.exit_code) == ("LEDGER_REVIEW_REQUIRED", 6)
    assert result.reason == "OI_RESEARCH_LEDGER_FAILED" and result.forward_days == 0
    assert result.research_failures == ("BTCUSDT:OI_LEDGER_FEATURE_BINDING",)
    btc = harness.store.checkpoint("BTCUSDT")
    assert harness.store.research_failures == [
        (
            "BTCUSDT",
            at_hour(14),
            btc.content_hash(),
            "OI_LEDGER_FEATURE_BINDING",
            btc.observation.available_at,
        )
    ]
    # The healthy symbol keeps its full research chain; the failed one admits nothing.
    assert harness.feature("ETHUSDT", 14).reasons == ()
    assert [f.symbol for f in harness.store.forecasts()] == ["ETHUSDT"]
    assert not [
        f for f in harness.store.features() if (f.symbol, f.slot_at.hour) == ("BTCUSDT", 14)
    ]


def test_ledger_failure_is_still_surfaced_when_the_job_ends_early():
    harness = Harness(DivergentHistoryStore())
    assert harness.run(13).code == "COMPLETE"
    fetch = harness.http.fetch

    def unavailable(symbol, **kwargs):
        if symbol == "ETHUSDT":
            from auvexo_alpha.infrastructure.public_http import SourceError

            raise SourceError("OI_NETWORK")
        return fetch(symbol, **kwargs)

    harness.http.fetch = unavailable
    result = harness.run(14)
    assert (result.code, result.reason, result.exit_code) == (
        "SOURCE_UNAVAILABLE",
        "OI_NETWORK",
        5,
    )
    assert result.research_failures == ("BTCUSDT:OI_LEDGER_FEATURE_BINDING",)
    assert len(harness.store.research_failures) == 1


def test_unrecordable_ledger_failure_is_never_swallowed():
    class Unrecordable(DivergentHistoryStore):
        def record_research_failure(self, *args):
            raise ValueError("OI_QUOTA_PAUSE")

    harness = Harness(Unrecordable())
    assert harness.run(13).code == "COMPLETE"
    with pytest.raises(ValueError, match="OI_QUOTA_PAUSE"):
        harness.run(14)
    assert harness.fetched(14) == ["BTCUSDT"]


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("free text with a provider value 123.45"), "ValueError"),
        (PermissionError("C:/private/path"), "PermissionError"),
        (ValueError("OI_QUOTA_PAUSE"), "OI_QUOTA_PAUSE"),
    ],
)
def test_ledger_failure_record_carries_a_stable_code_and_never_exception_text(error, code):
    class Failing(MemoryStore):
        def append_feature(self, feature):
            if feature.symbol == "BTCUSDT":
                raise error
            return super().append_feature(feature)

    harness = Harness(Failing())
    result = harness.run(13)
    assert harness.fetched(13) == ["BTCUSDT", "ETHUSDT"]
    assert result.research_failures == ("BTCUSDT:" + code,)
    assert [row[3] for row in harness.store.research_failures] == [code]
    assert result.exit_code == 6


def test_zero_or_late_target_is_recorded_unscored_and_the_job_continues():
    harness = Harness(values={("BTCUSDT", 15): "0"})
    for hour in (13, 14):
        assert harness.run(hour).code == "COMPLETE"
    result = harness.run(15)
    assert result.code == "COMPLETE" and harness.fetched(15) == ["BTCUSDT", "ETHUSDT"]
    scores = {s.symbol: s for s in harness.store.scores()}
    assert scores["ETHUSDT"].eligible
    assert not scores["BTCUSDT"].eligible and scores["BTCUSDT"].outcome is None
    assert scores["BTCUSDT"].reason == "TARGET_NONPOSITIVE_VALUE"
    assert (
        scores["BTCUSDT"].target_manifest_hash == harness.store.checkpoint("BTCUSDT").content_hash()
    )
    assert harness.feature("BTCUSDT", 15).level == Decimal(0)
    # The original prediction is retained unchanged beside its missing-outcome flag.
    assert [f.slot_at.hour for f in harness.store.forecasts() if f.symbol == "BTCUSDT"] == [14]
