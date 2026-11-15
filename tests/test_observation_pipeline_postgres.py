# Synthetic integration facts cannot qualify a genuine observation date.
"""Campaign v2 on real isolated PG: verified inputs, authorize, fill, close, replay.

STORE_VERIFIED binds every authorization to the database clock (ADR-032 OBV2-07), so these
nights run in real time on synthetic one-minute bars outside any genuine window. The first
waits for two minute boundaries, the runner night for three; no START, scheduled run or
genuine receipt exists.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from observation_fixtures import clock_gate, clock_proof, make_config_v2, spec_check
from sqlalchemy import text

from auvexo_alpha.application import observation_qualification, observation_runner
from auvexo_alpha.application.observation_gates import observed_specs
from auvexo_alpha.application.observation_runner import ObservationRunner
from auvexo_alpha.domain.contracts import MoneyAction
from auvexo_alpha.domain.observation import (
    ObservationProposalTrace,
    ObservationResources,
    ObservationRunEvidence,
    observation_market,
    observation_policy,
    observation_window,
)
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperIntent
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.observation_paper import (
    ObservationPaperCommands,
    ObservationPaperTruth,
)
from auvexo_alpha.infrastructure.observation_simulator import CausalPaperSimulator
from auvexo_alpha.infrastructure.observation_store import ObservationStore, ledger_mismatch_count
from auvexo_alpha.infrastructure.paper_truth import PaperTruth, truth_rows
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response
from tools.paper_observation_local import engine_for, isolated_observation_database

pytestmark = pytest.mark.integration
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def now():
    return datetime.now(UTC)


def floor_minute(value):
    return value.replace(second=0, microsecond=0)


def wait_until(instant):
    while (remaining := (instant - now()).total_seconds()) > 0:
        time.sleep(min(remaining, 1.0))


def intent_for(config, fact, account, release, spec, *, action, quantity, entry, stop, ref=None):
    at = now()
    return PaperIntent(
        intent_id=uuid4(),
        logical_key="observation.pipeline." + uuid4().hex,
        account_ref=config.account_ref,
        instrument_id=fact.candle.instrument_id,
        action=action,
        side="BUY" if action == MoneyAction.OPEN else "SELL",
        quantity=quantity,
        entry=entry,
        stop=stop,
        release_hash=release.content_hash(),
        spec_hash=spec.content_hash(),
        snapshot_hash=observation_market(fact, config).content_hash(),
        account_snapshot_hash=account.content_hash(),
        policy_hash=observation_policy(config).content_hash(),
        created_at=at,
        expires_at=at + timedelta(seconds=90),
        position_ref=ref,
    )


def test_v2_verified_inputs_authorize_fill_close_reconcile_with_zero_mismatches():
    with isolated_observation_database() as database, TemporaryDirectory() as temporary:
        engines = [
            engine_for(database, g)
            for g in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        try:
            source = DataStore(engines[2], Path(temporary) / "market", Path(temporary))
            store = ObservationStore(*engines, source_store=source)
            config = make_config_v2(campaign_id="synthetic.pipeline.v2", at=now())
            account_ref = config.account_ref
            key = store.prepare(config, now=now())
            run_id = store.begin(key, kind="PREFLIGHT", now=now())
            paper, truth = store.paper, PaperTruth(engines[2])
            release = store.pinned_release(config)
            # Leave the first bar enough of its 60 s market-age bound for the authorization.
            if now().second > 40:
                wait_until(floor_minute(now()) + MINUTE + timedelta(seconds=1))
            first_end = floor_minute(now())
            prices = {
                first_end: "50000",
                first_end + MINUTE: "49900",
                first_end + 2 * MINUTE: "50100",
            }
            # Run start order: writer, reconcile, roll, then specification facts.
            epoch = paper.acquire_writer(account_ref, now=now())
            assert paper.reconcile(account_ref, now=now())
            with pytest.raises(ValueError, match="UTC_DAY_NOT_ADVANCED"):
                paper.roll_flat_boundary(account_ref, now=now())
            specs = observed_specs(
                config, tuple(spec_check(s, at=now()) for s in ("BTCUSDT", "ETHUSDT"))
            )
            for spec in specs:
                truth.observe_spec(account_ref, spec, now=now())
            assert paper.reconcile(account_ref, now=now())
            paper.resume(account_ref, actor="owner.synthetic.pipeline", now=now())

            def transport(url, limit):
                if urlsplit(url).path.endswith("/time"):
                    stamp = (now() - EPOCH) // timedelta(milliseconds=1)
                    return Response(200, json.dumps({"serverTime": stamp}).encode())
                query = parse_qs(urlsplit(url).query)
                ended = int(query["endTime"][0]) + 1
                price = prices[EPOCH + timedelta(milliseconds=ended)]
                row = [int(query["startTime"][0]), price, price, price, price, "1"]
                row += [ended - 1, price, 1, "1", "1", "0"]
                return Response(200, json.dumps([row]).encode())

            feed = ObservationFeed(
                source,
                PublicHTTP(Event(), transport=transport, wait=lambda _: False),
                config.git_revision,
                config.campaign_id,
                clock_bound_ms=2000,
            )
            window = (first_end - MINUTE, first_end + timedelta(hours=1))

            def observe(expected_end):
                wait_until(expected_end + timedelta(milliseconds=300))
                fact = feed.poll("BTCUSDT", window_start=window[0], window_end=window[1])
                assert fact is not None and fact.candle.end_at == expected_end
                store.append_feed(run_id, fact, now=now())
                market = observation_market(fact, config)
                assert market.price_basis == "BAR_CLOSE"
                truth.mark(account_ref, market, now=now())
                return fact

            def propose(fact, **terms):
                # Reconcile, decide and claim back to back: the kernel bounds the account's
                # age (5 s) at both the decision and the claim.
                assert paper.reconcile(account_ref, now=now())
                account = paper.account(account_ref)
                intent = intent_for(config, fact, account, release, specs[0], **terms)
                submission = paper.authorize(
                    intent,
                    observation_policy(config),
                    observation_market(fact, config),
                    specs[0],
                    release,
                    now=now(),
                )
                assert submission.decision.status == "APPROVED", submission.decision.reasons
                decided = paper.journal(account_ref)[-1]["content_hash"]
                simulator.accept(intent, submission, fact, epoch=epoch, now=now())
                store.append_trace(
                    run_id,
                    ObservationProposalTrace(
                        proposal_id=uuid4(),
                        source_observation_hash=fact.content_hash(),
                        intent=intent,
                        decision=submission.decision,
                        account_before=account,
                        market=observation_market(fact, config),
                        spec=specs[0],
                        release=release,
                        authorization=submission.authorization,
                        reservation=submission.reservation,
                        journal_event_hash=decided,
                    ),
                    now=now(),
                )

            simulator = CausalPaperSimulator(paper, truth, config)
            first = observe(first_end)
            propose(
                first,
                action=MoneyAction.OPEN,
                quantity=Decimal("0.001"),
                entry=Decimal("50000"),
                stop=Decimal("49500"),
            )
            second = observe(first_end + MINUTE)
            (fill,) = simulator.observe(second, now=now())
            store.append_simulation(run_id, fill, now=now())
            assert paper.reconcile(account_ref, now=now())
            (position,) = paper.account(account_ref).positions
            propose(
                second,
                action=MoneyAction.CLOSE,
                quantity=position.quantity,
                entry=Decimal("49900"),
                stop=position.stop_price,
                ref=position.position_ref,
            )
            third = observe(first_end + 2 * MINUTE)
            (close_fill,) = simulator.observe(third, now=now())
            store.append_simulation(run_id, close_fill, now=now())
            assert paper.reconcile(account_ref, now=now())
            assert paper.account(account_ref).positions == ()
            state = store.snapshot(run_id)
            assert state["terminal_authorization_count"] == 2
            assert (
                state["ledger_mismatch_count"]
                == 0
                == paper.ledger_replay(account_ref).mismatch_count
            )
            assert state["day_roll_hash"] is None
            run = store.run(run_id)
            ended = now()
            evidence = ObservationRunEvidence(
                run_id=run_id,
                campaign_id=config.campaign_id,
                local_day=run["local_date"].isoformat(),
                scheduled_at=observation_window(run["local_date"])[0],
                started_at=run["started_at"],
                ended_at=ended,
                config_hash=key,
                facts=store.feeds(run_id),
                traces=store.traces(run_id),
                simulation_traces=store.simulations(run_id),
                **state,
            )
            receipt = store.close(run_id, evidence, now=now())
            # NON_COUNTING, and a v2 receipt still states every OBV2-12 input it lacks.
            assert receipt.kind == "NON_COUNTING" and receipt.status == "INCOMPLETE"
            assert receipt.authorization_count == 2 and receipt.fill_count == 2
            assert receipt.terminal_authorization_count == 2
            assert receipt.ledger_mismatch_count == 0 and receipt.position_hashes == ()
            assert {"DAY_NOT_ROLLED", "CLOCK_UNTRUSTED", "SPEC_UNVERIFIED"} <= set(receipt.reasons)
            assert "DENIAL_ONLY" not in receipt.reasons
            assert receipt.price_basis == "BAR_CLOSE"
            assert store.verify(run_id, evidence, now=now()).journal_tail_hash == (
                evidence.journal_tail_hash
            )
            assert store.qualified_dates(key, now=now()).qualified_count == 0
            # A stored account that disagrees with the replayed journal is counted.
            with engines[0].connect() as conn:
                truth_events = truth_rows(conn, account_ref)
            journal = paper.journal(account_ref)
            final = paper.account(account_ref)
            cursor = int(state["truth_cursor"])
            assert ledger_mismatch_count(account_ref, journal, truth_events, final, cursor) == 0
            tampered = final.model_copy(update={"cash": final.cash + Decimal("0.01")})
            assert ledger_mismatch_count(account_ref, journal, truth_events, tampered, cursor) >= 1
            with engines[0].connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM paper_production_release")) == 0
                assert conn.scalar(text("SELECT count(*) FROM paper_observation_activation")) == 0
        finally:
            for engine in engines:
                engine.dispose()


class RunnerGates:
    """PREFLIGHT start gates measured on the real clock; no provider or scheduler log."""

    def provenance(self, *, window_start, window_end):
        raise AssertionError("a PREFLIGHT run reads no scheduler provenance")

    def clock(self):
        return clock_gate(now(), spread_ms=1)

    def provider_time(self):
        return clock_proof(now(), spread_ms=1)

    def spec(self, symbol):
        return spec_check(symbol, at=now())


def test_runner_holds_btc_and_eth_across_a_minute_boundary_without_a_kill(monkeypatch):
    """Finding 1 regression, through ObservationRunner on the real store and truth.

    Both symbols open on one bar, fill on the next, stay open across a further boundary
    and close. A reconciliation between the two marks of one bar would value the other
    open position on the previous bar, past the 60 s bound, and raise K1. Fake time cannot
    be used: STORE_VERIFIED ties every decision to the database clock. The 16:00 UTC window
    is therefore compressed to seven minutes from the current minute (the planner opens
    only before the last five minutes), and the night is cancelled once both closes fill,
    about three minutes after the first bar.
    """
    with isolated_observation_database() as database, TemporaryDirectory() as temporary:
        engines = [
            engine_for(database, g)
            for g in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        try:
            source = DataStore(engines[2], Path(temporary) / "market", Path(temporary))
            store = ObservationStore(*engines, source_store=source)
            config = make_config_v2(campaign_id="synthetic.runner.v2", at=now())
            account_ref = config.account_ref
            store.prepare(config, now=now())
            paper, truth = store.paper, PaperTruth(engines[2])
            # Leave the first bar most of its 60 s market-age bound for the opens.
            if now().second > 30:
                wait_until(floor_minute(now()) + MINUTE + timedelta(seconds=1))
            first_end = floor_minute(now())
            window = (first_end, first_end + 7 * MINUTE)
            for module in (observation_runner, observation_qualification):
                monkeypatch.setattr(module, "observation_window", lambda day: window)
            closes = {"BTCUSDT": ("50000", "49900", "49900", "50100")}
            closes["ETHUSDT"] = ("3000", "2994", "2994", "3006")
            cancel = Event()

            def transport(url, limit):
                if urlsplit(url).path.endswith("/time"):
                    stamp = (now() - EPOCH) // timedelta(milliseconds=1)
                    return Response(200, json.dumps({"serverTime": stamp}).encode())
                query = parse_qs(urlsplit(url).query)
                ended = int(query["endTime"][0]) + 1
                minute = (EPOCH + timedelta(milliseconds=ended) - first_end) // MINUTE
                symbol = query["symbol"][0]
                price = closes[symbol][minute]
                if symbol == "ETHUSDT" and minute == 3:
                    # Both closes fill on this bar; the runner finishes the pair, then stops.
                    cancel.set()
                row = [int(query["startTime"][0]), price, price, price, price, "1"]
                row += [ended - 1, price, 1, "1", "1", "0"]
                return Response(200, json.dumps([row]).encode())

            class OwnerResumedFeed(ObservationFeed):
                """A PREFLIGHT run has no standing authority: the owner resumes the writer
                K1 once, by hand, after the start reconciliation and before any bar."""

                def require_ready(self, config, *, now):
                    super().require_ready(config, now=now)
                    resumed_at = datetime.now(UTC)
                    paper.resume(account_ref, actor="owner.synthetic.runner", now=resumed_at)

            feed = OwnerResumedFeed(
                source,
                PublicHTTP(Event(), transport=transport, wait=lambda _: False),
                config.git_revision,
                config.campaign_id,
                clock_bound_ms=2000,
            )
            runner = ObservationRunner(
                config,
                store,
                ObservationPaperCommands(paper),
                ObservationPaperTruth(truth),
                feed,
                simulator=CausalPaperSimulator(paper, truth, config),
                gates=RunnerGates(),
                cancel=cancel,
                resources=lambda at: ObservationResources(
                    observed_at=at,
                    available_ram_bytes=4_000_000_000,
                    cpu_percent="0",
                    cpu_high_for_seconds=0,
                ),
                pause_optional_research=lambda: True,
            )
            receipt = runner.run(kind="PREFLIGHT")

            account = paper.account(account_ref)
            # Every journal step after the start, so a timing failure names its cause.
            trail = [
                (
                    e["kind"],
                    str(e["recorded_at"]),
                    e["data"].get("actor"),
                    e["data"].get("reasons"),
                    e["data"].get("marks"),
                    (e["data"].get("account") or {}).get("kill"),
                    [
                        p.get("mark_as_of")
                        for p in (e["data"].get("account") or {}).get("positions", [])
                    ],
                )
                for e in paper.journal(account_ref)
            ]
            assert account.kill == KillLevel.K0 and account.reconciled, trail
            assert account.positions == () and not account.unknown_orders, trail
            assert receipt.kind == "NON_COUNTING" and receipt.status == "INCOMPLETE"
            assert receipt.paired_observations == 4
            assert receipt.authorization_count == receipt.proposal_count == 4
            assert receipt.fill_count == 4 and receipt.terminal_authorization_count == 4
            assert receipt.ledger_mismatch_count == 0 and receipt.position_hashes == ()
            assert paper.ledger_replay(account_ref).mismatch_count == 0
            journal = paper.journal(account_ref)
            resumed = max(i for i, e in enumerate(journal) if e["kind"] == "OWNER_PAPER_RESUME")
            after = journal[resumed + 1 :]
            assert not [e for e in after if e["kind"] == "KILL_STATE"]
            assert all(e["data"]["marks_fresh"] for e in after if e["kind"] == "MARK_HEALTH")
            states = [
                PaperAccountSnapshot.model_validate_json(json.dumps(e["data"]["account"]))
                for e in after
                if e["kind"] == "RECONCILIATION"
            ]
            assert all(s.reconciled and s.kill == KillLevel.K0 for s in states)
            # Both positions were held, freshly marked, across the second bar's boundary.
            held = first_end + 2 * MINUTE
            assert any(
                len(s.positions) == 2 and all(p.mark_as_of == held for p in s.positions)
                for s in states
            )
            assert states[-1].positions == ()
        finally:
            for engine in engines:
                engine.dispose()
