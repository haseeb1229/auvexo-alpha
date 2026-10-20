# Synthetic integration facts cannot qualify a genuine observation date.
"""Real isolated PG source publication, authorization, causal fill and replay."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import text

from auvexo_alpha.application.observation_qualification import plan_observation_intent
from auvexo_alpha.domain.observation import (
    ObservationConfig,
    ObservationProposalTrace,
    ObservationRunEvidence,
    observation_market,
    observation_release,
    observation_spec,
    observation_window,
)
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.observation_simulator import CausalPaperSimulator
from auvexo_alpha.infrastructure.observation_store import ObservationStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response
from auvexo_alpha.infrastructure.source_registry import identity, rights
from tools.paper_local import admin_args
from tools.paper_observation_local import engine_for, isolated_observation_database

pytestmark = pytest.mark.integration


def test_synthetic_source_authorize_later_fill_and_immutable_receipt_replay():
    # Past synthetic time is injected only into this isolated fixture. No START,
    # scheduled run or genuine receipt exists; database server time stays real.
    day = (datetime.now(UTC) - timedelta(days=1)).date()
    begin, _ = observation_window(day)
    clock = [begin + timedelta(milliseconds=100)]
    with isolated_observation_database() as database, TemporaryDirectory() as temporary:
        engines = [
            engine_for(database, g)
            for g in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        try:
            source = DataStore(engines[2], Path(temporary) / "market", Path(temporary))
            store = ObservationStore(*engines, source_store=source)
            config = ObservationConfig(
                campaign_id="synthetic.pipeline.noncounting",
                git_revision="a" * 40,
                rights=rights("DS-02"),
                source=identity("DS-02"),
                specs=tuple(observation_spec(s, observed_at=begin) for s in ("BTCUSDT", "ETHUSDT")),
            )
            key = store.prepare(config, now=begin)
            run_id = store.begin(key, kind="PREFLIGHT", now=begin)
            # Only this owned test DB permits a synthetic historical run envelope.
            # The production run guard/server clock and activation stay unchanged.
            with psycopg.connect(dbname=database, **admin_args()) as admin:
                admin.execute("ALTER TABLE paper_observation_run DISABLE TRIGGER USER")
                admin.execute(
                    "UPDATE paper_observation_run SET started_at=%s,local_date=%s WHERE run_id=%s",
                    (begin, day, str(run_id)),
                )
                admin.execute("ALTER TABLE paper_observation_run ENABLE TRIGGER USER")
            paper = store.paper
            epoch = paper.acquire_writer(config.account_ref, now=clock[0])
            assert paper.reconcile(config.account_ref, now=clock[0])
            paper.resume(config.account_ref, actor="owner.synthetic.pipeline", now=clock[0])

            def transport(url, limit):
                epoch_time = datetime(1970, 1, 1, tzinfo=UTC)
                if urlsplit(url).path.endswith("/time"):
                    return Response(
                        200,
                        json.dumps(
                            {"serverTime": int((clock[0] - epoch_time).total_seconds() * 1000)}
                        ).encode(),
                    )
                query = parse_qs(urlsplit(url).query)
                price = "50000" if clock[0] < begin + timedelta(minutes=1) else "49900"
                row = [
                    int(query["startTime"][0]),
                    price,
                    price,
                    price,
                    price,
                    "1",
                    int(query["endTime"][0]),
                    price,
                    1,
                    "1",
                    "1",
                    "0",
                ]
                return Response(200, json.dumps([row]).encode())

            feed = ObservationFeed(
                source,
                PublicHTTP(Event(), transport=transport, wait=lambda _: False),
                config.git_revision,
                config.campaign_id,
                clock=lambda: clock[0],
            )
            first = feed.poll("BTCUSDT", window_start=begin, window_end=begin + timedelta(hours=1))
            assert first is not None
            store.append_feed(run_id, first, now=clock[0])
            account = paper.account(config.account_ref)
            release = observation_release(config, now=begin)
            intent = plan_observation_intent(config, first, account, release, now=clock[0])
            assert intent is not None
            from auvexo_alpha.domain.observation import observation_policy

            submission = paper.authorize(
                intent,
                observation_policy(config),
                observation_market(first),
                config.specs[0],
                release,
                now=clock[0],
            )
            assert submission.decision.status == "APPROVED"
            trace = ObservationProposalTrace(
                proposal_id=uuid4(),
                source_observation_hash=first.content_hash(),
                intent=intent,
                decision=submission.decision,
                account_before=account,
                market=observation_market(first),
                spec=config.specs[0],
                release=release,
                authorization=submission.authorization,
                reservation=submission.reservation,
                journal_event_hash=paper.journal(config.account_ref)[-1]["content_hash"],
            )
            store.append_trace(run_id, trace, now=clock[0])
            simulator = CausalPaperSimulator(paper, PaperTruth(engines[2]))
            simulator.accept(intent, submission, first, epoch=epoch, now=clock[0])
            clock[0] += timedelta(minutes=1)
            later = feed.poll("BTCUSDT", window_start=begin, window_end=begin + timedelta(hours=1))
            assert later is not None
            store.append_feed(run_id, later, now=clock[0])
            fills = simulator.observe(later, now=clock[0])
            assert len(fills) == 1 and fills[0].price < intent.entry
            store.append_simulation(run_id, fills[0], now=clock[0])
            assert paper.reconcile(config.account_ref, now=clock[0])
            state = store.snapshot(run_id)
            evidence = ObservationRunEvidence(
                run_id=run_id,
                campaign_id=config.campaign_id,
                local_day=day.isoformat(),
                scheduled_at=begin,
                started_at=begin,
                ended_at=clock[0],
                config_hash=key,
                facts=store.feeds(run_id),
                traces=store.traces(run_id),
                simulation_traces=store.simulations(run_id),
                **state,
            )
            # A fact committed between snapshot and receipt cannot be ignored.
            truth = PaperTruth(engines[2])
            truth.adjustment(config.account_ref, "0.01", now=clock[0])
            with pytest.raises(ValueError, match="CLOSURE_NOT_CURRENT"):
                store.close(run_id, evidence, now=datetime.now(UTC))
            assert paper.reconcile(config.account_ref, now=clock[0])
            evidence = ObservationRunEvidence.model_validate(
                evidence.model_dump() | store.snapshot(run_id)
            )
            receipt = store.close(run_id, evidence, now=datetime.now(UTC))
            assert receipt.status == "INCOMPLETE" and receipt.kind == "NON_COUNTING"
            assert receipt.fill_count == 1 and receipt.authorization_count == 1
            assert store.qualified_dates(key, now=datetime.now(UTC)).qualified_count == 0
            assert (
                store.verify(run_id, evidence, now=datetime.now(UTC)).replay_journal_hash
                == evidence.journal_tail_hash
            )
            # Later account history cannot rewrite a previously closed prefix.
            truth.adjustment(config.account_ref, "0.01", now=clock[0] + timedelta(seconds=1))
            assert paper.reconcile(config.account_ref, now=clock[0] + timedelta(seconds=1))
            assert (
                store.verify(run_id, evidence, now=datetime.now(UTC)).replay_journal_hash
                == evidence.journal_tail_hash
            )
            with engines[0].connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM paper_production_release")) == 0
                assert conn.scalar(text("SELECT count(*) FROM paper_observation_activation")) == 0
        finally:
            for engine in engines:
                engine.dispose()
