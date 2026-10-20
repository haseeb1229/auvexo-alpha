"""NON_COUNTING synthetic dispatch proof against isolated real PAPER PostgreSQL."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from paper_fixtures import fixture_bundle

from auvexo_alpha.application.offline_execution import OfflineExecutionCoordinator
from auvexo_alpha.domain.contracts import Venue
from auvexo_alpha.domain.gateway import AccountAttestation
from auvexo_alpha.domain.paper import PaperAuthorization, PaperPosition, PaperReason
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.fake_execution import FakeExecutionTransport, SyntheticScenario
from auvexo_alpha.infrastructure.offline_paper import OfflinePaperAdapter, OfflineTruthAdapter
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from tools.paper_local import engine_for, isolated_database, require_migration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def offline_database():
    with isolated_database() as database:
        require_migration(database)
        yield database


@pytest.fixture
def offline_core(offline_database):
    runtime = engine_for(offline_database, "auvexo_paper")
    owner = engine_for(offline_database, "auvexo_paper_owner")
    simulator = engine_for(offline_database, "auvexo_paper_truth")
    try:
        bundle = fixture_bundle(account_ref="paper.offline." + uuid4().hex)
        store = PaperStore(runtime, owner_engine=owner)
        truth = PaperTruth(simulator)
        store.initialize(bundle.account, bundle.policy, bundle.release, now=bundle.now)
        epoch = store.acquire_writer(bundle.account.account_ref, now=bundle.now)
        assert store.reconcile(bundle.account.account_ref, now=bundle.now)
        store.resume(bundle.account.account_ref, actor="owner.fixture", now=bundle.now)
        bundle.account = store.account(bundle.account.account_ref)
        bundle.intent = bundle.rebind()
        yield bundle, store, truth, epoch
    finally:
        runtime.dispose()
        owner.dispose()
        simulator.dispose()


def identity(bundle):
    return AccountAttestation(
        account_ref=bundle.account.account_ref,
        venue=Venue.BINANCE,
        server="synthetic.offline.server",
        account_identifier="synthetic.offline.account",
        account_kind="DEMO",
        currency="USD",
        account_mode="HEDGING",
        observed_at=bundle.now,
        capability_hash="2" * 64,
    )


def establish(bundle, store, execution):
    assert execution.reconnect(
        bundle.account.account_ref, epoch=bundle.account.epoch, now=bundle.now
    )
    bundle.account = store.account(bundle.account.account_ref)
    bundle.intent = bundle.rebind()


def coordinator(bundle, store, truth, scenario=SyntheticScenario.ACKNOWLEDGE, *, ready=True):
    pin = identity(bundle)
    transport = FakeExecutionTransport(OfflineTruthAdapter(truth), pin, scenario)
    execution = OfflineExecutionCoordinator(OfflinePaperAdapter(store), transport, pin)
    if ready:
        establish(bundle, store, execution)
        transport.queries.clear()
    return execution, transport


def authorize(bundle, store):
    result = store.authorize(
        bundle.intent,
        bundle.policy,
        bundle.market,
        bundle.spec,
        bundle.release,
        now=bundle.now,
    )
    assert result.decision.status == "APPROVED"
    return result.authorization


def submit(bundle, execution, epoch):
    return execution.authorize_and_submit(
        bundle.intent,
        bundle.policy,
        bundle.market,
        bundle.spec,
        bundle.release,
        epoch=epoch,
        now=bundle.now,
    )


def test_offline_claim_is_committed_before_first_send_and_duplicate_cannot_send(offline_core):
    b, store, truth, epoch = offline_core

    class InspectingTransport(FakeExecutionTransport):
        def submit(self, intent, authorization, market, *, now):
            # A fresh connection sees the durable claim before transport entry.
            outbox = store.outbox(intent.content_hash())
            assert outbox["state"] == "SENT_PENDING" and outbox["attempts"] == 1
            assert any(e["kind"] == "DISPATCH_ATTEMPT" for e in store.journal(intent.account_ref))
            super().submit(intent, authorization, market, now=now)

    transport = InspectingTransport(OfflineTruthAdapter(truth), identity(b))
    execution = OfflineExecutionCoordinator(OfflinePaperAdapter(store), transport, identity(b))
    establish(b, store, execution)
    result = submit(b, execution, epoch)
    assert result.outcome == "RECONCILED"
    assert result.submission.authorization.semantics == "PAPER_NONEXTERNAL"
    with pytest.raises(ValueError, match="PAPER_DISPATCH_BINDING_OR_FRESHNESS_DENIED"):
        execution.dispatch(
            b.intent, result.submission.authorization, b.market, epoch=epoch, now=b.now
        )
    assert transport.sent == [b.intent.content_hash()]
    assert store.outbox(b.intent.content_hash())["attempts"] == 1
    assert len(store.reservations(b.account.account_ref)) == 1


@pytest.mark.parametrize(
    "scenario,sends",
    [
        (SyntheticScenario.TIMEOUT_BEFORE_SEND, 0),
        (SyntheticScenario.TIMEOUT_AFTER_SEND, 1),
        (SyntheticScenario.CRASH_BEFORE_SEND, 0),
        (SyntheticScenario.CRASH_AFTER_SEND, 1),
    ],
)
def test_offline_ambiguous_attempt_restart_queries_only_and_retains_capacity(
    offline_core, scenario, sends
):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth, scenario)
    if scenario in (SyntheticScenario.CRASH_BEFORE_SEND, SyntheticScenario.CRASH_AFTER_SEND):
        with pytest.raises(SystemExit, match="SYNTHETIC_PROCESS_CRASH"):
            submit(b, execution, epoch)
        assert store.outbox(b.intent.content_hash())["state"] == "SENT_PENDING"
    else:
        assert submit(b, execution, epoch).outcome == "UNKNOWN"
    assert len(transport.sent) == sends
    # New objects have no prior in-memory sends. Database history controls recovery.
    restarted, replacement = coordinator(b, PaperStore(store.engine), truth, ready=False)
    assert not restarted.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert replacement.sent == [] and replacement.queries == [b.account.account_ref]
    outbox = store.outbox(b.intent.content_hash())
    assert (outbox["state"], outbox["attempts"]) == ("UNKNOWN", 1)
    reservation = store.reservations(b.account.account_ref)[0]
    assert reservation.state == "UNKNOWN" and reservation.quantity == b.intent.quantity
    assert store.account(b.account.account_ref).kill >= KillLevel.K1
    auth = next(
        e["data"]["authorization"]
        for e in store.journal(b.account.account_ref)
        if e["kind"] == "AUTHORIZED"
    )

    with pytest.raises(ValueError):
        restarted.dispatch(
            b.intent, PaperAuthorization.model_validate(auth), b.market, epoch=epoch, now=b.now
        )
    assert replacement.sent == []


def test_offline_rejection_is_authoritative_synthetic_fact_not_new_risk_rule(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth, SyntheticScenario.REJECT)
    assert submit(b, execution, epoch).outcome == "RECONCILED"
    assert store.outbox(b.intent.content_hash())["state"] == "REJECTED"
    assert not store.reservations(b.account.account_ref)
    assert store.account(b.account.account_ref).positions == ()
    assert transport.sent == [b.intent.content_hash()]


def test_offline_partial_duplicate_and_cancel_fill_race_preserve_facts(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    assert submit(b, execution, epoch).outcome == "RECONCILED"
    event_id = str(uuid4())
    for _ in range(2):
        truth.fill(
            b.intent.content_hash(),
            "0.004",
            b.intent.entry,
            account_ref=b.account.account_ref,
            now=b.now,
            event_id=event_id,
        )
    assert store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(b.intent.content_hash())["state"] == "PARTIALLY_FILLED"
    assert store.reservations(b.account.account_ref)[0].quantity == Decimal("0.006")
    truth.status(b.intent.content_hash(), "CANCELED", account_ref=b.account.account_ref, now=b.now)
    truth.fill(
        b.intent.content_hash(),
        "0.006",
        b.intent.entry,
        account_ref=b.account.account_ref,
        now=b.now + timedelta(microseconds=1),
    )
    truth.status(
        b.intent.content_hash(),
        "ACKNOWLEDGED",
        account_ref=b.account.account_ref,
        now=b.now + timedelta(microseconds=2),
    )
    assert store.reconcile(b.account.account_ref, now=b.now + timedelta(microseconds=2))
    assert store.outbox(b.intent.content_hash())["state"] == "FILLED"
    assert store.account(b.account.account_ref).positions[0].quantity == Decimal("0.01")
    assert not store.reservations(b.account.account_ref)
    assert len([e for e in truth.events(b.account.account_ref) if e["kind"] == "FILL"]) == 2
    assert len(transport.sent) == 1


def test_offline_reject_with_late_partial_remains_unknown_until_bound_finality(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth, SyntheticScenario.REJECT)
    assert submit(b, execution, epoch).outcome == "RECONCILED"
    late = b.now + timedelta(microseconds=1)
    truth.fill(
        b.intent.content_hash(),
        "0.004",
        b.intent.entry,
        account_ref=b.account.account_ref,
        now=late,
    )
    assert not store.reconcile(b.account.account_ref, now=late)
    assert store.outbox(b.intent.content_hash())["state"] == "UNKNOWN"
    assert store.reservations(b.account.account_ref)[0].quantity == b.intent.quantity
    facts = OfflineTruthAdapter(truth)
    facts.resolve(
        b.intent.content_hash(),
        "CANCELED",
        Decimal("0.004"),
        account_ref=b.account.account_ref,
        now=late,
        evidence_hash="1" * 64,
        event_id=str(uuid4()),
    )
    assert store.reconcile(b.account.account_ref, now=late)
    assert not store.reservations(b.account.account_ref)
    assert store.account(b.account.account_ref).positions[0].quantity == Decimal("0.004")
    assert len(transport.sent) == 1
    assert store.account(b.account.account_ref).kill >= KillLevel.K1


def test_offline_late_ack_cannot_free_unknown_capacity_or_trigger_resend(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth, SyntheticScenario.TIMEOUT_AFTER_SEND)
    assert submit(b, execution, epoch).outcome == "UNKNOWN"
    truth.status(
        b.intent.content_hash(), "ACKNOWLEDGED", account_ref=b.account.account_ref, now=b.now
    )
    # Acknowledgment is an observed order fact, never a repeat dispatch.
    assert execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert len(transport.sent) == 1
    assert store.reservations(b.account.account_ref)[0].quantity == b.intent.quantity
    assert store.account(b.account.account_ref).kill >= KillLevel.K1


@pytest.mark.parametrize(
    "change",
    [
        {"authorization_id": uuid4()},
        {"account_ref": "paper.wrong"},
        {"writer_epoch": 999},
        {"release_hash": "0" * 64},
        {"policy_hash": "0" * 64},
        {"reservation_id": uuid4()},
    ],
)
def test_offline_altered_authorization_denied_before_any_fake_send(offline_core, change):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorization = authorize(b, store).model_copy(update=change)
    with pytest.raises(ValueError):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
    assert transport.sent == [] and not truth.events(b.account.account_ref)
    assert store.outbox(b.intent.content_hash())["attempts"] == 0


@pytest.mark.parametrize("cause", ["expired", "stale_writer", "kill", "market_bind"])
def test_offline_current_dispatch_guards_precede_send(offline_core, cause):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorization = authorize(b, store)
    now, market = b.now, b.market
    if cause == "expired":
        now += timedelta(seconds=31)
    elif cause == "stale_writer":
        store.acquire_writer(b.account.account_ref, now=b.now)
    elif cause == "kill":
        store.set_kill(b.account.account_ref, KillLevel.K4, actor="owner.fixture", now=b.now)
    else:
        market = market.model_copy(update={"snapshot_id": uuid4()})
    with pytest.raises(ValueError):
        execution.dispatch(b.intent, authorization, market, epoch=epoch, now=now)
    assert transport.sent == [] and not truth.events(b.account.account_ref)
    assert store.outbox(b.intent.content_hash())["attempts"] == 0


def test_offline_truth_fence_handles_writer_change_between_claim_and_send(offline_core):
    b, store, truth, epoch = offline_core

    class FencedTransport(FakeExecutionTransport):
        def submit(self, intent, authorization, market, *, now):
            store.acquire_writer(intent.account_ref, now=now)
            super().submit(intent, authorization, market, now=now)

    transport = FencedTransport(OfflineTruthAdapter(truth), identity(b))
    execution = OfflineExecutionCoordinator(OfflinePaperAdapter(store), transport, identity(b))
    establish(b, store, execution)
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER_OR_UNCLAIMED_ORDER"):
        submit(b, execution, epoch)
    assert not truth.events(b.account.account_ref) and transport.sent == []
    assert store.outbox(b.intent.content_hash())["attempts"] == 1
    newer = store.account(b.account.account_ref).epoch
    assert not execution.reconnect(b.account.account_ref, epoch=newer, now=b.now)
    assert store.outbox(b.intent.content_hash())["state"] == "UNKNOWN"
    assert transport.sent == []


def test_offline_unattempted_reservation_restart_never_dispatches(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorize(b, store)
    assert execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert transport.sent == []
    assert store.outbox(b.intent.content_hash())["attempts"] == 0
    assert store.outbox(b.intent.content_hash())["state"] == "RESERVED"
    assert store.reservations(b.account.account_ref)


def test_offline_external_position_requires_reconciliation_and_stays_paused(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    position = PaperPosition(
        position_ref="external.offline.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=b.intent.entry,
        mark_price=b.intent.entry,
        mark_as_of=b.now,
        fx_as_of=b.now,
        stop_price=b.intent.stop,
    )
    OfflineTruthAdapter(truth).external_position(
        b.account.account_ref, position, now=b.now, event_id=str(uuid4())
    )
    assert not execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert store.account(b.account.account_ref).kill >= KillLevel.K1
    b.account = store.account(b.account.account_ref)
    b.intent = b.rebind()
    result = submit(b, execution, epoch)
    assert result.outcome == "DENIED"
    assert PaperReason.KILL_BLOCKED in result.submission.decision.reasons
    assert transport.sent == []


def test_offline_disconnect_and_failed_protection_require_owner_recovery(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    transport.connected = False
    assert submit(b, execution, epoch).outcome == "UNKNOWN"
    assert not execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert transport.sent == []
    execution.failed_protection(b.account.account_ref, now=b.now)
    assert store.account(b.account.account_ref).kill == KillLevel.K4
    transport.connected = True
    # Attestation failed before claim; this reservation has never been attempted.
    assert store.outbox(b.intent.content_hash())["attempts"] == 0
    assert execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert store.account(b.account.account_ref).kill == KillLevel.K4
    with pytest.raises(ValueError, match="EXPLICIT_OWNER_RESUME_REQUIRED"):
        execution.shutdown(b.account.account_ref, now=b.now)
    assert store.account(b.account.account_ref).kill == KillLevel.K4


def test_offline_unexpected_transport_corruption_propagates_and_restart_never_resends(offline_core):
    b, store, truth, epoch = offline_core

    class CorruptTransport(FakeExecutionTransport):
        def submit(self, intent, authorization, market, *, now):
            raise ValueError("SYNTHETIC_CORRUPT_TRANSPORT_FACT")

    transport = CorruptTransport(OfflineTruthAdapter(truth), identity(b))
    execution = OfflineExecutionCoordinator(OfflinePaperAdapter(store), transport, identity(b))
    establish(b, store, execution)
    with pytest.raises(ValueError, match="SYNTHETIC_CORRUPT_TRANSPORT_FACT"):
        submit(b, execution, epoch)
    assert store.outbox(b.intent.content_hash())["state"] == "SENT_PENDING"
    assert store.outbox(b.intent.content_hash())["attempts"] == 1
    restarted, replacement = coordinator(b, store, truth, ready=False)
    assert not restarted.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    assert store.outbox(b.intent.content_hash())["state"] == "UNKNOWN"
    assert replacement.sent == []


def test_offline_initial_and_reconstructed_coordinator_refuse_before_startup_reconcile(
    offline_core,
):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth, ready=False)
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        submit(b, execution, epoch)
    assert transport.sent == [] and store.journal(b.account.account_ref)[-1]["kind"] != "AUTHORIZED"
    establish(b, store, execution)
    authorization = authorize(b, store)
    reconstructed, fresh = coordinator(b, store, truth, ready=False)
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        reconstructed.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
    assert fresh.sent == [] and store.outbox(b.intent.content_hash())["attempts"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"server": "synthetic.other.server"},
        {"account_kind": "REAL"},
        {"account_identifier": "synthetic.other.account"},
        {"capability_hash": "3" * 64},
    ],
)
def test_offline_identity_drift_revokes_readiness_and_latches_pause(offline_core, change):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorization = authorize(b, store)
    transport.identity = AccountAttestation.model_validate(transport.identity.model_dump() | change)
    with pytest.raises(ValueError, match="ACCOUNT_ATTESTATION_DRIFT|ACCOUNT_MODE_DENIED"):
        execution.reconnect(b.account.account_ref, epoch=epoch, now=b.now)
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
    assert transport.sent == [] and store.outbox(b.intent.content_hash())["attempts"] == 0
    assert store.account(b.account.account_ref).kill == KillLevel.K1


def test_offline_readiness_is_bound_to_exact_account_and_epoch(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorization = authorize(b, store)
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch + 1, now=b.now)
    with pytest.raises(ValueError, match="OFFLINE_ACCOUNT_BINDING_DENIED"):
        execution.reconnect("paper.unbound", epoch=epoch, now=b.now)
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
    assert transport.sent == [] and store.outbox(b.intent.content_hash())["attempts"] == 0


def test_offline_identity_drift_between_startup_and_send_refuses_before_claim(offline_core):
    b, store, truth, epoch = offline_core
    execution, transport = coordinator(b, store, truth)
    authorization = authorize(b, store)
    transport.identity = AccountAttestation.model_validate(
        transport.identity.model_dump() | {"server": "synthetic.drifted.server"}
    )
    with pytest.raises(ValueError, match="ACCOUNT_ATTESTATION_DRIFT"):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
    assert transport.sent == [] and store.outbox(b.intent.content_hash())["attempts"] == 0
    assert store.account(b.account.account_ref).kill == KillLevel.K1
    with pytest.raises(ValueError, match="OFFLINE_RECONCILIATION_REQUIRED"):
        execution.dispatch(b.intent, authorization, b.market, epoch=epoch, now=b.now)
