"""Offline coordinator through recording fakes; no database, broker or order capability."""

from types import SimpleNamespace

import pytest
from paper_fixtures import HASH, NOW, fixture_bundle

from auvexo_alpha.application.gateway_ports import (
    PendingOfflineAttempt,
    SyntheticTransportUnavailable,
)
from auvexo_alpha.application.offline_execution import OfflineExecutionCoordinator
from auvexo_alpha.domain.contracts import Venue
from auvexo_alpha.domain.gateway import AccountAttestation
from auvexo_alpha.domain.paper_lifecycle import KillLevel

ACCOUNT = "paper.test"
EPOCH = 7
LEVELS = (KillLevel.K0, KillLevel.K1, KillLevel.K2, KillLevel.K3, KillLevel.K4)


def pinned(**changes):
    data = dict(
        account_ref=ACCOUNT,
        venue=Venue.BINANCE,
        server="synthetic.offline.server",
        account_identifier="synthetic.offline.account",
        account_kind="DEMO",
        currency="USD",
        account_mode="HEDGING",
        observed_at=NOW,
        capability_hash="2" * 64,
    )
    return AccountAttestation.model_validate(data | changes)


class RecordingPaper:
    """Mirrors the accepted store's escalate-only kill rule and records every call."""

    def __init__(self, log, *, kill=KillLevel.K0, orders=(), reconciled=True, kill_error=None):
        self.log, self.kill, self.orders = log, kill, dict(orders)
        self.reconciled, self.kill_error = reconciled, kill_error
        self.kill_journal = []

    def set_kill(self, account_ref, level, *, actor, now):
        self.log.append(("set_kill", level, actor))
        if self.kill_error is not None:
            raise self.kill_error
        if level < self.kill:
            raise ValueError("EXPLICIT_OWNER_RESUME_REQUIRED")
        self.kill = level
        self.kill_journal.append((actor, level))

    def pending(self, account_ref):
        return tuple(
            PendingOfflineAttempt(intent_hash, state)
            for intent_hash, state in self.orders.items()
            if state not in ("FILLED", "REJECTED", "CANCELED", "EXPIRED")
        )

    def mark_unknown(self, intent_hash, epoch, *, now):
        assert epoch == EPOCH
        self.log.append(("mark_unknown", intent_hash))
        self.orders[intent_hash] = "UNKNOWN"
        self.kill = max(self.kill, KillLevel.K1)

    def reconcile(self, account_ref, *, now):
        self.log.append(("reconcile",))
        return self.reconciled

    def claim(self, intent_hash, epoch, *, now, authorization):
        self.log.append(("claim", intent_hash))
        self.orders[intent_hash] = "SENT_PENDING"
        return authorization

    def authorize(self, intent, policy, market, spec, release, *, now):
        self.log.append(("authorize",))
        return self.submission


class RecordingTransport:
    def __init__(self, log, identity, *, attests=True, queries=True, submits=True):
        self.log, self.identity = log, identity
        self.attests, self.queries, self.submits = attests, queries, submits

    def attest(self, *, now):
        self.log.append(("attest",))
        if not self.attests:
            raise SyntheticTransportUnavailable("SYNTHETIC_DISCONNECTED")
        return AccountAttestation.model_validate(self.identity.model_dump() | {"observed_at": now})

    def submit(self, intent, authorization, market, *, now):
        self.log.append(("submit", intent.content_hash()))
        if not self.submits:
            raise SyntheticTransportUnavailable("SYNTHETIC_RESPONSE_LOST")

    def query(self, account_ref, *, now):
        self.log.append(("query",))
        if not self.queries:
            raise SyntheticTransportUnavailable("SYNTHETIC_DISCONNECTED")


def build(*, drift=None, ready=False, **paper):
    log = []
    store = RecordingPaper(log, **paper)
    transport = RecordingTransport(log, pinned())
    execution = OfflineExecutionCoordinator(store, transport, pinned())
    if ready:
        assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW)
        log.clear()
    if drift is not None:
        transport.identity = pinned(**drift)
    return execution, store, transport, log


def sent(log):
    return [entry for entry in log if entry[0] in ("submit", "claim")]


def order():
    bundle = fixture_bundle(account_ref=ACCOUNT)
    authorization = SimpleNamespace(market_hash=bundle.market.content_hash())
    return bundle, authorization


