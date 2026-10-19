"""No research promotion or alpha claim can be manufactured from PAPER fixtures."""

from datetime import timedelta
from typing import Literal, cast

import pytest
from paper_fixtures import HASH, fixture_bundle, research_release
from pydantic import ValidationError

from auvexo_alpha.domain.contracts import Mode
from auvexo_alpha.domain.paper_lifecycle import (
    EdgeState,
    EdgeTransition,
    Release,
    ReleaseState,
    SourceEligibility,
    fixture_edge_transition,
    transition_release,
    validate_initial_release,
    validate_registry_release,
    validate_release_transition,
)
from auvexo_alpha.domain.research import DataUseClass


@pytest.mark.parametrize("mode", [mode for mode in Mode if mode != Mode.PAPER])
def test_p4_fixture_all_nonpaper_modes_refused(mode: Mode) -> None:
    release = fixture_bundle().release
    payload = release.model_dump()
    payload["allowed_modes"] = (mode,)
    with pytest.raises(ValidationError, match="TEST_ONLY_ISOLATION"):
        Release.model_validate(payload)


@pytest.mark.parametrize(
    "target",
    [
        ReleaseState.RESEARCH,
        ReleaseState.CANDIDATE,
        ReleaseState.VALIDATED,
        ReleaseState.SHADOW,
        ReleaseState.LIVE_LIMITED,
        ReleaseState.LIVE,
    ],
)
def test_p4_fixture_cannot_promote_or_change_kind(target: ReleaseState) -> None:
    b = fixture_bundle()
    with pytest.raises(ValueError):
        transition_release(
            b.release,
            target,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now,
            evidence_hash=HASH,
        )
    payload = b.release.model_dump()
    payload["state"] = target
    with pytest.raises(ValidationError):
        Release.model_validate(payload)


def test_p4_physical_fixture_registry_boundary_and_immutability() -> None:
    b = fixture_bundle()
    validate_registry_release(b.release, fixture_registry=True)
    with pytest.raises(ValueError, match="WRONG_RELEASE_REGISTRY"):
        validate_registry_release(b.release, fixture_registry=False)
    with pytest.raises(ValidationError):
        b.release.state = ReleaseState.LIVE
    # A construct/copy bypass is revalidated by registry and transition boundaries.
    forged = b.release.model_copy(update={"allowed_modes": (Mode.LIVE,)})
    with pytest.raises(ValueError):
        validate_registry_release(forged, fixture_registry=True)


def test_p4_suspend_resume_appends_hash_bound_owner_history() -> None:
    b = fixture_bundle()
    original_hash = b.release.content_hash()
    suspended, event = transition_release(
        b.release,
        ReleaseState.SUSPENDED,
        actor="owner",
        actor_role="OWNER",
        approved_at=b.now,
        evidence_hash="2" * 64,
    )
    assert b.release.content_hash() == original_hash
    assert event.prior_hash == original_hash
    assert event.next_hash == suspended.content_hash()
    assert suspended.state == ReleaseState.SUSPENDED
    with pytest.raises(ValueError, match="REQUALIFICATION"):
        transition_release(
            suspended,
            ReleaseState.PAPER,
            actor="reviewer",
            actor_role="INDEPENDENT_REVIEWER",
            approved_at=b.now,
            evidence_hash=HASH,
        )
    resumed, resume = transition_release(
        suspended,
        ReleaseState.PAPER,
        actor="owner",
        actor_role="OWNER",
        approved_at=b.now + timedelta(seconds=1),
        evidence_hash=HASH,
    )
    assert resumed.state == ReleaseState.PAPER
    assert resume.prior_hash == suspended.content_hash()
    retired, _ = transition_release(
        resumed,
        ReleaseState.RETIRED,
        actor="owner",
        actor_role="OWNER",
        approved_at=b.now + timedelta(seconds=2),
        evidence_hash=HASH,
    )
    with pytest.raises(ValueError):
        transition_release(
            retired,
            ReleaseState.PAPER,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now + timedelta(seconds=3),
            evidence_hash=HASH,
        )


