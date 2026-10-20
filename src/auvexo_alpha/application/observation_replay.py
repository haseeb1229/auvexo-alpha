"""Deterministic replay of immutable observation inputs; no live acquisition."""

from collections.abc import Sequence

from auvexo_alpha.domain.observation import (
    ObservationConfig,
    ObservationFact,
    ObservationProposalTrace,
    observation_market,
    observation_policy,
)
from auvexo_alpha.domain.paper import PaperDecision
from auvexo_alpha.domain.paper_risk import assess_paper, verify_authorization


def replay_observation_traces(
    config: ObservationConfig,
    facts: Sequence[ObservationFact],
    traces: Sequence[ObservationProposalTrace],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Reproduce exact decision hashes, refusing incomplete or altered evidence."""
    by_hash = {fact.content_hash(): fact for fact in facts}
    if len(by_hash) != len(facts):
        raise ValueError("OBSERVATION_REPLAY_DUPLICATE_SOURCE")
    intents: list[str] = []
    decisions: list[str] = []
    policy = observation_policy(config)
    for trace in traces:
        fact = by_hash.get(trace.source_observation_hash)
        if (
            fact is None
            or trace.market != observation_market(fact)
            or trace.spec not in config.specs
            or trace.intent.instrument_id != fact.candle.instrument_id
            or trace.intent.account_ref != config.account_ref
            or trace.account_before.account_ref != config.account_ref
            or trace.release.config_hash != config.content_hash()
            or trace.decision.decision_at < fact.candle.availability.available_at
        ):
            raise ValueError("OBSERVATION_REPLAY_BINDING_MISMATCH")
        replayed = assess_paper(
            trace.intent,
            policy,
            trace.market,
            trace.spec,
            trace.account_before,
            trace.release,
            trace.prior_reservations,
            now=trace.decision.decision_at,
        )
        if replayed.status == "DENIED":
            replayed = PaperDecision.model_validate(replayed.model_dump() | {"exposure": None})
        if replayed.content_hash() != trace.decision.content_hash():
            raise ValueError("OBSERVATION_REPLAY_DECISION_MISMATCH")
        if trace.authorization is not None:
            if trace.reservation is None or not verify_authorization(
                trace.authorization,
                trace.intent,
                policy,
                trace.market,
                trace.spec,
                trace.account_before,
                trace.release,
                trace.reservation,
                now=trace.decision.decision_at,
                reservations=trace.prior_reservations,
            ):
                raise ValueError("OBSERVATION_REPLAY_AUTHORIZATION_MISMATCH")
        elif trace.reservation is not None or trace.decision.status == "APPROVED":
            raise ValueError("OBSERVATION_REPLAY_AUTHORIZATION_MISSING")
        intents.append(trace.intent.content_hash())
        decisions.append(replayed.content_hash())
    return tuple(intents), tuple(decisions)