DRIFTS = (
    ({"server": "synthetic.other.server"}, "ACCOUNT_ATTESTATION_DRIFT"),
    ({"account_identifier": "synthetic.other.account"}, "ACCOUNT_ATTESTATION_DRIFT"),
    ({"capability_hash": "3" * 64}, "ACCOUNT_ATTESTATION_DRIFT"),
    ({"account_kind": "REAL"}, "ACCOUNT_MODE_DENIED"),
)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("drift,code", DRIFTS)
def test_drift_is_journaled_at_every_kill_level_and_the_drift_error_propagates(level, drift, code):
    execution, store, _, log = build(kill=level, drift=drift)
    with pytest.raises(ValueError) as caught:
        execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW)
    assert str(caught.value) == code
    expected = max(level, KillLevel.K1)
    assert store.kill_journal == [("offline.identity.drift", expected)]
    assert store.kill == expected and store.kill >= level
    # Requests only ever ascend; the single accepted one is the journaled level.
    requested = [entry[1] for entry in log if entry[0] == "set_kill"]
    assert requested == sorted(requested) and requested[-1] == expected
    assert [entry[0] for entry in log if entry[0] != "set_kill"] == ["attest"]


@pytest.mark.parametrize("level", (KillLevel.K2, KillLevel.K3, KillLevel.K4))
def test_drift_before_dispatch_above_k1_never_claims_or_sends_and_revokes_readiness(level):
    execution, store, transport, log = build(ready=True)
    store.kill = level
    transport.identity = pinned(server="synthetic.drifted.server")
    bundle, authorization = order()
    with pytest.raises(ValueError, match="^ACCOUNT_ATTESTATION_DRIFT$"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert store.kill_journal == [("offline.identity.drift", level)] and store.kill == level
    assert sent(log) == [] and store.orders == {}
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert sent(log) == []


def test_a_failed_drift_journal_write_surfaces_and_is_not_retried_at_another_level():
    failure = ValueError("CORRUPT_PAPER_JOURNAL")
    execution, store, _, log = build(
        kill=KillLevel.K3, drift={"server": "synthetic.other.server"}, kill_error=failure
    )
    with pytest.raises(ValueError, match="CORRUPT_PAPER_JOURNAL") as caught:
        execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW)
    assert caught.value is failure
    assert str(caught.value.__context__) == "ACCOUNT_ATTESTATION_DRIFT"
    assert [entry for entry in log if entry[0] == "set_kill"] == [
        ("set_kill", KillLevel.K1, "offline.identity.drift")
    ]
    assert store.kill == KillLevel.K3 and store.kill_journal == []


@pytest.mark.parametrize("level", LEVELS)
def test_shutdown_journals_at_the_current_or_k1_level_and_never_lowers_or_raises(level):
    execution, store, _, log = build(kill=level)
    execution.shutdown(ACCOUNT, now=NOW)
    expected = max(level, KillLevel.K1)
    assert store.kill_journal == [("offline.shutdown", expected)]
    assert store.kill == expected and store.kill >= level
    assert [entry[0] for entry in log] == ["set_kill"] * len(log)
    bundle, authorization = order()
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)


def test_failed_protection_still_latches_k4_directly():
    execution, store, _, log = build(kill=KillLevel.K2)
    execution.failed_protection(ACCOUNT, now=NOW)
    assert log == [("set_kill", KillLevel.K4, "offline.protection.failed")]
    assert store.kill == KillLevel.K4


def test_reconnect_with_consistent_truth_leaves_acknowledged_orders_alone():
    orders = {"a" * 64: "ACKNOWLEDGED", "b" * 64: "PARTIALLY_FILLED", "c" * 64: "RESERVED"}
    execution, store, _, log = build(orders=orders)
    assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW) is True
    assert log == [("attest",), ("query",), ("reconcile",)]
    assert store.orders == orders and store.kill == KillLevel.K0
    assert store.kill_journal == []


def test_reconnect_marks_only_unobserved_attempts_unknown_before_the_query():
    orders = {
        "a" * 64: "SENT_PENDING",
        "b" * 64: "UNKNOWN",
        "c" * 64: "ACKNOWLEDGED",
        "d" * 64: "PARTIALLY_FILLED",
        "e" * 64: "RESERVED",
        "f" * 64: "FILLED",
    }
    execution, store, _, log = build(orders=orders)
    assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW) is True
    assert log == [
        ("attest",),
        ("mark_unknown", "a" * 64),
        ("mark_unknown", "b" * 64),
        ("query",),
        ("reconcile",),
    ]
    assert store.orders["c" * 64] == "ACKNOWLEDGED"
    assert store.orders["d" * 64] == "PARTIALLY_FILLED"
    assert store.orders["e" * 64] == "RESERVED" and store.orders["f" * 64] == "FILLED"
    assert store.kill == KillLevel.K1 and sent(log) == []