def test_p4_real_research_requires_eligible_evidence_and_no_skipped_states() -> None:
    b = fixture_bundle()
    ineligible = research_release(eligible=False)
    with pytest.raises(ValueError, match="INDEPENDENT_ELIGIBLE"):
        transition_release(
            ineligible,
            ReleaseState.CANDIDATE,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now,
            evidence_hash=HASH,
        )
    release = research_release(eligible=True)
    validate_registry_release(release, fixture_registry=False)
    with pytest.raises(ValueError, match="WRONG_RELEASE_REGISTRY"):
        validate_registry_release(release, fixture_registry=True)
    with pytest.raises(ValueError, match="CANNOT_SKIP"):
        transition_release(
            release,
            ReleaseState.VALIDATED,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now,
            evidence_hash=HASH,
        )
    for state in (
        ReleaseState.CANDIDATE,
        ReleaseState.VALIDATED,
        ReleaseState.PAPER,
        ReleaseState.SHADOW,
        ReleaseState.LIVE_LIMITED,
        ReleaseState.LIVE,
    ):
        release, history = transition_release(
            release, state, actor="owner", actor_role="OWNER", approved_at=b.now, evidence_hash=HASH
        )
        assert history.to_state == state
    # Metadata labels are permitted design; no transport/permit is created here.
    assert release.allowed_modes == (Mode.PAPER,)


def test_p4_source_specific_eligibility_cannot_be_invented_or_expired() -> None:
    b = fixture_bundle()
    release = research_release(eligible=True)
    assert release.data_eligibility is not None
    source = release.data_eligibility.inputs[0]
    for source_id in ("DS-01", "DS-02"):
        with pytest.raises(ValidationError, match="RESTRICTED_SOURCE"):
            SourceEligibility.model_validate(source.model_dump() | {"source_id": source_id})
    with pytest.raises(ValueError, match="ELIGIBLE"):
        transition_release(
            release.model_copy(update={"data_eligibility": None}),
            ReleaseState.CANDIDATE,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now,
            evidence_hash=HASH,
        )
    with pytest.raises(ValueError, match="EXPIRED"):
        transition_release(
            release,
            ReleaseState.CANDIDATE,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now + timedelta(days=2),
            evidence_hash=HASH,
        )
    restricted = SourceEligibility.model_validate(
        source.model_dump() | {"classification": DataUseClass.PERSONAL_RESEARCH}
    )
    with pytest.raises(ValidationError, match="RESTRICTED_SOURCE"):
        SourceEligibility.model_validate(source.model_dump() | {"parents": (restricted,)})


@pytest.mark.parametrize("bad_role", ["AGENT", "MODEL", "SYSTEM"])
def test_p4_agent_cannot_promote_even_eligible_evidence(bad_role: str) -> None:
    b = fixture_bundle()
    with pytest.raises(ValueError, match="AGENT_PROMOTION"):
        transition_release(
            research_release(eligible=True),
            ReleaseState.CANDIDATE,
            actor="untrusted",
            actor_role=cast(Literal["OWNER", "INDEPENDENT_REVIEWER"], bad_role),
            approved_at=b.now,
            evidence_hash=HASH,
        )


@pytest.mark.parametrize("state", list(EdgeState))
def test_p4_versioned_fixture_edge_state_plumbing(state: EdgeState) -> None:
    b = fixture_bundle()
    prior = EdgeState.WATCH if state == EdgeState.NORMAL else EdgeState.NORMAL
    event = EdgeTransition(
        release_hash=b.release.content_hash(),
        from_state=prior,
        to_state=state,
        fixture_version="edge.fixture.v1",
        evidence_hash=HASH,
        recorded_at=b.now,
        actor="owner",
        actor_role="OWNER",
    )
    assert fixture_edge_transition(b.release, event) == state


@pytest.mark.parametrize("role", ["SYSTEM", "AGENT"])
def test_p4_edge_suspend_never_auto_resumes(role: Literal["SYSTEM", "AGENT"]) -> None:
    b = fixture_bundle()
    event = EdgeTransition(
        release_hash=b.release.content_hash(),
        from_state=EdgeState.SUSPEND,
        to_state=EdgeState.NORMAL,
        fixture_version="edge.fixture.v1",
        evidence_hash=HASH,
        recorded_at=b.now,
        actor="untrusted",
        actor_role=role,
    )
    with pytest.raises(ValueError):
        fixture_edge_transition(b.release, event)


