"""Synthetic adapter and orchestration checks; no network, DB or observation credit."""

from datetime import timedelta
from decimal import Decimal

import pytest
from observation_fixtures import BEGIN, account_at, changed, fact_for, make_config, make_run

from auvexo_alpha.application.observation_qualification import plan_observation_intent
from auvexo_alpha.application.observation_replay import replay_observation_traces
from auvexo_alpha.application.observation_runner import ObservationRunner, resource_actions
from auvexo_alpha.application.observation_simulator import PendingSimulation, causal_fill_price
from auvexo_alpha.domain.observation import ObservationResources, observation_release


def pending_fixture():
    config = make_config()
    fact = fact_for("BTCUSDT", 0)
    now = fact.candle.availability.available_at
    intent = plan_observation_intent(
        config, fact, account_at(now), observation_release(config, now=BEGIN), now=now
    )
    assert intent is not None
    return PendingSimulation(intent, fact, intent.quantity)


def test_causal_simulation_only_later_independently_received_bounded_close():
    pending = pending_fixture()
    later = fact_for("BTCUSDT", 1, close="49900")
    price = causal_fill_price(pending, later, now=later.candle.availability.available_at)
    assert price == Decimal("49924.95")
    assert price <= pending.intent.entry
    assert (
        causal_fill_price(
            pending, fact_for("BTCUSDT", 1, close="51000"), now=BEGIN + timedelta(seconds=63)
        )
        is None
    )
    assert causal_fill_price(pending, later, now=pending.intent.expires_at) is None


@pytest.mark.parametrize("case", ("same_bar", "wrong_symbol", "future", "receipt_not_later"))
def test_causal_simulation_refuses_noncausal_facts(case):
    pending = pending_fixture()
    later = fact_for(
        "ETHUSDT" if case == "wrong_symbol" else "BTCUSDT", 0 if case == "same_bar" else 1
    )
    now = later.candle.availability.available_at
    if case == "future":
        now -= timedelta(microseconds=1)
    if case == "receipt_not_later":
        later = changed(
            later,
            candle=changed(
                later.candle,
                source=changed(
                    later.candle.source, received_at=pending.source.candle.source.received_at
                ),
            ),
        )
    with pytest.raises(ValueError, match="FILL_CAUSALITY_DENIED"):
        causal_fill_price(pending, later, now=now)


def test_offline_replay_reproduces_all_denials_and_refuses_mutated_inputs():
    config, evidence, _ = make_run()
    intents, decisions = replay_observation_traces(config, evidence.facts, evidence.traces)
    assert intents == tuple(t.intent.content_hash() for t in evidence.traces)
    assert decisions == tuple(t.decision.content_hash() for t in evidence.traces)
    trace = evidence.traces[0]
    forged = changed(trace, market=changed(trace.market, bid=trace.market.bid - 1))
    with pytest.raises(ValueError, match="REPLAY_BINDING_MISMATCH"):
        replay_observation_traces(config, evidence.facts, (forged,))
    with pytest.raises(ValueError, match="DUPLICATE_SOURCE"):
        replay_observation_traces(config, evidence.facts + evidence.facts[:1], evidence.traces)


@pytest.mark.parametrize(
    "ram,cpu,duration,healthy,expected",
    (
        (3_000_000_000, "80", 60, True, ()),
        (2_999_999_999, "20", 0, True, ("PAUSE_OPTIONAL_RESEARCH",)),
        (4_000_000_000, "81", 59, True, ()),
        (4_000_000_000, "81", 60, True, ("PAUSE_OPTIONAL_RESEARCH",)),
        (1_499_999_999, "20", 0, True, ("PAUSE_OPTIONAL_RESEARCH", "PAUSE_NEW_ENTRIES")),
        (4_000_000_000, "20", 0, False, ("PAUSE_NEW_ENTRIES",)),
    ),
)
def test_resource_actions_fail_closed_at_exact_boundaries(ram, cpu, duration, healthy, expected):
    sample = ObservationResources(
        observed_at=BEGIN,
        available_ram_bytes=ram,
        cpu_percent=Decimal(cpu),
        cpu_high_for_seconds=duration,
    )
    assert resource_actions(sample, healthy=healthy) == expected


def test_prepared_campaign_refuses_before_writer_or_feed():
    calls = []

    class Prepared:
        def verify_schema(self):
            calls.append("schema")

        def begin(self, *args, **kwargs):
            calls.append("begin")
            raise ValueError("OBSERVATION_CAMPAIGN_NOT_ACTIVATED")

    class NoAction:
        def __getattr__(self, name):
            pytest.fail("Unexpected execution before PREPARED refusal: " + name)

    runner = ObservationRunner(
        make_config(),
        Prepared(),
        NoAction(),
        NoAction(),
        NoAction(),
        clock=lambda: BEGIN,
        simulator=NoAction(),
        resources=lambda now: None,
    )
    with pytest.raises(ValueError, match="NOT_ACTIVATED"):
        runner.run()
    assert calls == ["schema", "begin"]