def test_reconnect_failed_query_escalates_acknowledged_orders_and_stays_unready():
    orders = {"a" * 64: "ACKNOWLEDGED", "b" * 64: "PARTIALLY_FILLED", "c" * 64: "RESERVED"}
    execution, store, transport, log = build(orders=orders)
    transport.queries = False
    assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW) is False
    assert log == [
        ("attest",),
        ("query",),
        ("mark_unknown", "a" * 64),
        ("mark_unknown", "b" * 64),
    ]
    assert store.orders == {"a" * 64: "UNKNOWN", "b" * 64: "UNKNOWN", "c" * 64: "RESERVED"}
    assert store.kill == KillLevel.K1
    bundle, authorization = order()
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert sent(log) == []


def test_reconnect_truth_mismatch_escalates_acknowledged_orders_after_reconcile():
    orders = {"a" * 64: "ACKNOWLEDGED", "b" * 64: "PARTIALLY_FILLED", "c" * 64: "RESERVED"}
    execution, store, _, log = build(orders=orders, reconciled=False)
    assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW) is False
    assert log == [
        ("attest",),
        ("query",),
        ("reconcile",),
        ("mark_unknown", "a" * 64),
        ("mark_unknown", "b" * 64),
    ]
    assert store.orders["c" * 64] == "RESERVED" and store.kill == KillLevel.K1
    assert sent(log) == []


def test_reconnect_without_attestation_changes_nothing_and_queries_nothing():
    orders = {"a" * 64: "ACKNOWLEDGED", "b" * 64: "SENT_PENDING"}
    execution, store, transport, log = build(orders=orders)
    transport.attests = False
    assert execution.reconnect(ACCOUNT, epoch=EPOCH, now=NOW) is False
    assert log == [("attest",)] and store.orders == orders and store.kill == KillLevel.K0


def test_dispatch_without_attestation_is_not_attempted_and_nothing_is_claimed_or_sent():
    execution, store, transport, log = build(ready=True)
    transport.attests = False
    bundle, authorization = order()
    outcome = execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert outcome == "NOT_ATTEMPTED"
    assert log == [("attest",)] and store.orders == {} and store.kill == KillLevel.K0
    # Nothing was attempted, and nothing may be sent without a fresh reconciliation.
    transport.attests = True
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert sent(log) == []


def test_lost_response_after_the_claim_is_unknown_and_is_never_sent_twice():
    execution, store, transport, log = build(ready=True)
    transport.submits = False
    bundle, authorization = order()
    intent_hash = bundle.intent.content_hash()
    outcome = execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert outcome == "UNKNOWN"
    assert log == [
        ("attest",),
        ("claim", intent_hash),
        ("submit", intent_hash),
        ("mark_unknown", intent_hash),
    ]
    assert store.orders == {intent_hash: "UNKNOWN"} and store.kill == KillLevel.K1
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(bundle.intent, authorization, bundle.market, epoch=EPOCH, now=NOW)
    assert len(sent(log)) == 2


@pytest.mark.parametrize(
    "attests,reconciled,outcome",
    ((False, True, "NOT_ATTEMPTED"), (True, True, "RECONCILED"), (True, False, "UNKNOWN")),
)
def test_authorize_and_submit_reports_each_distinct_outcome(attests, reconciled, outcome):
    execution, store, transport, log = build(ready=True)
    bundle, authorization = order()
    transport.attests, store.reconciled = attests, reconciled
    store.submission = SimpleNamespace(
        decision=SimpleNamespace(status="APPROVED"), authorization=authorization, reservation=None
    )
    result = execution.authorize_and_submit(
        bundle.intent,
        bundle.policy,
        bundle.market,
        bundle.spec,
        bundle.release,
        epoch=EPOCH,
        now=NOW,
    )
    assert result.outcome == outcome and result.submission is store.submission
    assert len(sent(log)) == (0 if outcome == "NOT_ATTEMPTED" else 2)


def test_denied_decision_is_never_attested_claimed_or_sent():
    execution, store, _, log = build(ready=True)
    bundle, _ = order()
    store.submission = SimpleNamespace(
        decision=SimpleNamespace(status="DENIED"), authorization=None, reservation=None
    )
    result = execution.authorize_and_submit(
        bundle.intent,
        bundle.policy,
        bundle.market,
        bundle.spec,
        bundle.release,
        epoch=EPOCH,
        now=NOW,
    )
    assert result.outcome == "DENIED" and log == [("authorize",)]
    assert HASH != bundle.intent.content_hash()
