"""Independent append-only virtual facts. This adapter never contacts a venue."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from auvexo_alpha.domain.contracts import Contract, utc_time
from auvexo_alpha.domain.paper import PaperMarketSnapshot, PaperPosition, paper_position_ref
from auvexo_alpha.infrastructure.paper_identity import enforce_paper_engine


def canonical_payload(value: object) -> str:
    """Encode bounded JSON; floats and non-finite decimal values cannot enter facts."""

    def convert(item: object) -> object:
        if isinstance(item, Contract):
            return json.loads(item.canonical_bytes())
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("NONFINITE_PAPER_FACT")
            return format(item, "f")
        if isinstance(item, datetime):
            return utc_time(item).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, float):
            raise ValueError("FLOAT_PAPER_FACT")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("INVALID_PAPER_FACT_KEY")
            return {key: convert(val) for key, val in item.items()}
        if isinstance(item, (tuple, list)):
            return [convert(val) for val in item]
        if item is None or isinstance(item, (str, int, bool)):
            return item
        raise ValueError("INVALID_PAPER_FACT")

    result = json.dumps(convert(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(result.encode()) > 1048576:
        raise ValueError("PAPER_FACT_BUDGET")
    return result


def digest(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_market_mark(
    payload: object,
    recorded_at: datetime,
    rows: list[dict[str, Any]],
    *,
    baseline_positions: tuple[PaperPosition, ...] = (),
) -> None:
    """Intrinsic historical acceptance; current age/policy never deletes a fact."""

    mark = PaperMarketSnapshot.model_validate_json(canonical_payload(payload))
    if (
        mark.health != "HEALTHY"
        or not mark.session_open
        or mark.adverse_fx is None
        or mark.fx_as_of is None
        or not mark.as_of <= mark.available_at <= recorded_at
        or mark.fx_as_of > mark.available_at
    ):
        raise ValueError("INVALID_OR_FUTURE_VIRTUAL_MARK")
    known = {
        str(row["data"].get("instrument_id"))
        for row in rows
        if row["kind"] in ("ORDER", "EXTERNAL_POSITION")
    }
    known.update(position.instrument_id for position in baseline_positions)
    if mark.instrument_id not in known:
        raise ValueError("VIRTUAL_MARK_INSTRUMENT_SCOPE_DENIED")
    _validate_mark_economics(
        mark.instrument_id,
        mark.as_of,
        mark.bid,
        mark.adverse_fx,
        mark.fx_as_of,
        rows,
        baseline_positions,
    )
    economics = (
        mark.bid,
        mark.ask,
        mark.adverse_fx,
        mark.available_at,
        mark.fx_as_of,
        mark.health,
        mark.session_open,
        mark.clock_offset_ms,
    )
    for row in rows:
        if row["kind"] != "MARKET_MARK":
            continue
        previous = PaperMarketSnapshot.model_validate_json(canonical_payload(row["data"]))
        if previous.snapshot_id == mark.snapshot_id and previous != mark:
            raise ValueError("CONFLICTING_VIRTUAL_MARK_SNAPSHOT")
        if (
            previous.instrument_id == mark.instrument_id
            and previous.as_of == mark.as_of
            and (
                previous.bid,
                previous.ask,
                previous.adverse_fx,
                previous.available_at,
                previous.fx_as_of,
                previous.health,
                previous.session_open,
                previous.clock_offset_ms,
            )
            != economics
        ):
            raise ValueError("CONFLICTING_VIRTUAL_MARK_TIMESTAMP")


def _validate_mark_economics(
    instrument_id: str,
    observed_at: datetime,
    price: Decimal,
    adverse_fx: Decimal,
    fx_as_of: datetime,
    rows: list[dict[str, Any]],
    baseline_positions: tuple[PaperPosition, ...],
) -> None:
    """A shared observation time cannot name conflicting position valuations."""
    previous_positions = list(baseline_positions)
    for row in rows:
        if row["kind"] == "EXTERNAL_POSITION":
            previous_positions.append(
                PaperPosition.model_validate_json(canonical_payload(row["data"]))
            )
        elif row["kind"] == "MARKET_MARK":
            previous = PaperMarketSnapshot.model_validate_json(canonical_payload(row["data"]))
            if (
                previous.instrument_id == instrument_id
                and previous.as_of == observed_at
                and (previous.bid, previous.adverse_fx, previous.fx_as_of)
                != (price, adverse_fx, fx_as_of)
            ):
                raise ValueError("CONFLICTING_VIRTUAL_MARK_TIMESTAMP")
    for position in previous_positions:
        if (
            position.instrument_id == instrument_id
            and position.mark_as_of == observed_at
            and position.fx_as_of is not None
            and (position.mark_price, position.adverse_fx, position.fx_as_of)
            != (price, adverse_fx, fx_as_of)
        ):
            raise ValueError("CONFLICTING_VIRTUAL_MARK_TIMESTAMP")


def validate_position_mark(
    position: PaperPosition,
    recorded_at: datetime,
    rows: list[dict[str, Any]],
    *,
    baseline_positions: tuple[PaperPosition, ...] = (),
) -> None:
    prior_positions = list(baseline_positions) + [
        PaperPosition.model_validate_json(canonical_payload(row["data"]))
        for row in rows
        if row["kind"] == "EXTERNAL_POSITION"
    ]
    conflicting_order = any(
        row["kind"] == "ORDER"
        and row["data"].get("action") == "OPEN"
        and paper_position_ref(str(row["account_ref"]), UUID(str(row["data"]["intent_id"])))
        == position.position_ref
        and row["data"]["instrument_id"] != position.instrument_id
        for row in rows
    )
    if conflicting_order or any(
        prior.position_ref == position.position_ref
        and prior.instrument_id != position.instrument_id
        for prior in prior_positions
    ):
        raise ValueError("VIRTUAL_POSITION_INSTRUMENT_SCOPE_DENIED")
    available = position.mark_available_at or recorded_at
    if (
        available > recorded_at
        or (position.mark_as_of is not None and position.mark_as_of > available)
        or (position.fx_as_of is not None and position.fx_as_of > available)
    ):
        raise ValueError("INVALID_OR_FUTURE_VIRTUAL_MARK")
    if position.mark_as_of is not None and position.fx_as_of is not None:
        _validate_mark_economics(
            position.instrument_id,
            position.mark_as_of,
            position.mark_price,
            position.adverse_fx,
            position.fx_as_of,
            rows,
            baseline_positions,
        )


def resolution_facts(rows: list[dict[str, Any]], intent_hash: str) -> str:
    """Bind finality to every observed fill and rejection, never erase either fact."""
    return digest(
        canonical_payload(
            [
                row["content_hash"]
                for row in rows
                if (
                    row["intent_hash"] == intent_hash
                    and (
                        row["kind"] == "FILL"
                        or (row["kind"] == "STATUS" and row["data"].get("status") == "REJECTED")
                    )
                )
            ]
        )
    )


def validate_resolution(rows: list[dict[str, Any]], intent_hash: str, data: dict[str, Any]) -> None:
    from auvexo_alpha.domain.contracts import exact_decimal

    if (
        set(data)
        != {
            "status",
            "confirmed_filled_quantity",
            "no_further_fills",
            "observed_facts_hash",
            "evidence_hash",
            "semantics",
        }
        or data["status"] not in ("FILLED", "CANCELED", "EXPIRED")
        or data["no_further_fills"] is not True
        or data["semantics"] != "AUTHORITATIVE_VIRTUAL_FINALITY"
        or not isinstance(data["evidence_hash"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", data["evidence_hash"])
        or data["observed_facts_hash"] != resolution_facts(rows, intent_hash)
    ):
        raise ValueError("INVALID_VIRTUAL_FINALITY_PROOF")
    orders = [row for row in rows if row["intent_hash"] == intent_hash and row["kind"] == "ORDER"]
    if len(orders) != 1:
        raise ValueError("UNBOUND_VIRTUAL_FINALITY_PROOF")
    actual = sum(
        (
            exact_decimal(row["data"]["quantity"])
            for row in rows
            if row["intent_hash"] == intent_hash and row["kind"] == "FILL"
        ),
        Decimal("0"),
    )
    confirmed = exact_decimal(data["confirmed_filled_quantity"])
    maximum = exact_decimal(orders[0]["data"]["quantity"])
    if (
        confirmed != actual
        or not Decimal("0") <= confirmed <= maximum
        or (data["status"] == "FILLED" and confirmed != maximum)
    ):
        raise ValueError("VIRTUAL_FINALITY_QUANTITY_MISMATCH")


def truth_rows(conn: Connection, account_ref: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT * FROM paper_truth_event WHERE account_ref=:a ORDER BY sequence"),
        {"a": account_ref},
    ).mappings()
    result: list[dict[str, Any]] = []
    previous = "0" * 64
    for row in rows:
        payload = str(row["payload"])
        envelope = json.loads(payload)
        if (
            digest(payload) != row["content_hash"]
            or envelope["previous_hash"] != previous
            or any(
                envelope.get(key) != value
                for key, value in {
                    "account_ref": account_ref,
                    "kind": row["kind"],
                    "intent_hash": row["intent_hash"],
                    "event_id": row["event_id"],
                    "recorded_at": canonical_payload(row["recorded_at"])[1:-1],
                }.items()
            )
        ):
            raise ValueError("CORRUPT_PAPER_TRUTH")
        previous = str(row["content_hash"])
        result.append(dict(row) | {"data": envelope["data"]})
    return result


class PaperTruth:
    """Simulator-owned truth role. Local journal writers have no INSERT permission here."""

    def __init__(self, engine: Engine) -> None:
        enforce_paper_engine(engine, "auvexo_paper_truth")
        self.engine = engine

    def append(
        self,
        account_ref: str,
        kind: str,
        payload: object,
        *,
        intent_hash: str | None = None,
        event_id: str | None = None,
        now: datetime,
        writer_epoch: int | None = None,
    ) -> str:
        now = utc_time(now)
        identity = event_id or str(uuid4())
        if not account_ref.startswith("paper."):
            raise ValueError("VIRTUAL_PAPER_ACCOUNT_REQUIRED")
        data = json.loads(canonical_payload(payload))
        with self.engine.begin() as conn:
            if not conn.scalar(text("SELECT paper_lock_truth(:a)"), {"a": account_ref}):
                raise ValueError("UNKNOWN_VIRTUAL_PAPER_ACCOUNT")
            if kind == "ORDER" and (
                writer_epoch is None
                or not conn.scalar(
                    text("SELECT paper_fence_truth(:a,:e,:i,:p,:at)"),
                    {
                        "a": account_ref,
                        "e": writer_epoch,
                        "i": intent_hash,
                        "p": canonical_payload(data),
                        "at": now,
                    },
                )
            ):
                raise ValueError("STALE_PAPER_WRITER_OR_UNCLAIMED_ORDER")
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:a,20801501))"),
                {"a": account_ref},
            )
            prior = (
                conn.execute(
                    text("SELECT * FROM paper_truth_event WHERE event_id=:id"), {"id": identity}
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                old = json.loads(str(prior["payload"]))["data"]
                if (prior["account_ref"], prior["intent_hash"], prior["kind"], old) != (
                    account_ref,
                    intent_hash,
                    kind,
                    data,
                ):
                    raise ValueError("CONFLICTING_VIRTUAL_EVENT")
                return identity
            rows = truth_rows(conn, account_ref)
            if kind == "MARKET_MARK":
                validate_market_mark(data, now, rows)
            if kind == "EXTERNAL_POSITION":
                position = PaperPosition.model_validate_json(canonical_payload(data))
                validate_position_mark(position, now, rows)
            if kind == "RESOLUTION":
                if intent_hash is None:
                    raise ValueError("UNBOUND_VIRTUAL_FINALITY_PROOF")
                validate_resolution(rows, intent_hash, data)
            previous = str(rows[-1]["content_hash"]) if rows else "0" * 64
            encoded = canonical_payload(
                {
                    "data": data,
                    "previous_hash": previous,
                    "account_ref": account_ref,
                    "kind": kind,
                    "intent_hash": intent_hash,
                    "event_id": identity,
                    "recorded_at": now,
                }
            )
            conn.execute(
                text(
                    "INSERT INTO paper_truth_event "
                    "(event_id,account_ref,intent_hash,kind,content_hash,payload,recorded_at) "
                    "VALUES (:id,:a,:i,:k,:h,:p,:at)"
                ),
                {
                    "id": identity,
                    "a": account_ref,
                    "i": intent_hash,
                    "k": kind,
                    "h": digest(encoded),
                    "p": encoded,
                    "at": now,
                },
            )
        return identity

    def record_order(
        self,
        intent: Contract,
        *,
        now: datetime,
        writer_epoch: int,
        quantity: Decimal | None = None,
        event_id: str | None = None,
    ) -> str:
        from auvexo_alpha.domain.paper import PaperIntent

        intent = PaperIntent.model_validate_json(intent.canonical_bytes())
        data = json.loads(intent.canonical_bytes())
        if quantity is not None:
            data["quantity"] = format(quantity, "f")
        return self.append(
            str(data["account_ref"]),
            "ORDER",
            data,
            intent_hash=intent.content_hash(),
            event_id=event_id,
            now=now,
            writer_epoch=writer_epoch,
        )

    def fill(
        self,
        intent_hash: str,
        quantity: Decimal | str,
        price: Decimal | str,
        *,
        account_ref: str,
        now: datetime,
        event_id: str | None = None,
    ) -> str:
        from auvexo_alpha.domain.contracts import exact_decimal

        qty, px = exact_decimal(quantity), exact_decimal(price)
        if qty <= 0 or px <= 0:
            raise ValueError("INVALID_VIRTUAL_FILL")
        return self.append(
            account_ref,
            "FILL",
            {"quantity": qty, "price": px},
            intent_hash=intent_hash,
            event_id=event_id,
            now=now,
        )

    def status(
        self,
        intent_hash: str,
        status: str,
        *,
        account_ref: str,
        now: datetime,
        event_id: str | None = None,
    ) -> str:
        if status not in ("ACKNOWLEDGED", "REJECTED", "UNKNOWN", "CANCELED", "EXPIRED"):
            raise ValueError("INVALID_VIRTUAL_STATUS")
        return self.append(
            account_ref,
            "STATUS",
            {"status": status},
            intent_hash=intent_hash,
            event_id=event_id,
            now=now,
        )

    def external_position(
        self,
        account_ref: str,
        position: Contract,
        *,
        now: datetime,
        event_id: str | None = None,
    ) -> str:
        return self.append(
            account_ref,
            "EXTERNAL_POSITION",
            position,
            event_id=event_id,
            now=now,
        )

    def events(self, account_ref: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return truth_rows(conn, account_ref)

    def adjustment(
        self, account_ref: str, amount: Decimal | str, *, now: datetime, event_id: str | None = None
    ) -> str:
        from auvexo_alpha.domain.contracts import exact_decimal

        return self.append(
            account_ref,
            "ADJUSTMENT",
            {"amount": exact_decimal(amount), "semantics": "OBSERVED_VIRTUAL_ONLY"},
            now=now,
            event_id=event_id,
        )

    def mark(
        self, account_ref: str, market: Contract, *, now: datetime, event_id: str | None = None
    ) -> str:
        from auvexo_alpha.domain.paper import PaperMarketSnapshot

        snapshot = PaperMarketSnapshot.model_validate_json(market.canonical_bytes())
        return self.append(account_ref, "MARKET_MARK", snapshot, now=now, event_id=event_id)

    def resolve(
        self,
        intent_hash: str,
        status: str,
        confirmed_filled_quantity: Decimal | str,
        *,
        account_ref: str,
        now: datetime,
        evidence_hash: str,
        event_id: str | None = None,
    ) -> str:
        from auvexo_alpha.domain.contracts import exact_decimal

        rows = self.events(account_ref)
        return self.append(
            account_ref,
            "RESOLUTION",
            {
                "status": status,
                "confirmed_filled_quantity": exact_decimal(confirmed_filled_quantity),
                "no_further_fills": True,
                "observed_facts_hash": resolution_facts(rows, intent_hash),
                "evidence_hash": evidence_hash,
                "semantics": "AUTHORITATIVE_VIRTUAL_FINALITY",
            },
            intent_hash=intent_hash,
            now=now,
            event_id=event_id,
        )
