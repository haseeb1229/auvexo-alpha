"""Independent PAPER ledger replay (P-13/OBV2-11).

The verified journal and truth facts are replayed into account state without using the
store's reconciliation code or its stored projection, and compared field by field: each
journaled transition against the change its kind permits, each reconciliation's balances
against an independent fold of the truth facts it consumed, and the stored account against
the replayed final state. A differing field is counted, not raised; the caller has already
verified both hash chains, so only a structurally corrupt fact can raise.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Any, NamedTuple

from pydantic import ValidationError

from auvexo_alpha.domain.contracts import MoneyAction, exact_decimal
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPosition,
    paper_position_ref,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel

_ZERO = Decimal("0")
_PLACES = Decimal("0.000000000000000001")
# Re-derived from paper_intent on every read; never part of the compared state.
_DERIVED = frozenset({"prior_logical_keys", "prior_intent_ids", "recent_intent_times"})


@dataclass(frozen=True)
class PaperLedgerReplay:
    account_ref: str
    journal_events: int
    truth_events: int
    mismatches: tuple[str, ...]

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)


class _Mark(NamedTuple):
    price: Decimal
    adverse_fx: Decimal
    observed_at: datetime
    available_at: datetime
    fx_as_of: datetime
    snapshot_hash: str | None
    fact_hash: str | None


@dataclass(frozen=True)
class _Order:
    intent: PaperIntent
    authorization: PaperAuthorization
    spec: PaperInstrumentSpec
    market: PaperMarketSnapshot


def _floor(value: Decimal) -> Decimal:
    return value.quantize(_PLACES, rounding=ROUND_FLOOR)


def _ceil(value: Decimal) -> Decimal:
    return value.quantize(_PLACES, rounding=ROUND_CEILING)


def _parse[T: (PaperAccountSnapshot, PaperPosition, PaperMarketSnapshot)](
    model: type[T], data: object
) -> T:
    return model.model_validate_json(json.dumps(data))


def _midnight(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _fields(account: PaperAccountSnapshot) -> dict[str, Any]:
    dumped = json.loads(account.canonical_bytes())
    return {key: value for key, value in dumped.items() if key not in _DERIVED}


class _Ledger:
    """Truth facts folded in sequence; formulas restated from ADR-021 PAPER accounting."""

    def __init__(
        self, account_ref: str, baseline: PaperAccountSnapshot, orders: Mapping[str, _Order]
    ) -> None:
        self.account_ref, self.baseline, self.orders = account_ref, baseline, orders
        self.positions = {p.position_ref: p for p in baseline.positions}
        self.position_marks: dict[str, _Mark] = {}
        for p in baseline.positions:
            if p.mark_as_of is not None and p.fx_as_of is not None:
                self.position_marks[p.position_ref] = _Mark(
                    p.mark_price,
                    p.adverse_fx,
                    p.mark_as_of,
                    p.mark_available_at or p.mark_as_of,
                    p.fx_as_of,
                    p.mark_snapshot_hash,
                    p.mark_fact_hash,
                )
        self.marks: dict[str, _Mark] = {}
        self.cash = baseline.cash
        self.flows: list[tuple[datetime, Decimal]] = []
        self.position = 0

    def advance(self, truth: Sequence[dict[str, Any]], cursor: int, skip: set[str]) -> None:
        while self.position < len(truth) and int(truth[self.position]["sequence"]) <= cursor:
            event = truth[self.position]
            self.position += 1
            if event["content_hash"] not in skip:
                self._apply(event)

    def _apply(self, event: dict[str, Any]) -> None:
        data = event["data"]
        if event["kind"] == "FILL":
            self._fill(self.orders[str(event["intent_hash"])], data)
        elif event["kind"] == "EXTERNAL_POSITION":
            p = _parse(PaperPosition, data)
            self.positions[p.position_ref] = p
            if p.mark_as_of is not None and p.fx_as_of is not None:
                candidate = _Mark(
                    p.mark_price,
                    p.adverse_fx,
                    p.mark_as_of,
                    p.mark_available_at or event["recorded_at"],
                    p.fx_as_of,
                    p.content_hash(),
                    str(event["content_hash"]),
                )
                previous = self.position_marks.get(p.position_ref)
                if previous is None or candidate.observed_at > previous.observed_at:
                    self.position_marks[p.position_ref] = candidate
        elif event["kind"] == "ADJUSTMENT":
            amount = exact_decimal(data["amount"])
            self.cash += amount
            self.flows.append((event["recorded_at"], amount))
        elif event["kind"] == "MARKET_MARK":
            m = _parse(PaperMarketSnapshot, data)
            if m.adverse_fx is None or m.fx_as_of is None:
                return
            previous = self.marks.get(m.instrument_id)
            if previous is None or m.as_of > previous.observed_at:
                self.marks[m.instrument_id] = _Mark(
                    m.bid,
                    m.adverse_fx,
                    m.as_of,
                    m.available_at,
                    m.fx_as_of,
                    m.content_hash(),
                    str(event["content_hash"]),
                )

    def _fill(self, order: _Order, data: Mapping[str, Any]) -> None:
        intent, exposure = order.intent, order.authorization.exposure
        q, price = exact_decimal(data["quantity"]), exact_decimal(data["price"])
        fx = order.market.adverse_fx or _ZERO
        multiplier = order.spec.contract_multiplier
        total = exposure.quantity
        stop_loss = total * multiplier * abs(intent.entry - intent.stop) * fx
        costs = (
            exposure.modeled_loss
            if intent.action == MoneyAction.CLOSE
            else max(_ZERO, exposure.modeled_loss - stop_loss)
        )
        fee = _ceil(costs * q / total)
        value = q * price * multiplier * fx
        if intent.action == MoneyAction.OPEN:
            ref = paper_position_ref(self.account_ref, intent.intent_id)
            old = self.positions.get(ref)
            held = old.quantity if old else _ZERO
            quantity = held + q
            self.positions[ref] = PaperPosition(
                position_ref=ref,
                instrument_id=intent.instrument_id,
                bucket=exposure.bucket,
                quantity=quantity,
                entry_price=_ceil(
                    (q * price + (held * old.entry_price if old else _ZERO)) / quantity
                ),
                mark_price=price,
                stop_price=intent.stop,
                multiplier=multiplier,
                adverse_fx=fx,
                modeled_costs=_ceil((old.modeled_costs if old else _ZERO) + fee),
                margin_used=_ceil(
                    (old.margin_used if old else _ZERO) + exposure.margin_required * q / total
                ),
            )
            self.cash = _floor(self.cash - value - fee)
            return
        ref = str(intent.position_ref)
        old = self.positions[ref]
        remaining = old.quantity - q
        if remaining:
            self.positions[ref] = old.model_copy(
                update={
                    "quantity": remaining,
                    "margin_used": _ceil(old.margin_used * remaining / old.quantity),
                    "modeled_costs": _ceil(old.modeled_costs * remaining / old.quantity),
                }
            )
        else:
            del self.positions[ref]
        self.cash = _floor(self.cash + value - fee)

    def balances(self, prior: PaperAccountSnapshot) -> dict[str, Any]:
        positions = []
        for ref in sorted(self.positions):
            p = self.positions[ref]
            mark = self.marks.get(p.instrument_id)
            own = self.position_marks.get(ref)
            if own is not None and (mark is None or own.observed_at > mark.observed_at):
                mark = own
            if mark is not None:
                p = p.model_copy(
                    update={
                        "mark_price": mark.price,
                        "adverse_fx": mark.adverse_fx,
                        "mark_as_of": mark.observed_at,
                        "mark_available_at": mark.available_at,
                        "fx_as_of": mark.fx_as_of,
                        "mark_snapshot_hash": mark.snapshot_hash,
                        "mark_fact_hash": mark.fact_hash,
                    }
                )
            positions.append(p)
        equity = _floor(
            self.cash
            + sum(
                (p.quantity * p.mark_price * p.multiplier * p.adverse_fx for p in positions), _ZERO
            )
        )
        total_flows = self.baseline.net_flows_since_high_water + sum(
            (amount for _, amount in self.flows), _ZERO
        )
        day_flows = (
            self.baseline.day_net_flows
            if self.baseline.day_start_at == prior.day_start_at
            else _ZERO
        ) + sum((amount for at, amount in self.flows if at >= prior.day_start_at), _ZERO)
        return {
            "cash": self.cash,
            "equity": equity,
            "high_water_equity": max(prior.high_water_equity, equity - total_flows),
            "day_net_flows": day_flows,
            "net_flows_since_high_water": total_flows,
            "positions": tuple(positions),
        }


def _expected(
    kind: str,
    prior: PaperAccountSnapshot,
    event: PaperAccountSnapshot,
    recorded_at: datetime,
    latched: KillLevel,
) -> dict[str, Any]:
    """The fields a journal kind may set; every field not named here must equal `prior`."""
    raised = max(prior.kill, latched)
    if kind == "WRITER_ACQUIRED_PAUSE_NEW":
        return {"epoch": prior.epoch + 1, "kill": max(raised, KillLevel.K1), "reconciled": False}
    if kind == "KILL_STATE":
        return {
            "kill": max(raised, event.kill),
            "reconciled": prior.reconciled and event.reconciled,
        }
    if kind == "UNKNOWN_RECONCILE_ONLY":
        return {"kill": max(raised, KillLevel.K1), "reconciled": False, "unknown_orders": True}
    if kind == "OWNER_PAPER_RESUME":
        return {"kill": KillLevel.K0}
    if kind in ("OWNER_RELEASE_PIN", "OWNER_POLICY_PIN"):
        return {"kill": max(raised, KillLevel.K1), "reconciled": False}
    if kind in ("UTC_DAY_ROLLOVER", "FLAT_BOUNDARY_ROLL"):
        rolled: dict[str, Any] = {
            "kill": raised,
            "day_start_at": _midnight(recorded_at),
            "day_start_equity": prior.equity,
            "day_net_flows": _ZERO,
        }
        if kind == "UTC_DAY_ROLLOVER":
            rolled["as_of"] = recorded_at.astimezone(UTC)
        return rolled
    raise ValueError("UNREPLAYABLE_PROJECTION_KIND")


def _compare(
    label: str, expected: Mapping[str, Any], actual: Mapping[str, Any], out: list[str]
) -> None:
    for key in sorted(set(expected) | set(actual)):
        if expected.get(key) != actual.get(key):
            out.append(f"{label}.{key}")


def replay_ledger(
    account_ref: str,
    journal: Sequence[dict[str, Any]],
    truth: Sequence[dict[str, Any]],
    *,
    stored_payload: str,
    stored_columns: Mapping[str, object],
) -> PaperLedgerReplay:
    with localcontext() as context:
        context.prec = 100
        mismatches = _replay(account_ref, journal, truth, stored_payload, stored_columns)
    return PaperLedgerReplay(account_ref, len(journal), len(truth), tuple(mismatches))


def _replay(
    account_ref: str,
    journal: Sequence[dict[str, Any]],
    truth: Sequence[dict[str, Any]],
    stored_payload: str,
    stored_columns: Mapping[str, object],
) -> list[str]:
    out: list[str] = []
    if not journal or journal[0]["kind"] != "INITIALIZED":
        return ["journal.initialized"]
    state = _parse(PaperAccountSnapshot, journal[0]["data"]["account"])
    orders = {
        str(e["intent_hash"]): _Order(
            PaperIntent.model_validate_json(json.dumps(e["data"]["intent"])),
            PaperAuthorization.model_validate_json(json.dumps(e["data"]["authorization"])),
            PaperInstrumentSpec.model_validate_json(json.dumps(e["data"]["spec"])),
            _parse(PaperMarketSnapshot, e["data"]["market"]),
        )
        for e in journal
        if e["kind"] == "AUTHORIZED"
    }
    ledger = _Ledger(account_ref, state, orders)
    skip: set[str] = set()
    cursor = 0
    latched = KillLevel.K0
    for event in journal[1:]:
        kind, label = event["kind"], f"journal.{event['sequence']}.{event['kind']}"
        if kind == "TRUTH_QUARANTINE":
            skip.add(str(event["data"]["truth_content_hash"]))
            continue
        if kind == "LOSS_BREACH_LATCH":
            # A latch annotates the transition that follows in the same transaction.
            if _parse(PaperAccountSnapshot, event["data"]["account"]).kill < KillLevel.K2:
                out.append(label + ".kill")
            latched = KillLevel.K2
            continue
        if "account" not in event["data"] or kind not in _PROJECTIONS:
            continue
        journaled = _parse(PaperAccountSnapshot, event["data"]["account"])
        expected = _fields(state)
        actual = _fields(journaled)
        if kind == "RECONCILIATION":
            cursor = int(event["data"]["truth_cursor"])
            ledger.advance(truth, cursor, skip)
            recomputed = PaperAccountSnapshot.model_validate(
                state.model_dump() | ledger.balances(state)
            )
            expected = _fields(recomputed)
            # Evaluation time, health flags and kill are journaled outcomes; they are
            # checked against their rules rather than recomputed.
            for key in ("snapshot_id", "reconciled", "unknown_orders"):
                expected[key] = actual[key]
            for key in ("as_of", "reconciled_at"):
                if actual[key] in (expected[key], _canonical_time(event["recorded_at"])):
                    expected[key] = actual[key]
            expected["kill"] = max(max(state.kill, latched), journaled.kill).value
            if journaled.reconciled and journaled.unknown_orders:
                out.append(label + ".reconciled")
        else:
            changes = _expected(kind, state, journaled, event["recorded_at"], latched)
            expected = _fields(PaperAccountSnapshot.model_validate(state.model_dump() | changes))
        _compare(label, expected, actual, out)
        state, latched = journaled, KillLevel.K0
    try:
        stored = PaperAccountSnapshot.model_validate_json(stored_payload)
    except ValidationError:
        return [*out, "account.payload"]
    _compare("account", _fields(state), _fields(stored), out)
    _compare(
        "column",
        {
            "writer_epoch": state.epoch,
            "kill_level": state.kill.value,
            "reconciled": state.reconciled,
            "truth_cursor": cursor,
        },
        stored_columns,
        out,
    )
    return out


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


_PROJECTIONS = frozenset(
    {
        "WRITER_ACQUIRED_PAUSE_NEW",
        "KILL_STATE",
        "OWNER_PAPER_RESUME",
        "UNKNOWN_RECONCILE_ONLY",
        "RECONCILIATION",
        "OWNER_RELEASE_PIN",
        "OWNER_POLICY_PIN",
        "UTC_DAY_ROLLOVER",
        "FLAT_BOUNDARY_ROLL",
    }
)
