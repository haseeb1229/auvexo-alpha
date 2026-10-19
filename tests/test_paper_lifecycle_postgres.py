"""Synthetic lifecycle history in isolated PostgreSQL; no operational promotion."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from multiprocessing import get_context
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import HASH, NOW, fixture_bundle, research_release
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.paper_lifecycle import (
    Release,
    ReleaseDataEligibility,
    ReleaseState,
    ReleaseTransition,
    SourceEligibility,
    transition_release,
)
from auvexo_alpha.infrastructure.paper_store import PaperStore
from tools.paper_local import engine_for, isolated_database, require_migration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def lifecycle_database():
    with isolated_database() as database:
        require_migration(database)
        yield database


@pytest.fixture
def lifecycle_store(lifecycle_database):
    runtime = engine_for(lifecycle_database, "auvexo_paper")
    owner = engine_for(lifecycle_database, "auvexo_paper_owner")
    try:
        yield PaperStore(runtime, owner_engine=owner)
    finally:
        runtime.dispose()
        owner.dispose()


def synthetic_production():
    release = research_release(eligible=True)
    return Release.model_validate(
        release.model_dump() | {"release_id": "synthetic.lifecycle." + uuid4().hex}
    )


def registry_rows(store, release_id, *, fixture=False):
    tables = (
        ("paper_release", "paper_lifecycle")
        if fixture
        else ("paper_production_release", "paper_production_lifecycle")
    )
    with store.engine.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    f"SELECT row_to_json(t)::text FROM {table} t "
                    "WHERE payload::jsonb->>'release_id'=:identity "
                    "ORDER BY row_to_json(t)::text"
                ),
                {"identity": release_id},
            ).all()
            for table in tables
        )


def assert_chain(store, releases, *, fixture=False):
    table = "paper_lifecycle" if fixture else "paper_production_lifecycle"
    release_id = releases[0].release_id
    snapshots, history_rows = registry_rows(store, release_id, fixture=fixture)
    assert len(snapshots) == len(history_rows) == len(releases)
    if fixture:
        with pytest.raises(ValueError, match="UNKNOWN_RELEASE_IDENTITY"):
            store.current_release(release_id)
    else:
        assert store.current_release(release_id) == releases[-1]
    with store.engine.connect() as conn:
        history = conn.execute(
            text(
                f"SELECT release_hash,payload,content_hash,recorded_at FROM {table} "
                "WHERE payload::jsonb->>'release_id'=:identity ORDER BY sequence"
            ),
            {"identity": release_id},
        ).all()
    for index, (release_hash, payload, content_hash, recorded_at) in enumerate(history):
        assert sha256(payload.encode()).hexdigest() == content_hash
        assert release_hash == releases[index].content_hash()
        if index == 0:
            assert Release.model_validate_json(payload) == releases[0]
            assert recorded_at == releases[0].created_at
        else:
            transition = ReleaseTransition.model_validate_json(payload)
            assert transition.release_id == release_id
            assert transition.prior_hash == releases[index - 1].content_hash()
            assert transition.next_hash == releases[index].content_hash()
            assert transition.from_state == releases[index - 1].state
            assert transition.to_state == releases[index].state
            assert transition.evidence_hash == releases[index].evidence_hash
            assert transition.recorded_at == recorded_at


def advance(store, release, target, *, at=None, role="OWNER"):
    instant = at or (release.updated_at or release.created_at) + timedelta(seconds=1)
    updated, transition = transition_release(
        release,
        target,
        actor="synthetic.owner" if role == "OWNER" else "synthetic.independent.reviewer",
        actor_role=role,
        approved_at=instant,
        evidence_hash=HASH,
    )
    store.register_release(updated, transition=transition, now=instant)
    return updated, transition


def test_p4_production_initial_research_has_exact_initial_history(lifecycle_store):
    store = lifecycle_store
    release = synthetic_production()
    assert registry_rows(store, release.release_id) == ([], [])
    store.register_release(release, now=NOW)
    assert_chain(store, [release])


@pytest.mark.parametrize("state", [s for s in ReleaseState if s != ReleaseState.RESEARCH])
def test_p4_production_initial_promoted_or_terminal_state_is_refused(lifecycle_store, state):
    store = lifecycle_store
    release = synthetic_production()
    forged = Release.model_validate(release.model_dump() | {"state": state})
    with pytest.raises(ValueError, match="INITIAL_PRODUCTION_RESEARCH_REQUIRED"):
        store.register_release(forged, now=NOW)
    assert registry_rows(store, release.release_id) == ([], [])
    with pytest.raises(ValueError, match="UNKNOWN_RELEASE_IDENTITY"):
        store.current_release(release.release_id)


@pytest.mark.parametrize("state", list(ReleaseState))
def test_p4_existing_identity_cannot_reinitialize_without_transition(lifecycle_store, state):
    store = lifecycle_store
    release = synthetic_production()
    store.register_release(release, now=NOW)
    before = registry_rows(store, release.release_id)
    changed = Release.model_validate(release.model_dump() | {"state": state})
    with pytest.raises(ValueError):
        store.register_release(changed, now=NOW)
    assert registry_rows(store, release.release_id) == before
    assert_chain(store, [release])


def test_p4_legal_adjacent_production_metadata_transitions_append_complete_history(lifecycle_store):
    store = lifecycle_store
    release = synthetic_production()
    store.register_release(release, now=NOW)
    chain = [release]
    for target in (
        ReleaseState.CANDIDATE,
        ReleaseState.VALIDATED,
        ReleaseState.PAPER,
        ReleaseState.SHADOW,
        ReleaseState.LIVE_LIMITED,
        ReleaseState.LIVE,
    ):
        release, _ = advance(store, release, target)
        chain.append(release)
        assert_chain(store, chain)
    assert release.allowed_modes == fixture_bundle().release.allowed_modes


@pytest.mark.parametrize(
    ("prior_state", "target"),
    (
        (ReleaseState.RESEARCH, ReleaseState.VALIDATED),
        (ReleaseState.RESEARCH, ReleaseState.PAPER),
        (ReleaseState.CANDIDATE, ReleaseState.PAPER),
    ),
)
def test_p4_forged_skipped_transition_cannot_write_either_registry_table(
    lifecycle_store, prior_state, target
):
    store = lifecycle_store
    initial = synthetic_production()
    store.register_release(initial, now=NOW)
    chain = [initial]
    prior = initial
    if prior_state == ReleaseState.CANDIDATE:
        prior, _ = advance(store, prior, ReleaseState.CANDIDATE)
        chain.append(prior)
    instant = (prior.updated_at or prior.created_at) + timedelta(seconds=1)
    forged = Release.model_validate(prior.model_dump() | {"state": target, "updated_at": instant})
    transition = ReleaseTransition(
        release_id=prior.release_id,
        prior_hash=prior.content_hash(),
        next_hash=forged.content_hash(),
        from_state=prior.state,
        to_state=target,
        actor="synthetic.owner",
        actor_role="OWNER",
        recorded_at=instant,
        evidence_hash=forged.evidence_hash,
    )
    before = registry_rows(store, prior.release_id)
    with pytest.raises(ValueError):
        store.register_release(forged, transition=transition, now=instant)
    assert registry_rows(store, prior.release_id) == before
    assert_chain(store, chain)


def test_p4_transition_without_initial_research_cannot_create_history(lifecycle_store):
    store = lifecycle_store
    release = synthetic_production()
    candidate, transition = transition_release(
        release,
        ReleaseState.CANDIDATE,
        actor="synthetic.owner",
        actor_role="OWNER",
        approved_at=NOW,
        evidence_hash=HASH,
    )
    with pytest.raises(ValueError, match="RELEASE_TRANSITION_REQUIRES_HISTORY"):
        store.register_release(candidate, transition=transition, now=NOW)
    assert registry_rows(store, release.release_id) == ([], [])


@pytest.mark.parametrize("attack", ("stale", "duplicate", "cross_release"))
def test_p4_stale_duplicate_or_cross_identity_transition_is_refused(lifecycle_store, attack):
    store = lifecycle_store
    initial = synthetic_production()
    store.register_release(initial, now=NOW)
    candidate, event = advance(store, initial, ReleaseState.CANDIDATE)
    chain = [initial, candidate]
    if attack == "stale":
        candidate = Release.model_validate(candidate.model_dump() | {"evidence_hash": "2" * 64})
        event = ReleaseTransition.model_validate(
            event.model_dump() | {"next_hash": candidate.content_hash(), "evidence_hash": "2" * 64}
        )
    elif attack == "cross_release":
        other = synthetic_production()
        store.register_release(other, now=NOW)
        other_rows = registry_rows(store, other.release_id)
        candidate = Release.model_validate(
            candidate.model_dump() | {"release_id": other.release_id}
        )
    before = registry_rows(store, initial.release_id)
    with pytest.raises(ValueError):
        store.register_release(candidate, transition=event, now=event.recorded_at)
    assert registry_rows(store, initial.release_id) == before
    if attack == "cross_release":
        assert registry_rows(store, other.release_id) == other_rows
        assert_chain(store, [other])
    assert_chain(store, chain)


@pytest.mark.parametrize(
    "attack",
    (
        "code_hash",
        "config_hash",
        "data_hash",
        "evidence_hash",
        "prior_hash",
        "next_hash",
        "from_state",
        "to_state",
        "release_id",
        "recorded_at",
        "created_at",
    ),
)
def test_p4_transition_binds_exact_immutable_release_and_event_fields(lifecycle_store, attack):
    store = lifecycle_store
    initial = synthetic_production()
    store.register_release(initial, now=NOW)
    candidate, transition = transition_release(
        initial,
        ReleaseState.CANDIDATE,
        actor="synthetic.owner",
        actor_role="OWNER",
        approved_at=NOW + timedelta(seconds=1),
        evidence_hash=HASH,
    )
    if attack in ("code_hash", "config_hash", "evidence_hash", "created_at", "data_hash"):
        updates = {attack: "2" * 64}
        if attack == "created_at":
            updates[attack] = NOW - timedelta(seconds=1)
        elif attack == "data_hash":
            source = initial.data_eligibility.inputs[0]
            changed_source = SourceEligibility.model_validate(
                source.model_dump() | {"dataset_hash": "2" * 64}
            )
            eligibility = ReleaseDataEligibility(inputs=(changed_source,))
            updates = {"data_eligibility": eligibility, "data_hash": eligibility.content_hash()}
        candidate = Release.model_validate(candidate.model_dump() | updates)
        transition = ReleaseTransition.model_validate(
            transition.model_dump() | {"next_hash": candidate.content_hash()}
        )
    else:
        value = {
            "prior_hash": "2" * 64,
            "next_hash": "2" * 64,
            "from_state": ReleaseState.VALIDATED,
            "to_state": ReleaseState.PAPER,
            "release_id": "synthetic.other.identity",
            "recorded_at": NOW,
        }[attack]
        transition = ReleaseTransition.model_validate(transition.model_dump() | {attack: value})
    before = registry_rows(store, initial.release_id)
    with pytest.raises(ValueError):
        store.register_release(candidate, transition=transition, now=NOW + timedelta(seconds=1))
    assert registry_rows(store, initial.release_id) == before
    assert_chain(store, [initial])


def _lifecycle_worker(arguments):
    database, release, transition, barrier = arguments
    runtime = engine_for(database, "auvexo_paper")
    owner = engine_for(database, "auvexo_paper_owner")
    try:
        store = PaperStore(runtime, owner_engine=owner)
        barrier.wait(timeout=30)
        try:
            store.register_release(
                release, transition=transition, now=transition.recorded_at if transition else NOW
            )
        except ValueError as exc:
            return str(exc)
        return "APPLIED"
    finally:
        runtime.dispose()
        owner.dispose()


@pytest.mark.parametrize("pool_type", (ThreadPoolExecutor, ProcessPoolExecutor))
@pytest.mark.parametrize("operation", ("initial", "transition"))
def test_p4_concurrent_registration_or_transition_commits_once(
    lifecycle_database, lifecycle_store, pool_type, operation
):
    store = lifecycle_store
    initial = synthetic_production()
    release, transition = initial, None
    chain = [initial]
    if operation == "transition":
        store.register_release(initial, now=NOW)
        release, transition = transition_release(
            initial,
            ReleaseState.CANDIDATE,
            actor="synthetic.owner",
            actor_role="OWNER",
            approved_at=NOW + timedelta(seconds=1),
            evidence_hash=HASH,
        )
        chain.append(release)
    context = get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(4)
        arguments = [(lifecycle_database, release, transition, barrier)] * 4
        options = {"mp_context": context} if pool_type is ProcessPoolExecutor else {}
        with pool_type(max_workers=4, **options) as pool:
            outcomes = list(pool.map(_lifecycle_worker, arguments))
    refusal = (
        "RELEASE_IDENTITY_ALREADY_REGISTERED"
        if operation == "initial"
        else "RELEASE_CURRENT_STATE_MISMATCH"
    )
    assert outcomes.count("APPLIED") == 1
    assert outcomes.count(refusal) == 3
    assert_chain(store, chain)


@pytest.mark.parametrize("boundary", ("snapshot", "history"))
@pytest.mark.parametrize("operation", ("initial", "transition"))
def test_p4_lifecycle_write_failure_rolls_back_history_and_current_projection(
    lifecycle_store, boundary, operation
):
    store = lifecycle_store
    initial = synthetic_production()
    release, transition = initial, None
    chain = []
    if operation == "transition":
        store.register_release(initial, now=NOW)
        chain.append(initial)
        release, transition = transition_release(
            initial,
            ReleaseState.CANDIDATE,
            actor="synthetic.owner",
            actor_role="OWNER",
            approved_at=NOW + timedelta(seconds=1),
            evidence_hash=HASH,
        )
    before = registry_rows(store, initial.release_id)
    table = "paper_production_release" if boundary == "snapshot" else "paper_production_lifecycle"

    def fail_after_write(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO " + table):
            raise psycopg.errors.DiskFull("SYNTHETIC_LIFECYCLE_COMMIT_FAILURE")

    event.listen(store.owner_engine, "after_cursor_execute", fail_after_write)
    try:
        with pytest.raises(DBAPIError) as refusal:
            store.register_release(
                release, transition=transition, now=transition.recorded_at if transition else NOW
            )
        assert isinstance(refusal.value.orig, psycopg.errors.DiskFull)
        assert str(refusal.value.orig) == "SYNTHETIC_LIFECYCLE_COMMIT_FAILURE"
    finally:
        event.remove(store.owner_engine, "after_cursor_execute", fail_after_write)
    assert registry_rows(store, initial.release_id) == before
    if chain:
        assert_chain(store, chain)
    else:
        with pytest.raises(ValueError, match="UNKNOWN_RELEASE_IDENTITY"):
            store.current_release(initial.release_id)
    store.register_release(
        release, transition=transition, now=transition.recorded_at if transition else NOW
    )
    assert_chain(store, chain + [release])


def test_p4_early_suspension_cannot_skip_required_paper_history(lifecycle_store):
    store = lifecycle_store
    initial = synthetic_production()
    store.register_release(initial, now=NOW)
    suspended, _ = advance(store, initial, ReleaseState.SUSPENDED)
    resumed, transition = transition_release(
        suspended,
        ReleaseState.PAPER,
        actor="synthetic.owner",
        actor_role="OWNER",
        approved_at=NOW + timedelta(seconds=2),
        evidence_hash=HASH,
    )
    before = registry_rows(store, initial.release_id)
    with pytest.raises(ValueError):
        store.register_release(resumed, transition=transition, now=transition.recorded_at)
    assert registry_rows(store, initial.release_id) == before
    assert_chain(store, [initial, suspended])


def test_p4_paper_suspension_needs_explicit_owner_resume_and_retirement_is_terminal(
    lifecycle_store,
):
    store = lifecycle_store
    release = synthetic_production()
    store.register_release(release, now=NOW)
    chain = [release]
    for state in (ReleaseState.CANDIDATE, ReleaseState.VALIDATED, ReleaseState.PAPER):
        release, _ = advance(store, release, state)
        chain.append(release)
    suspended, _ = advance(store, release, ReleaseState.SUSPENDED)
    chain.append(suspended)
    before = registry_rows(store, release.release_id)
    with pytest.raises(ValueError, match="EXPLICIT_PAPER_REQUALIFICATION_REQUIRED"):
        transition_release(
            suspended,
            ReleaseState.PAPER,
            actor="synthetic.independent.reviewer",
            actor_role="INDEPENDENT_REVIEWER",
            approved_at=NOW + timedelta(seconds=5),
            evidence_hash=HASH,
        )
    with pytest.raises(ValueError):
        store.register_release(release, now=NOW + timedelta(seconds=5))
    assert registry_rows(store, release.release_id) == before
    resumed, _ = advance(store, suspended, ReleaseState.PAPER)
    chain.append(resumed)
    retired, _ = advance(store, resumed, ReleaseState.RETIRED)
    chain.append(retired)
    assert_chain(store, chain)
    forged = ReleaseTransition(
        release_id=retired.release_id,
        prior_hash=retired.content_hash(),
        next_hash=resumed.content_hash(),
        from_state=ReleaseState.RETIRED,
        to_state=ReleaseState.PAPER,
        actor="synthetic.owner",
        actor_role="OWNER",
        recorded_at=NOW + timedelta(seconds=10),
        evidence_hash=HASH,
    )
    before = registry_rows(store, retired.release_id)
    with pytest.raises(ValueError):
        store.register_release(resumed, transition=forged, now=forged.recorded_at)
    assert registry_rows(store, retired.release_id) == before
    assert_chain(store, chain)


def test_p4_fixture_paper_remains_physically_separate_and_cannot_seed_production(lifecycle_store):
    store = lifecycle_store
    fixture = fixture_bundle().release
    fixture = Release.model_validate(
        fixture.model_dump() | {"release_id": "synthetic.fixture." + uuid4().hex}
    )
    store.register_release(fixture, fixture_registry=True, now=NOW)
    assert_chain(store, [fixture], fixture=True)
    assert registry_rows(store, fixture.release_id) == ([], [])
    with pytest.raises(ValueError, match="WRONG_RELEASE_REGISTRY"):
        store.register_release(fixture, fixture_registry=False, now=NOW)
    hypothetical = synthetic_production()
    copied = Release.model_validate(
        hypothetical.model_dump() | {"release_id": fixture.release_id, "state": ReleaseState.PAPER}
    )
    with pytest.raises(ValueError, match="INITIAL_PRODUCTION_RESEARCH_REQUIRED"):
        store.register_release(copied, now=NOW)
    event = ReleaseTransition(
        release_id=copied.release_id,
        prior_hash=fixture.content_hash(),
        next_hash=copied.content_hash(),
        from_state=ReleaseState.VALIDATED,
        to_state=ReleaseState.PAPER,
        actor="synthetic.owner",
        actor_role="OWNER",
        recorded_at=NOW,
        evidence_hash=HASH,
    )
    with pytest.raises(ValueError, match="RELEASE_TRANSITION_REQUIRES_HISTORY"):
        store.register_release(copied, transition=event, now=NOW)
    assert registry_rows(store, fixture.release_id) == ([], [])
    assert_chain(store, [fixture], fixture=True)


@pytest.mark.parametrize("corruption", ("orphan_snapshot", "duplicate_history", "forked_history"))
def test_p4_inconsistent_durable_history_cannot_produce_usable_current_release(
    lifecycle_store, corruption
):
    store = lifecycle_store
    initial = synthetic_production()
    store.register_release(initial, now=NOW)
    candidate, transition = transition_release(
        initial,
        ReleaseState.CANDIDATE,
        actor="synthetic.owner",
        actor_role="OWNER",
        approved_at=NOW + timedelta(seconds=1),
        evidence_hash=HASH,
    )
    if corruption == "forked_history":
        store.register_release(candidate, transition=transition, now=transition.recorded_at)
        candidate, transition = transition_release(
            initial,
            ReleaseState.CANDIDATE,
            actor="synthetic.owner",
            actor_role="OWNER",
            approved_at=NOW + timedelta(seconds=2),
            evidence_hash="2" * 64,
        )
    # Deliberate privileged corruption is isolated to this unique synthetic identity.
    # Append-only triggers remain enabled; readers must still refuse incomplete/forked state.
    with store.owner_engine.begin() as conn:
        if corruption == "duplicate_history":
            conn.execute(
                text(
                    "INSERT INTO paper_production_lifecycle"
                    "(release_hash,payload,content_hash,recorded_at) "
                    "SELECT release_hash,payload,content_hash,recorded_at "
                    "FROM paper_production_lifecycle WHERE release_hash=:hash"
                ),
                {"hash": initial.content_hash()},
            )
        else:
            conn.execute(
                text("INSERT INTO paper_production_release VALUES (:hash,:payload,:now)"),
                {
                    "hash": candidate.content_hash(),
                    "payload": candidate.canonical_bytes().decode(),
                    "now": transition.recorded_at,
                },
            )
            if corruption == "forked_history":
                payload = transition.canonical_bytes().decode()
                conn.execute(
                    text(
                        "INSERT INTO paper_production_lifecycle"
                        "(release_hash,payload,content_hash,recorded_at) "
                        "VALUES (:release,:payload,:hash,:now)"
                    ),
                    {
                        "release": candidate.content_hash(),
                        "payload": payload,
                        "hash": sha256(payload.encode()).hexdigest(),
                        "now": transition.recorded_at,
                    },
                )
    before = registry_rows(store, initial.release_id)
    with pytest.raises(ValueError, match="CORRUPT_PRODUCTION_RELEASE_HISTORY"):
        store.current_release(initial.release_id)
    with pytest.raises(ValueError, match="CORRUPT_PRODUCTION_RELEASE_HISTORY"):
        store.register_release(candidate, transition=transition, now=transition.recorded_at)
    assert registry_rows(store, initial.release_id) == before