def test_p4_no_edge_alpha_threshold_on_research_metadata() -> None:
    b = fixture_bundle()
    research = research_release(eligible=True)
    event = EdgeTransition(
        release_hash=research.content_hash(),
        from_state=EdgeState.NORMAL,
        to_state=EdgeState.WATCH,
        fixture_version="edge.fixture.v1",
        evidence_hash=HASH,
        recorded_at=b.now,
        actor="owner",
        actor_role="OWNER",
    )
    with pytest.raises(ValueError, match="VERSIONED_TEST_EDGE"):
        fixture_edge_transition(research, event)


def test_p4_release_transition_time_cannot_rewind() -> None:
    b = fixture_bundle()
    suspended, _ = transition_release(
        b.release,
        ReleaseState.SUSPENDED,
        actor="owner",
        actor_role="OWNER",
        approved_at=b.now + timedelta(seconds=2),
        evidence_hash=HASH,
    )
    with pytest.raises(ValueError, match="TIME_REVERSED"):
        transition_release(
            suspended,
            ReleaseState.PAPER,
            actor="owner",
            actor_role="OWNER",
            approved_at=b.now + timedelta(seconds=1),
            evidence_hash=HASH,
        )


def test_p4_any_edge_resume_needs_owner_and_copy_bypass_is_validated() -> None:
    b = fixture_bundle()
    event = EdgeTransition(
        release_hash=b.release.content_hash(),
        from_state=EdgeState.WATCH,
        to_state=EdgeState.NORMAL,
        fixture_version="edge.fixture.v1",
        evidence_hash=HASH,
        recorded_at=b.now,
        actor="system",
        actor_role="SYSTEM",
    )
    with pytest.raises(ValueError, match="OWNER_RESUME"):
        fixture_edge_transition(b.release, event)
    forged = event.model_copy(update={"actor_role": "MODEL"})
    with pytest.raises(ValueError):
        fixture_edge_transition(b.release, forged)


@pytest.mark.parametrize("state", list(ReleaseState))
def test_p4_initial_production_domain_boundary_requires_first_research(state: ReleaseState) -> None:
    release = research_release(eligible=True)
    release = Release.model_validate(release.model_dump() | {"state": state})
    if state == ReleaseState.RESEARCH:
        validate_initial_release(release, fixture_registry=False)
    else:
        with pytest.raises(ValueError, match="INITIAL_PRODUCTION_RESEARCH_REQUIRED"):
            validate_initial_release(release, fixture_registry=False)


def test_p4_initial_registration_domain_boundary_rejects_transition_snapshot() -> None:
    b = fixture_bundle()
    release = research_release(eligible=True)
    changed = Release.model_validate(release.model_dump() | {"updated_at": b.now})
    with pytest.raises(ValueError, match="INITIAL_PRODUCTION_RESEARCH_REQUIRED"):
        validate_initial_release(changed, fixture_registry=False)
    validate_initial_release(b.release, fixture_registry=True)
    with pytest.raises(ValueError, match="WRONG_RELEASE_REGISTRY"):
        validate_initial_release(b.release, fixture_registry=False)


def test_p4_transition_domain_boundary_validates_all_fields_and_copy_bypass() -> None:
    b = fixture_bundle()
    prior = research_release(eligible=True)
    candidate, transition = transition_release(
        prior,
        ReleaseState.CANDIDATE,
        actor="owner",
        actor_role="OWNER",
        approved_at=b.now,
        evidence_hash=HASH,
    )
    validate_release_transition(prior, candidate, transition)
    forged = transition.model_copy(update={"actor_role": "AGENT"})
    with pytest.raises(ValueError):
        validate_release_transition(prior, candidate, forged)
    changed = Release.model_validate(candidate.model_dump() | {"config_hash": "2" * 64})
    changed_event = transition.model_copy(update={"next_hash": changed.content_hash()})
    with pytest.raises(ValueError, match="RELEASE_HISTORY_BINDING_DENIED"):
        validate_release_transition(prior, changed, changed_event)
