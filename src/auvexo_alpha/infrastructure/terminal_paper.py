"""Query-only synthetic PAPER projection; never connected to campaign runtime."""

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from auvexo_alpha.application.terminal_models import (
    Freshness,
    JournalEvent,
    JournalView,
    PaperView,
    PendingView,
    PositionView,
    ReservationView,
)
from auvexo_alpha.application.terminal_reads import UnconnectedTerminalReads
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperReservation


class PostgresTerminalReads(UnconnectedTerminalReads):
    """Isolated synthetic namespace only; future operational wiring is not authorized."""

    def __init__(self, engine: Engine, account_ref: str) -> None:
        if (
            not re.fullmatch(r"auvexo_test_[a-f0-9]{20}", engine.url.database or "")
            or not re.fullmatch(r"auvexo_read_[a-f0-9]{20}", engine.url.username or "")
            or not re.fullmatch(r"paper\.[a-zA-Z0-9._-]{1,100}", account_ref)
        ):
            raise ValueError("ISOLATED_READ_MODEL_IDENTITY_REQUIRED")
        self.engine, self.account_ref = engine, account_ref

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout='2000ms'"))
                privileged = conn.execute(
                    text(
                        "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                ).scalar_one()
                mutable = conn.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM "
                        "unnest(ARRAY['paper_account','paper_reservation',"
                        "'paper_outbox','paper_journal']) t CROSS JOIN "
                        "unnest(ARRAY['INSERT','UPDATE','DELETE','TRUNCATE',"
                        "'TRIGGER','REFERENCES']) p "
                        "WHERE has_table_privilege(current_user,t,p))"
                    )
                ).scalar_one()
                if privileged or mutable:
                    raise ValueError("READ_ONLY_PRIVILEGES_REQUIRED")
                yield conn

    @staticmethod
    def _unavailable() -> Freshness:
        return Freshness(
            state="UNAVAILABLE", provenance="ISOLATED_SYNTHETIC_PAPER", reason="READ_UNAVAILABLE"
        )

    @staticmethod
    def _freshness(observed: datetime, now: datetime) -> Freshness:
        stale = not timedelta(seconds=-5) <= now - observed <= timedelta(seconds=120)
        return Freshness(
            state="STALE" if stale else "AVAILABLE",
            observed_at=observed,
            provenance="ISOLATED_SYNTHETIC_PAPER",
            reason="SOURCE_STALE" if stale else "CURRENT",
        )

    def paper(self, *, now: datetime) -> PaperView:
        try:
            with self._connection() as conn:
                row = (
                    conn.execute(
                        text(
                            "SELECT payload,kill_level,reconciled FROM paper_account WHERE "
                            "account_ref=:a"
                        ),
                        {"a": self.account_ref},
                    )
                    .mappings()
                    .one()
                )
                account = PaperAccountSnapshot.model_validate_json(row["payload"])
                if (
                    account.account_ref != self.account_ref
                    or account.kill.value != row["kill_level"]
                    or account.reconciled != row["reconciled"]
                ):
                    raise ValueError("PROJECTION_BINDING_INVALID")
                count = conn.execute(
                    text("SELECT count(*) FROM paper_reservation WHERE account_ref=:a AND active"),
                    {"a": self.account_ref},
                ).scalar_one()
                reservation_rows = (
                    conn.execute(
                        text(
                            "SELECT payload FROM paper_reservation WHERE account_ref=:a AND active "
                            "ORDER BY intent_hash LIMIT 101"
                        ),
                        {"a": self.account_ref},
                    )
                    .scalars()
                    .all()
                )
                if len(reservation_rows) > 100:
                    raise ValueError("PROJECTION_BOUND_EXCEEDED")
                reservations = tuple(
                    PaperReservation.model_validate_json(v) for v in reservation_rows
                )
                if any(r.account_ref != self.account_ref for r in reservations):
                    raise ValueError("PROJECTION_BINDING_INVALID")
                pending = (
                    conn.execute(
                        text(
                            "SELECT intent_hash,state FROM paper_outbox WHERE account_ref=:a AND "
                            "state IN "
                            "('RESERVED','SENT_PENDING','ACKNOWLEDGED','UNKNOWN',"
                            "'PARTIALLY_FILLED') ORDER BY intent_hash LIMIT 101"
                        ),
                        {"a": self.account_ref},
                    )
                    .mappings()
                    .all()
                )
                if len(pending) > 100 or len(account.positions) > 100:
                    raise ValueError("PROJECTION_BOUND_EXCEEDED")
                return PaperView(
                    freshness=self._freshness(account.as_of, now),
                    balance=format(account.cash, "f"),
                    equity=format(account.equity, "f"),
                    currency="USD" if account.currency == "USD" else "UNCLASSIFIED",
                    kill=cast(Any, account.kill.value),
                    reconciled=account.reconciled,
                    unknown_orders=account.unknown_orders,
                    active_reservations=count,
                    reservations=tuple(
                        ReservationView(
                            intent_hash=r.intent_hash,
                            state=r.state,
                            instrument=cast(
                                Any,
                                r.instrument_id
                                if r.instrument_id in ("BTCUSDT", "ETHUSDT")
                                else "UNCLASSIFIED",
                            ),
                            quantity=format(r.quantity, "f"),
                            notional=format(r.notional, "f"),
                            modeled_loss=format(r.modeled_loss, "f"),
                        )
                        for r in reservations
                    ),
                    positions=tuple(
                        PositionView(
                            position_hash=hashlib.sha256(p.position_ref.encode()).hexdigest(),
                            instrument=cast(
                                Any,
                                p.instrument_id
                                if p.instrument_id in ("BTCUSDT", "ETHUSDT")
                                else "UNCLASSIFIED",
                            ),
                            quantity=format(p.quantity, "f"),
                            entry_price=format(p.entry_price, "f"),
                            mark_price=format(p.mark_price, "f"),
                        )
                        for p in account.positions
                    ),
                    pending=tuple(
                        PendingView(intent_hash=p["intent_hash"], state=p["state"]) for p in pending
                    ),
                )
        except (SQLAlchemyError, ValidationError, ValueError):
            return PaperView(freshness=self._unavailable())

    def journal(self, *, now: datetime) -> JournalView:
        try:
            with self._connection() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT sequence,recorded_at,kind,intent_hash,content_hash FROM "
                            "paper_journal WHERE account_ref=:a ORDER BY sequence DESC LIMIT 100"
                        ),
                        {"a": self.account_ref},
                    )
                    .mappings()
                    .all()
                )
                # Only safe immutable metadata, never arbitrary payload or kind text.
                events = tuple(
                    JournalEvent(
                        sequence=r["sequence"],
                        observed_at=r["recorded_at"].astimezone(UTC),
                        reason=cast(
                            Any,
                            r["kind"]
                            if r["kind"] in ("AUTHORIZED", "DENIED", "RECONCILED", "KILL_CHANGED")
                            else "OTHER_RECORDED_EVENT",
                        ),
                        intent_hash=r["intent_hash"],
                        evidence_hash=r["content_hash"],
                    )
                    for r in rows
                )
                freshness = (
                    self._freshness(events[0].observed_at, now)
                    if events
                    else Freshness(
                        state="UNKNOWN",
                        provenance="ISOLATED_SYNTHETIC_PAPER",
                        reason="NOT_CONNECTED",
                    )
                )
                return JournalView(freshness=freshness, events=events)
        except (SQLAlchemyError, ValidationError, ValueError):
            return JournalView(freshness=self._unavailable())
