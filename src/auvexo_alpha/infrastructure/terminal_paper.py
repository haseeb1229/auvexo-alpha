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

# One catalog snapshot per acquired connection; no cached identity/privilege verdict.
_READ_IDENTITY_SQL = text("""
WITH reader AS (
    SELECT * FROM pg_catalog.pg_roles WHERE rolname = :login
), relations AS (
    SELECT c.oid, c.relname, c.relkind, n.nspname
    FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND c.relkind IN ('r','p','v','m','f')
)
SELECT
    session_user::text = :login AND current_user::text = :login
    AND current_database() = :database
    AND inet_server_addr() = '127.0.0.1'::inet AND inet_server_port() = 55432
    AND current_setting('TimeZone') = 'UTC'
    AND current_setting('transaction_isolation') = 'repeatable read'
    AND current_setting('transaction_read_only') = 'on'
    AND current_schemas(false) = ARRAY['public']::name[]
    AND EXISTS (SELECT FROM reader WHERE rolcanlogin AND NOT rolsuper
        AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
        AND NOT rolbypassrls AND NOT rolinherit
        AND (rolvaliduntil IS NULL OR rolvaliduntil > clock_timestamp()))
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_auth_members m JOIN reader r ON m.member=r.oid)
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_database d JOIN reader r ON d.datdba=r.oid)
    AND NOT has_database_privilege(current_user,current_database(),'CREATE,TEMP')
    AND has_schema_privilege(current_user,'public','USAGE')
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_namespace n JOIN reader r ON n.nspowner=r.oid)
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_namespace n
        WHERE has_schema_privilege(current_user,n.oid,'CREATE'))
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_class c JOIN reader r ON c.relowner=r.oid)
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_proc p JOIN reader r ON p.proowner=r.oid)
    AND (SELECT count(*) = 4 FROM relations t
        WHERE t.nspname='public' AND t.relkind='r'
        AND t.relname IN ('paper_account','paper_reservation','paper_outbox','paper_journal')
        AND has_table_privilege(current_user,t.oid,'SELECT'))
    AND NOT EXISTS (SELECT FROM relations t WHERE
        (has_any_column_privilege(current_user,t.oid,'SELECT') AND NOT (
            t.nspname='public' AND t.relname IN
            ('paper_account','paper_reservation','paper_outbox','paper_journal')))
        OR has_table_privilege(current_user,t.oid,
            'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES,MAINTAIN,SELECT WITH GRANT OPTION')
        OR has_any_column_privilege(current_user,t.oid,
            'INSERT,UPDATE,REFERENCES,SELECT WITH GRANT OPTION'))
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='S' AND n.nspname NOT IN ('pg_catalog','information_schema')
        AND has_sequence_privilege(current_user,c.oid,'USAGE,SELECT,UPDATE'))
    AND NOT EXISTS (SELECT FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema')
        AND has_function_privilege(current_user,p.oid,'EXECUTE'))
""")


class PostgresTerminalReads(UnconnectedTerminalReads):
    """Isolated synthetic namespace only; future operational wiring is not authorized."""

    def __init__(self, engine: Engine, account_ref: str) -> None:
        if (
            engine.url.drivername != "postgresql+psycopg"
            or engine.url.host != "127.0.0.1"
            or engine.url.port != 55432
            or not engine.url.password
            or bool(engine.url.query)
            or bool(engine.get_execution_options())
            or not re.fullmatch(r"auvexo_test_[a-f0-9]{20}", engine.url.database or "")
            or not re.fullmatch(r"auvexo_read_[a-f0-9]{20}", engine.url.username or "")
            or not re.fullmatch(r"paper\.[a-zA-Z0-9._-]{1,100}", account_ref)
        ):
            raise ValueError("ISOLATED_READ_MODEL_IDENTITY_REQUIRED")
        self.engine, self.account_ref = engine, account_ref
        self._expected_login = engine.url.username or ""
        self._expected_database = engine.url.database or ""

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout='2000ms'"))
                valid = conn.execute(
                    _READ_IDENTITY_SQL,
                    {"login": self._expected_login, "database": self._expected_database},
                ).scalar_one()
                if valid is not True:
                    raise ValueError("READ_ONLY_IDENTITY_OR_PRIVILEGES_REQUIRED")
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
                            "SELECT payload,kill_level,reconciled FROM public.paper_account WHERE "
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
                    text(
                        "SELECT count(*) FROM public.paper_reservation "
                        "WHERE account_ref=:a AND active"
                    ),
                    {"a": self.account_ref},
                ).scalar_one()
                reservation_rows = (
                    conn.execute(
                        text(
                            "SELECT payload FROM public.paper_reservation "
                            "WHERE account_ref=:a AND active "
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
                            "SELECT intent_hash,state FROM public.paper_outbox "
                            "WHERE account_ref=:a AND "
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
                            "public.paper_journal WHERE account_ref=:a "
                            "ORDER BY sequence DESC LIMIT 100"
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
