"""Shared synthetic NON_COUNTING observation fixtures; never genuine day evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from auvexo_alpha.application.observation_qualification import (
    evaluate_observation_day,
    plan_observation_intent,
)
from auvexo_alpha.domain.market_data import (
    Candle,
    CoverageReport,
    DataAvailabilityWindow,
    DatasetManifest,
    SourceRecord,
)
from auvexo_alpha.domain.observation import (
    ObservationClockProof,
    ObservationConfig,
    ObservationFact,
    ObservationProposalTrace,
    ObservationResources,
    ObservationRunEvidence,
    ObservationVerification,
    observation_market,
    observation_policy,
    observation_release,
    observation_spec,
)
from auvexo_alpha.domain.paper import PaperAccountSnapshot
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.domain.paper_risk import assess_paper
from auvexo_alpha.infrastructure.source_registry import identity, rights

BEGIN = datetime(2026, 10, 21, 16, tzinfo=UTC)
END = BEGIN + timedelta(hours=1)
HASH = "1" * 64


def changed(model, **values):
    return type(model).model_validate(model.model_dump() | values)


def fact_for(symbol, minute, *, day=BEGIN, delay=3, close="50000"):
    finish = day + timedelta(minutes=minute)
    received = finish + timedelta(seconds=delay)
    opened = finish - timedelta(minutes=1)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    start_ms = int((opened - epoch).total_seconds() * 1000)
    end_ms = int((finish - epoch).total_seconds() * 1000) - 1
    url = (
        "https://data-api.binance.vision/api/v3/klines?symbol="
        + symbol
        + f"&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    candle = Candle(
        instrument_id="binance.spot." + symbol,
        symbol=symbol,
        interval="1m",
        base_currency="BTC" if symbol == "BTCUSDT" else "ETH",
        open_at=opened,
        end_at=finish,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1"),
        quote_volume=Decimal(close),
        trades=1,
        source=SourceRecord(
            source_id="DS-02",
            source_url=url,
            source_hash=HASH,
            raw_open=start_ms,
            raw_close=end_ms,
            timestamp_unit="MILLISECOND",
            received_at=received,
        ),
        availability=DataAvailabilityWindow(
            original_first_seen_at=received,
            received_at=received,
            processed_at=received,
            available_at=received,
            historical_close_bound=finish,
            basis="OBSERVED_RECEIPT",
        ),
    )
    version = sha256((symbol + str(finish)).encode()).hexdigest()
    manifest = DatasetManifest(
        dataset_version=version,
        logical_key="observation." + symbol + "." + version[:12],
        source=identity("DS-02"),
        rights=rights("DS-02"),
        source_url=url,
        source_hash=HASH,
        checksum_verified=False,
        raw_bytes=1,
        raw_relative_path="bronze/" + HASH + ".raw",
        parquet_hash=HASH,
        parquet_bytes=1,
        relative_path="partitions/binance.spot." + symbol + "/" + version + ".parquet",
        normalized_hash=sha256(candle.canonical_bytes()).hexdigest(),
        code_revision="a" * 40,
        code_hash=HASH,
        created_at=received,
        processed_at=received,
        coverage=CoverageReport(
            instrument_id=candle.instrument_id,
            interval="1m",
            requested_start=opened,
            requested_end=finish,
            earliest=opened,
            latest_end=finish,
            expected_rows=1,
            observed_rows=1,
            rejected_rows=0,
            findings=(),
            status="PASS",
        ),
        supersedes=None,
        changed_rows=0,
    )
    server = finish + timedelta(seconds=2)
    raw = '{"serverTime":' + str(int((server - epoch).total_seconds() * 1000)) + "}"
    clock = ObservationClockProof(
        source_url="https://data-api.binance.vision/api/v3/time",
        raw_json=raw,
        raw_hash=sha256(raw.encode()).hexdigest(),
        sent_at=server - timedelta(milliseconds=10),
        received_at=server + timedelta(milliseconds=10),
        server_at=server,
    )
    return ObservationFact(observation_id=uuid4(), candle=candle, manifest=manifest, clock=clock)


def make_config():
    return ObservationConfig(
        campaign_id="synthetic.noncounting.v1",
        git_revision="a" * 40,
        rights=rights("DS-02"),
        source=identity("DS-02"),
        specs=tuple(
            observation_spec(symbol, observed_at=BEGIN) for symbol in ("BTCUSDT", "ETHUSDT")
        ),
    )


def account_at(now):
    return PaperAccountSnapshot(
        account_ref="paper.observation",
        epoch=1,
        snapshot_id=uuid4(),
        as_of=now,
        reconciled_at=now,
        day_start_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
        currency="USDT",
        cash=Decimal("10000"),
        equity=Decimal("10000"),
        high_water_equity=Decimal("10000"),
        day_start_equity=Decimal("10000"),
        reconciled=True,
        kill=KillLevel.K1,
    )


def witness(evidence):
    return ObservationVerification(
        run_evidence_hash=evidence.content_hash(),
        source_fact_hashes=tuple(f.content_hash() for f in evidence.facts),
        trace_hashes=tuple(t.content_hash() for t in evidence.traces),
        journal_tail_hash=evidence.journal_tail_hash,
        replay_journal_hash=evidence.journal_tail_hash,
        replay_intent_hashes=tuple(t.intent.content_hash() for t in evidence.traces),
        replay_decision_hashes=tuple(t.decision.content_hash() for t in evidence.traces),
        reservation_hashes=evidence.reservation_hashes,
        outbox_hashes=evidence.outbox_hashes,
        fill_hashes=evidence.fill_hashes,
        privilege_identity_hash=HASH,
    )


def make_run(*, points=60, minutes=None):
    config = make_config()
    facts = tuple(
        fact_for(symbol, minute)
        for minute in (range(points) if minutes is None else minutes)
        for symbol in ("BTCUSDT", "ETHUSDT")
    )
    traces = []
    release = observation_release(config, now=BEGIN)
    for fact in facts:
        now = fact.candle.availability.available_at
        account = account_at(now)
        intent = plan_observation_intent(config, fact, account, release, now=now)
        if intent is None:
            continue
        market = observation_market(fact)
        spec = next(s for s in config.specs if s.instrument_id == fact.candle.instrument_id)
        decision = assess_paper(
            intent, observation_policy(config), market, spec, account, release, now=now
        )
        assert decision.status == "DENIED"
        decision = changed(decision, exposure=None)
        traces.append(
            ObservationProposalTrace(
                proposal_id=uuid4(),
                source_observation_hash=fact.content_hash(),
                intent=intent,
                decision=decision,
                account_before=account,
                market=market,
                spec=spec,
                release=release,
                journal_event_hash=HASH,
            )
        )
    evidence = ObservationRunEvidence(
        run_id=uuid4(),
        campaign_id=config.campaign_id,
        local_day=BEGIN.date().isoformat(),
        kind="NON_COUNTING",
        scheduled_at=BEGIN,
        started_at=BEGIN,
        ended_at=END,
        config_hash=config.content_hash(),
        facts=facts,
        traces=tuple(traces),
        final_account=account_at(END),
        truth_cursor=1,
        journal_tail_hash=HASH,
        resource_snapshots=(
            ObservationResources(
                observed_at=BEGIN,
                available_ram_bytes=4_000_000_000,
                cpu_percent=Decimal("20"),
                cpu_high_for_seconds=0,
            ),
        ),
    )
    return config, evidence, witness(evidence)


def evaluate(config, evidence):
    return evaluate_observation_day(config, evidence, witness(evidence), now=END)
