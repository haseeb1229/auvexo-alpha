"""Account-serialized virtual PAPER journal/outbox; no external execution capability."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from auvexo_alpha.application.paper_ledger import PaperLedgerReplay, replay_ledger
from auvexo_alpha.domain.contracts import Contract, MoneyAction, exact_decimal, utc_time
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperDecision,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperMarkHealth,
    PaperPolicy,
    PaperPosition,
    PaperReason,
    PaperReservation,
    bind_authorization,
    paper_position_ref,
)
from auvexo_alpha.domain.paper_lifecycle import (
    EdgeState,
    EdgeTransition,
    KillLevel,
    Release,
    ReleaseState,
    ReleaseTransition,
    fixture_edge_transition,
    validate_initial_release,
    validate_registry_release,
    validate_release_transition,
)
from auvexo_alpha.domain.paper_risk import assess_paper, loss_limits, verify_authorization
from auvexo_alpha.infrastructure.paper_identity import enforce_paper_engine
from auvexo_alpha.infrastructure.paper_truth import (
    PaperTruth,
    canonical_payload,
    digest,
    resolution_facts,
    truth_rows,
    validate_market_mark,
    validate_position_mark,
    validate_resolution,
    validate_spec_observation,
)

# Journal kinds whose `data.account` is a full account projection.
PROJECTION_EVENTS = frozenset(
    {
        "INITIALIZED",
        "WRITER_ACQUIRED_PAUSE_NEW",
        "KILL_STATE",
        "OWNER_PAPER_RESUME",
        "UNKNOWN_RECONCILE_ONLY",
        "RECONCILIATION",
        "OWNER_RELEASE_PIN",
        "OWNER_POLICY_PIN",
        "UTC_DAY_ROLLOVER",
        "FLAT_BOUNDARY_ROLL",
        "LOSS_BREACH_LATCH",
    }
)
# A fact that fails validation is excluded from the projection, never deleted (P-9).
INVALID_TRUTH = (ValueError, KeyError, TypeError, ArithmeticError)


@dataclass(frozen=True)
class Submission:
    decision: PaperDecision
    authorization: PaperAuthorization | None = None
    reservation: PaperReservation | None = None


@dataclass(frozen=True)
class ObservedMark:
    price: Decimal
    adverse_fx: Decimal
    observed_at: datetime
    available_at: datetime
    fx_as_of: datetime
    snapshot_hash: str | None
    fact_hash: str | None
    clock_offset_ms: int = 0

    @classmethod
    def from_position(cls, position: PaperPosition) -> ObservedMark | None:
        if position.mark_as_of is None or position.fx_as_of is None:
            return None
        return cls(
            position.mark_price,
            position.adverse_fx,
            position.mark_as_of,
            position.mark_available_at or position.mark_as_of,
            position.fx_as_of,
            position.mark_snapshot_hash,
            position.mark_fact_hash,
        )


@dataclass
class _VerifiedJournal:
    """Verified history owned by one locked account transaction, never a store cache."""

    connection: Connection
    transaction: object
    account_ref: str
    rows: list[dict[str, Any]]

    def for_scope(self, conn: Connection, account_ref: str) -> list[dict[str, Any]]:
        if (
            conn is not self.connection
            or account_ref != self.account_ref
            or not conn.in_transaction()
            or conn.in_nested_transaction()
            or conn.get_transaction() is not self.transaction
        ):
            raise ValueError("PAPER_JOURNAL_CONTEXT_SCOPE_DENIED")
        return self.rows


def bounded_amount(value: Decimal, *, ceiling: bool = False) -> Decimal:
    """Explicit conservative 18-place projection; exact fill facts remain preserved."""
    return value.quantize(
        Decimal("0.000000000000000001"), rounding=ROUND_CEILING if ceiling else ROUND_FLOOR
    )


@dataclass
class _TruthFold:
    """Projection folded from accepted truth. Each fact is applied to a copy, so a fact
    that fails validation leaves no partial effect and is quarantined instead."""

    positions: dict[str, PaperPosition]
    owners: dict[str, str | None]
    marks: dict[str, ObservedMark]
    position_marks: dict[str, ObservedMark | None]
    cash: Decimal
    day_flows: Decimal
    total_flows: Decimal
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    fills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    rejected: set[str] = field(default_factory=set)
    resolutions: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_new: bool = False

    def copy(self) -> _TruthFold:
        return replace(
            self,
            positions=dict(self.positions),
            owners=dict(self.owners),
            marks=dict(self.marks),
            position_marks=dict(self.position_marks),
            orders=dict(self.orders),
            fills={key: list(value) for key, value in self.fills.items()},
            statuses=dict(self.statuses),
            rejected=set(self.rejected),
            resolutions=dict(self.resolutions),
        )


@dataclass(frozen=True)
class _Bound:
    """Immutable authorization inputs of one outbox order, read from its AUTHORIZED event."""

    intent: PaperIntent
    authorization: PaperAuthorization
    spec: PaperInstrumentSpec
    market: PaperMarketSnapshot


class PaperStore:
    """Account-serialized PAPER writes.

    Writer fencing (P-11/OBV2-10). `acquire_writer` records the epoch it was granted on
    this instance. Writer operations (authorize, claim, mark_unknown, dispatch and both day
    rolls) need that epoch, or an explicit `epoch`, equal to the account's current epoch.
    Deterministic maintenance (reconcile, edge suspension) derives only from durable facts,
    so a caller holding no epoch may run it, but a caller holding a superseded epoch is
    refused. Raising a kill level is fail-closed and is accepted from any runtime caller.
    """

    def __init__(self, engine: Engine, owner_engine: Engine | None = None) -> None:
        enforce_paper_engine(engine, "auvexo_paper")
        if owner_engine is not None:
            enforce_paper_engine(owner_engine, "auvexo_paper_owner")
        self.engine, self.owner_engine = engine, owner_engine
        self._writer_epochs: dict[str, int] = {}

    def _fence(
        self, account_ref: str, row: dict[str, Any], epoch: int | None, *, writer: bool
    ) -> None:
        held = epoch if epoch is not None else self._writer_epochs.get(account_ref)
        if held is None:
            if writer:
                raise ValueError("PAPER_WRITER_EPOCH_REQUIRED")
            return
        if held != int(row["writer_epoch"]):
            raise ValueError("STALE_PAPER_WRITER")

    @staticmethod
    def _latest_truth(conn: Connection, account_ref: str) -> int:
        return int(
            conn.scalar(
                text(
                    "SELECT COALESCE(max(sequence),0) FROM paper_truth_event WHERE account_ref=:a"
                ),
                {"a": account_ref},
            )
            or 0
        )

    @staticmethod
    def _pinned_policy(conn: Connection, row: dict[str, Any]) -> PaperPolicy:
        payload = conn.scalar(
            text("SELECT payload FROM paper_policy WHERE content_hash=:h"),
            {"h": row["policy_hash"]},
        )
        if digest(str(payload)) != row["policy_hash"]:
            raise ValueError("CORRUPT_PAPER_CONFIGURATION")
        return PaperPolicy.model_validate_json(str(payload))

    @staticmethod
    def _lock(conn: Connection, account_ref: str) -> dict[str, Any]:
        row = (
            conn.execute(
                text("SELECT * FROM paper_account WHERE account_ref=:a FOR UPDATE"),
                {"a": account_ref},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("UNKNOWN_PAPER_ACCOUNT")
        return dict(row)

    @staticmethod
    def _journal(conn: Connection, account_ref: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            text("SELECT * FROM paper_journal WHERE account_ref=:a ORDER BY sequence"),
            {"a": account_ref},
        ).mappings()
        previous, result = "0" * 64, []
        for row in rows:
            envelope = json.loads(str(row["payload"]))
            if (
                digest(str(row["payload"])) != row["content_hash"]
                or (envelope["previous_hash"] != previous)
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
                raise ValueError("CORRUPT_PAPER_JOURNAL")
            previous = str(row["content_hash"])
            result.append(dict(row) | {"data": envelope["data"]})
        return result

    @classmethod
    def _append(
        cls,
        conn: Connection,
        account_ref: str,
        kind: str,
        data: object,
        now: datetime,
        intent_hash: str | None = None,
        *,
        history: _VerifiedJournal | None = None,
    ) -> None:
        rows = (
            history.for_scope(conn, account_ref)
            if history is not None
            else cls._journal(conn, account_ref)
        )
        identity = str(uuid4())
        encoded = canonical_payload(
            {
                "previous_hash": str(rows[-1]["content_hash"]) if rows else "0" * 64,
                "data": data,
                "account_ref": account_ref,
                "kind": kind,
                "intent_hash": intent_hash,
                "event_id": identity,
                "recorded_at": utc_time(now),
            }
        )
        conn.execute(
            text(
                "INSERT INTO paper_journal "
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
                "at": utc_time(now),
            },
        )
        if history is not None:
            envelope = json.loads(encoded)
            rows.append(
                {
                    "event_id": identity,
                    "account_ref": account_ref,
                    "intent_hash": intent_hash,
                    "kind": kind,
                    "content_hash": digest(encoded),
                    "payload": encoded,
                    "recorded_at": utc_time(now),
                    "data": envelope["data"],
                }
            )

    @classmethod
    def _account(
        cls,
        conn: Connection,
        row: dict[str, Any],
        *,
        history: _VerifiedJournal | None = None,
    ) -> PaperAccountSnapshot:
        account = PaperAccountSnapshot.model_validate_json(str(row["payload"]))
        if (account.epoch, account.kill.value, account.reconciled) != (
            row["writer_epoch"],
            row["kill_level"],
            row["reconciled"],
        ):
            raise ValueError("CORRUPT_PAPER_ACCOUNT")
        rows = (
            history.for_scope(conn, account.account_ref)
            if history is not None
            else cls._journal(conn, account.account_ref)
        )
        latest = next(
            (
                event["data"]["account"]
                for event in reversed(rows)
                if event["kind"] in PROJECTION_EVENTS
            ),
            None,
        )
        if (
            latest is None
            or PaperAccountSnapshot.model_validate_json(canonical_payload(latest)) != account
        ):
            raise ValueError("CORRUPT_PAPER_ACCOUNT_HISTORY")
        intents = conn.execute(
            text(
                "SELECT logical_key,recorded_at,(payload::jsonb->>'intent_id')::uuid "
                "FROM paper_intent "
                "WHERE account_ref=:a ORDER BY recorded_at,intent_hash"
            ),
            {"a": account.account_ref},
        ).all()
        return PaperAccountSnapshot.model_validate(
            account.model_dump()
            | {
                "prior_logical_keys": tuple(str(item[0]) for item in intents),
                "recent_intent_times": tuple(item[1] for item in intents),
                "prior_intent_ids": tuple(item[2] for item in intents),
            }
        )

    @staticmethod
    def _save(
        conn: Connection,
        account: PaperAccountSnapshot,
        *,
        cursor: int | None = None,
        policy_hash: str | None = None,
        release_hash: str | None = None,
    ) -> None:
        """One UPDATE per journaled transition; the 0007 guard binds it to that event."""
        conn.execute(
            text(
                "UPDATE paper_account SET payload=:p,writer_epoch=:e,kill_level=:k,"
                "reconciled=:r,version=version+1,truth_cursor=COALESCE(:c,truth_cursor),"
                "policy_hash=COALESCE(:ph,policy_hash),release_hash=COALESCE(:rh,release_hash) "
                "WHERE account_ref=:a"
            ),
            {
                "p": account.canonical_bytes().decode(),
                "e": account.epoch,
                "k": account.kill.value,
                "r": account.reconciled,
                "c": cursor,
                "ph": policy_hash,
                "rh": release_hash,
                "a": account.account_ref,
            },
        )

    def initialize(
        self,
        account: PaperAccountSnapshot,
        policy: PaperPolicy,
        release: Release,
        *,
        now: datetime,
    ) -> None:
        if self.owner_engine is None:
            raise ValueError("PAPER_OWNER_ROLE_REQUIRED")
        account = PaperAccountSnapshot.model_validate_json(account.canonical_bytes())
        policy = PaperPolicy.model_validate_json(policy.canonical_bytes())
        release = Release.model_validate_json(release.canonical_bytes())
        validate_registry_release(release, fixture_registry=True, now=now)
        account = PaperAccountSnapshot.model_validate(
            account.model_dump()
            | {
                "kill": KillLevel.K1,
                "reconciled": False,
                "unknown_orders": False,
                "prior_logical_keys": (),
                "prior_intent_ids": (),
                "recent_intent_times": (),
            }
        )
        with self.owner_engine.begin() as conn:
            for table, value in (("paper_policy", policy), ("paper_release", release)):
                conn.execute(
                    text(f"INSERT INTO {table} VALUES (:h,:p,:at) ON CONFLICT DO NOTHING"),
                    {"h": value.content_hash(), "p": value.canonical_bytes().decode(), "at": now},
                )
                stored = conn.scalar(
                    text(f"SELECT payload FROM {table} WHERE content_hash=:h"),
                    {"h": value.content_hash()},
                )
                if stored != value.canonical_bytes().decode():
                    raise ValueError("CORRUPT_PAPER_CONFIGURATION")
            conn.execute(
                text(
                    "INSERT INTO paper_account "
                    "(account_ref,payload,policy_hash,release_hash,writer_epoch,"
                    "kill_level,reconciled) "
                    "VALUES (:a,:p,:ph,:rh,:e,'K1',false)"
                ),
                {
                    "a": account.account_ref,
                    "p": account.canonical_bytes().decode(),
                    "ph": policy.content_hash(),
                    "rh": release.content_hash(),
                    "e": account.epoch,
                },
            )
            self._append(conn, account.account_ref, "INITIALIZED", {"account": account}, now)
            conn.execute(
                text(
                    "INSERT INTO paper_lifecycle(release_hash,payload,content_hash,recorded_at) "
                    "VALUES (:h,:p,:d,:at)"
                ),
                {
                    "h": release.content_hash(),
                    "p": release.canonical_bytes().decode(),
                    "d": release.content_hash(),
                    "at": now,
                },
            )

    def account(self, account_ref: str) -> PaperAccountSnapshot:
        with self.engine.begin() as conn:
            row = self._lock(conn, account_ref)
            self._journal(conn, account_ref)
            return self._account(conn, row)

    def reservations(self, account_ref: str) -> tuple[PaperReservation, ...]:
        with self.engine.connect() as conn:
            return self._reservations(conn, account_ref)

    @classmethod
    def _reservations(
        cls,
        conn: Connection,
        account_ref: str,
        *,
        history: _VerifiedJournal | None = None,
    ) -> tuple[PaperReservation, ...]:
        rows = (
            history.for_scope(conn, account_ref)
            if history is not None
            else cls._journal(conn, account_ref)
        )
        result = []
        for row in conn.execute(
            text(
                "SELECT r.*,o.state FROM paper_reservation r "
                "JOIN paper_outbox o ON o.intent_hash=r.intent_hash WHERE r.account_ref=:a "
                "ORDER BY r.intent_hash"
            ),
            {"a": account_ref},
        ).mappings():
            reservation = PaperReservation.model_validate_json(str(row["payload"]))
            events = [e for e in rows if e["intent_hash"] == row["intent_hash"]]
            expected_state = "RESERVED"
            for event in events:
                if event["kind"] == "DISPATCH_ATTEMPT":
                    expected_state = "SENT_PENDING"
                elif event["kind"] == "UNKNOWN_RECONCILE_ONLY":
                    expected_state = "UNKNOWN"
                elif event["kind"] == "RECONCILED_ORDER":
                    expected_state = str(event["data"]["state"])
            last = next(
                (
                    e["data"]["reservation"]
                    for e in reversed(rows)
                    if e["intent_hash"] == row["intent_hash"] and "reservation" in e["data"]
                ),
                None,
            )
            if (
                last is None
                or row["state"] != expected_state
                or reservation != PaperReservation.model_validate_json(canonical_payload(last))
                or (
                    bool(row["active"])
                    != (row["state"] not in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"))
                )
            ):
                raise ValueError("CORRUPT_PAPER_RESERVATION")
            if row["active"]:
                result.append(reservation)
        return tuple(result)

    def acquire_writer(self, account_ref: str, *, now: datetime) -> int:
        with self.engine.begin() as conn:
            row = self._lock(conn, account_ref)
            account = self._account(conn, row)
            account = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {
                    "epoch": account.epoch + 1,
                    "kill": max(account.kill, KillLevel.K1),
                    "reconciled": False,
                }
            )
            self._append(conn, account_ref, "WRITER_ACQUIRED_PAUSE_NEW", {"account": account}, now)
            self._save(conn, account)
        self._writer_epochs[account_ref] = account.epoch
        return account.epoch

    def set_kill(
        self,
        account_ref: str,
        level: KillLevel,
        *,
        actor: str,
        now: datetime,
    ) -> None:
        """Raise (or restate) the kill level. Fail-closed, so never writer-fenced."""
        with self.engine.begin() as conn:
            account = self._account(conn, self._lock(conn, account_ref))
            if level < account.kill:
                raise ValueError("EXPLICIT_OWNER_RESUME_REQUIRED")
            updated = PaperAccountSnapshot.model_validate(account.model_dump() | {"kill": level})
            self._append(conn, account_ref, "KILL_STATE", {"actor": actor, "account": updated}, now)
            self._save(conn, updated)

    def resume(
        self,
        account_ref: str,
        *,
        actor: str,
        now: datetime,
        standing_use: Contract | None = None,
    ) -> None:
        """Owner resume to K0. A standing use (ADR-032 OBV2-01) is narrower: it applies
        only to exactly K1 and only if the journal tail is the one its facts were read at;
        the facts are journaled with the resume event."""
        if self.owner_engine is None or not actor or "agent" in actor.lower():
            raise ValueError("PAPER_OWNER_ROLE_REQUIRED")
        with self.owner_engine.begin() as conn:
            row = self._lock(conn, account_ref)
            account = self._account(conn, row)
            journal = self._journal(conn, account_ref)
            if standing_use is not None and (
                account.kill != KillLevel.K1
                or json.loads(standing_use.canonical_bytes()).get("journal_tail_hash")
                != journal[-1]["content_hash"]
            ):
                raise ValueError("PAPER_STANDING_RESUME_SCOPE_DENIED")
            if not account.reconciled or account.unknown_orders or not account.journal_healthy:
                raise ValueError("PAPER_RECONCILIATION_REQUIRED")
            policy = self._pinned_policy(conn, row)
            if (
                self._latest_truth(conn, account_ref) != int(row["truth_cursor"])
                or account.kill == KillLevel.K4
                or not timedelta(0)
                <= now - account.as_of
                <= timedelta(seconds=policy.max_account_age_seconds)
            ):
                raise ValueError("PAPER_RECONCILIATION_REQUIRED")
            daily, daily_cap, drawdown, drawdown_cap = loss_limits(account, policy)
            if daily > daily_cap or drawdown > drawdown_cap:
                raise ValueError("PAPER_LOSS_LIMIT_STILL_ACTIVE")
            edges = [e for e in journal if e["kind"] == "EDGE_STATE"]
            if edges and edges[-1]["data"]["to_state"] != "NORMAL":
                raise ValueError("PAPER_EDGE_SUSPENDED")
            updated = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {
                    "kill": KillLevel.K0,
                }
            )
            data: dict[str, object] = {"actor": actor, "account": updated}
            if standing_use is not None:
                data["standing_use"] = standing_use
            self._append(conn, account_ref, "OWNER_PAPER_RESUME", data, now)
            self._save(conn, updated)

    def roll_day(self, account_ref: str, *, now: datetime, epoch: int | None = None) -> None:
        """Exact-midnight roll, kept for its existing callers; see roll_flat_boundary."""
        now = utc_time(now)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        denied = False
        with self.engine.begin() as conn:
            row = self._lock(conn, account_ref)
            self._fence(account_ref, row, epoch, writer=True)
            account = self._account(conn, row)
            if midnight <= account.day_start_at:
                raise ValueError("UTC_DAY_NOT_ADVANCED")
            policy = self._pinned_policy(conn, row)
            account = self._latch_loss(conn, account, policy, now)
            if (
                now != midnight
                or account.as_of != midnight
                or not account.reconciled
                or account.unknown_orders
                or self._latest_truth(conn, account_ref) != int(row["truth_cursor"])
            ):
                updated = PaperAccountSnapshot.model_validate(
                    account.model_dump()
                    | {"kill": max(account.kill, KillLevel.K1), "reconciled": False}
                )
                self._append(
                    conn,
                    account_ref,
                    "KILL_STATE",
                    {"actor": "deterministic.missing_midnight_truth", "account": updated},
                    now,
                )
                self._save(conn, updated)
                denied = True
            else:
                self._roll_verified_boundary(conn, account, midnight, now)
        if denied:
            raise ValueError("EXACT_FRESH_UTC_BOUNDARY_REQUIRED")

    def roll_flat_boundary(
        self, account_ref: str, *, now: datetime, epoch: int | None = None
    ) -> None:
        """Roll the UTC day at a flat boundary (OBV2-02), at any time of the new day.

        Allowed only when the account is flat, reconciled since the new day's midnight, has
        no unknown order and no active reservation, and no truth fact exists after the last
        reconciliation of the previous day. Equity cannot move while flat without facts, so
        the new day's start equity is the journaled equity, recorded with that proof. Any
        failed condition journals the refusal, sets K1 and raises; nothing is rolled.
        """
        now = utc_time(now)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        refused: list[str] = []
        with self.engine.begin() as conn:
            row = self._lock(conn, account_ref)
            self._fence(account_ref, row, epoch, writer=True)
            account = self._account(conn, row)
            if midnight <= account.day_start_at:
                raise ValueError("UTC_DAY_NOT_ADVANCED")
            account = self._latch_loss(conn, account, self._pinned_policy(conn, row), now)
            journal = self._journal(conn, account_ref)
            latest_truth = self._latest_truth(conn, account_ref)
            prior = next(
                (
                    event
                    for event in reversed(journal)
                    if event["kind"] == "RECONCILIATION" and event["recorded_at"] < midnight
                ),
                None,
            )
            checks = (
                ("NOT_FLAT", bool(account.positions)),
                ("NOT_RECONCILED", not account.reconciled),
                ("UNKNOWN_ORDER", account.unknown_orders),
                ("ACTIVE_RESERVATION", bool(self._reservations(conn, account_ref))),
                ("TRUTH_AFTER_RECONCILIATION", latest_truth != int(row["truth_cursor"])),
                (
                    "NOT_RECONCILED_SINCE_MIDNIGHT",
                    account.as_of < midnight or account.reconciled_at < midnight,
                ),
                ("NO_PRIOR_DAY_RECONCILIATION", prior is None),
            )
            refused = [reason for reason, failed in checks if failed]
            prior_account = (
                PaperAccountSnapshot.model_validate_json(
                    canonical_payload(prior["data"]["account"])
                )
                if prior is not None
                else None
            )
            if prior is not None and prior_account is not None:
                if int(prior["data"]["truth_cursor"]) != latest_truth:
                    refused.append("TRUTH_AFTER_PRIOR_DAY_RECONCILIATION")
                if prior_account.equity != account.equity or prior_account.positions:
                    refused.append("EQUITY_OR_EXPOSURE_CHANGED_WHILE_FLAT")
            if refused:
                updated = PaperAccountSnapshot.model_validate(
                    account.model_dump() | {"kill": max(account.kill, KillLevel.K1)}
                )
                self._append(
                    conn,
                    account_ref,
                    "KILL_STATE",
                    {
                        "actor": "deterministic.flat_boundary_roll_refused",
                        "reasons": refused,
                        "account": updated,
                    },
                    now,
                )
                self._save(conn, updated)
            else:
                assert prior is not None
                updated = PaperAccountSnapshot.model_validate(
                    account.model_dump()
                    | {
                        "day_start_at": midnight,
                        "day_start_equity": account.equity,
                        "day_net_flows": Decimal("0"),
                    }
                )
                self._append(
                    conn,
                    account_ref,
                    "FLAT_BOUNDARY_ROLL",
                    {
                        "prior_day": account,
                        "account": updated,
                        "kill_retained": account.kill,
                        "proof": {
                            "rule": "FLAT_NO_FACT_SINCE_PRIOR_DAY_RECONCILIATION",
                            "prior_reconciliation_event_id": prior["event_id"],
                            "prior_reconciliation_hash": prior["content_hash"],
                            "prior_reconciliation_at": prior["recorded_at"],
                            "truth_cursor": latest_truth,
                            "journaled_equity": account.equity,
                        },
                    },
                    now,
                )
                self._save(conn, updated)
        if refused:
            raise ValueError("FLAT_BOUNDARY_ROLL_REFUSED:" + ",".join(refused))

    def _latch_loss(
        self, conn: Connection, account: PaperAccountSnapshot, policy: PaperPolicy, now: datetime
    ) -> PaperAccountSnapshot:
        daily, daily_cap, drawdown, drawdown_cap = loss_limits(account, policy)
        causes = tuple(
            reason
            for reason, breached in (
                ("DAILY_LOSS_CAP", daily > daily_cap),
                ("DRAWDOWN_CAP", drawdown > drawdown_cap),
            )
            if breached
        )
        if not causes:
            return account
        updated = PaperAccountSnapshot.model_validate(
            account.model_dump() | {"kill": max(account.kill, KillLevel.K2)}
        )
        previous = [
            event
            for event in self._journal(conn, account.account_ref)
            if event["kind"] == "LOSS_BREACH_LATCH"
        ]
        if (
            not previous
            or previous[-1]["data"]["day_start_at"] != canonical_payload(account.day_start_at)[1:-1]
            or tuple(previous[-1]["data"]["causes"]) != causes
            or account.kill < KillLevel.K2
        ):
            self._append(
                conn,
                account.account_ref,
                "LOSS_BREACH_LATCH",
                {
                    "account": updated,
                    "causes": causes,
                    "daily_marked_loss": daily,
                    "high_water_drawdown": drawdown,
                    "day_start_at": account.day_start_at,
                    "policy_hash": policy.content_hash(),
                    "explicit_owner_resume_required": True,
                },
                now,
            )
        return updated

    def _roll_verified_boundary(
        self, conn: Connection, account: PaperAccountSnapshot, midnight: datetime, now: datetime
    ) -> None:
        updated = PaperAccountSnapshot.model_validate(
            account.model_dump()
            | {
                "as_of": now,
                "day_start_at": midnight,
                "day_start_equity": account.equity,
                "day_net_flows": Decimal("0"),
            }
        )
        self._append(
            conn,
            account.account_ref,
            "UTC_DAY_ROLLOVER",
            {"prior_day": account, "account": updated, "kill_retained": account.kill},
            now,
        )
        self._save(conn, updated)

    @staticmethod
    def _quarantined(journal: list[dict[str, Any]]) -> set[str]:
        return {
            str(event["data"]["truth_content_hash"])
            for event in journal
            if event["kind"] == "TRUTH_QUARANTINE"
        }

    @staticmethod
    def _database_clock_untrusted(conn: Connection, policy: PaperPolicy, now: datetime) -> bool:
        database_now = utc_time(conn.scalar(text("SELECT clock_timestamp()")))
        return abs(now - database_now) > timedelta(milliseconds=policy.max_store_clock_skew_ms)

    def _untrusted_inputs(
        self,
        conn: Connection,
        history: _VerifiedJournal,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        *,
        now: datetime,
    ) -> set[PaperReason]:
        """P-3/OBV2-07: market and specification must equal stored, reconciled truth facts.

        A fact counts only if its row digest verifies, it was consumed by a reconciliation
        (at or below the cursor), it is not quarantined and it was recorded by `now`.
        The caller's `now` must lie within the policy's bound of the database clock.
        """
        account_ref = history.account_ref
        reasons: set[PaperReason] = set()
        if self._database_clock_untrusted(conn, policy, now):
            reasons.add(PaperReason.CLOCK_UNTRUSTED)
        try:
            # Roundtrip rejects model_construct/model_copy bypasses before any hashing.
            market = PaperMarketSnapshot.model_validate_json(
                market.model_dump_json(warnings="error")
            )
            spec = PaperInstrumentSpec.model_validate_json(spec.model_dump_json(warnings="error"))
        except (ValueError, TypeError):
            # The kernel already denies such input as INVALID_INPUT; it is also unverified.
            return reasons | {PaperReason.MARKET_UNVERIFIED, PaperReason.SPEC_UNOBSERVED}
        quarantined = self._quarantined(history.for_scope(conn, account_ref))
        rows = conn.execute(
            text(
                "SELECT t.* FROM paper_truth_event t JOIN paper_account a "
                "ON a.account_ref=t.account_ref WHERE t.account_ref=:a "
                "AND t.kind IN ('MARKET_MARK','SPEC_OBSERVATION') AND t.sequence<=a.truth_cursor "
                "AND t.payload::jsonb #>> '{data,instrument_id}'=:i ORDER BY t.sequence"
            ),
            {"a": account_ref, "i": market.instrument_id},
        ).mappings()
        marks: set[str] = set()
        specs: set[str] = set()
        for row in rows:
            payload = str(row["payload"])
            envelope = json.loads(payload)
            if (
                digest(payload) != row["content_hash"]
                or envelope["kind"] != row["kind"]
                or envelope["account_ref"] != account_ref
            ):
                raise ValueError("CORRUPT_PAPER_TRUTH")
            if row["content_hash"] in quarantined or row["recorded_at"] > now:
                continue
            if row["kind"] == "MARKET_MARK":
                marks.add(
                    PaperMarketSnapshot.model_validate_json(
                        canonical_payload(envelope["data"])
                    ).content_hash()
                )
            else:
                specs.add(
                    PaperInstrumentSpec.model_validate_json(
                        canonical_payload(envelope["data"])
                    ).content_hash()
                )
        if market.content_hash() not in marks:
            reasons.add(PaperReason.MARKET_UNVERIFIED)
        if spec.content_hash() not in specs or spec.instrument_id != market.instrument_id:
            reasons.add(PaperReason.SPEC_UNOBSERVED)
        return reasons

    def authorize(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        now: datetime,
        epoch: int | None = None,
    ) -> Submission:
        intent = PaperIntent.model_validate_json(intent.canonical_bytes())
        now = utc_time(now)
        with self.engine.begin() as conn:
            row = self._lock(conn, intent.account_ref)
            self._fence(intent.account_ref, row, epoch, writer=True)
            history = _VerifiedJournal(
                conn,
                conn.get_transaction(),
                intent.account_ref,
                self._journal(conn, intent.account_ref),
            )
            account = self._account(conn, row, history=history)
            reservations = self._reservations(conn, intent.account_ref, history=history)
            policy_stored = conn.scalar(
                text("SELECT payload FROM paper_policy WHERE content_hash=:h"),
                {"h": row["policy_hash"]},
            )
            release_stored = conn.scalar(
                text("SELECT payload FROM paper_release WHERE content_hash=:h"),
                {"h": row["release_hash"]},
            )
            if (
                digest(str(policy_stored)) != row["policy_hash"]
                or digest(str(release_stored)) != row["release_hash"]
            ):
                raise ValueError("CORRUPT_PAPER_CONFIGURATION")
            current_policy = PaperPolicy.model_validate_json(str(policy_stored))
            current_release = Release.model_validate_json(str(release_stored))
            decision = assess_paper(
                intent,
                current_policy,
                market,
                spec,
                account,
                current_release,
                reservations,
                now=now,
            )
            extra = set(decision.reasons)
            if intent.action == MoneyAction.OPEN and (
                intent.position_ref is not None
                or any(
                    p.position_ref == paper_position_ref(intent.account_ref, intent.intent_id)
                    for p in account.positions
                )
            ):
                extra.add(PaperReason.DUPLICATE_INTENT)
            if current_policy.input_trust == "STORE_VERIFIED":
                extra |= self._untrusted_inputs(
                    conn, history, current_policy, market, spec, now=now
                )
            if self._latest_truth(conn, intent.account_ref) != int(row["truth_cursor"]):
                extra.add(PaperReason.ACCOUNT_UNRECONCILED)
                account = PaperAccountSnapshot.model_validate(
                    account.model_dump()
                    | {"reconciled": False, "kill": max(account.kill, KillLevel.K1)}
                )
                self._append(
                    conn,
                    intent.account_ref,
                    "KILL_STATE",
                    {"actor": "deterministic.unconsumed_truth", "account": account},
                    now,
                    history=history,
                )
                self._save(conn, account)
            edge = [
                e for e in history.for_scope(conn, intent.account_ref) if e["kind"] == "EDGE_STATE"
            ]
            if (
                edge
                and edge[-1]["data"]["to_state"] in ("SUSPEND", "INVESTIGATE")
                and intent.action in (MoneyAction.OPEN, MoneyAction.AMEND)
            ):
                extra.add(PaperReason.RELEASE_INELIGIBLE)
            if (
                policy.content_hash() != row["policy_hash"]
                or release.content_hash() != row["release_hash"]
            ):
                extra.add(PaperReason.HASH_MISMATCH)
            depth = conn.scalar(
                text(
                    "SELECT count(*) FROM paper_outbox WHERE account_ref=:a "
                    "AND state NOT IN ('FILLED','CANCELED','EXPIRED','REJECTED')"
                ),
                {"a": intent.account_ref},
            )
            if int(depth or 0) >= current_policy.max_queue_depth:
                extra.add(PaperReason.ORDER_RATE_CAP)
            if extra:
                decision = PaperDecision.model_validate(
                    decision.model_dump()
                    | {
                        "status": "DENIED",
                        "reasons": tuple(r for r in PaperReason if r in extra),
                        "exposure": None,
                    }
                )
            if decision.status == "DENIED":
                if (
                    PaperReason.DAILY_LOSS_CAP in decision.reasons
                    or PaperReason.DRAWDOWN_CAP in decision.reasons
                ):
                    account = PaperAccountSnapshot.model_validate(
                        account.model_dump() | {"kill": max(account.kill, KillLevel.K2)}
                    )
                    self._append(
                        conn,
                        intent.account_ref,
                        "KILL_STATE",
                        {"actor": "deterministic.loss_cap", "account": account},
                        now,
                        history=history,
                    )
                    self._save(conn, account)
                payload = canonical_payload(
                    {
                        "intent": intent,
                        "decision": decision,
                        "policy_version": current_policy.version,
                        "spec_version": spec.spec_version,
                    }
                )
                conn.execute(
                    text("INSERT INTO paper_denial VALUES (:id,:a,:i,:h,:p,:at)"),
                    {
                        "id": str(uuid4()),
                        "a": intent.account_ref,
                        "i": intent.content_hash(),
                        "h": digest(payload),
                        "p": payload,
                        "at": now,
                    },
                )
                self._append(
                    conn, intent.account_ref, "DENIED", json.loads(payload), now, history=history
                )
                return Submission(decision)
            exposure = decision.exposure
            assert exposure is not None
            reservation = PaperReservation(
                reservation_id=uuid4(),
                intent_hash=intent.content_hash(),
                intent_id=intent.intent_id,
                logical_key=intent.logical_key,
                account_ref=intent.account_ref,
                instrument_id=intent.instrument_id,
                bucket=exposure.bucket,
                action=intent.action,
                quantity=exposure.quantity,
                notional=exposure.notional,
                modeled_loss=exposure.modeled_loss,
                margin=exposure.margin_required,
                position_ref=intent.position_ref,
                target_intent_ref=intent.target_intent_ref,
                created_at=now,
                expires_at=intent.expires_at,
            )
            authorization = bind_authorization(
                decision, intent, account, reservation.reservation_id, uuid4(), now
            )
            ih = intent.content_hash()
            conn.execute(
                text(
                    "INSERT INTO paper_intent "
                    "(intent_hash,account_ref,logical_key,action,payload,recorded_at,"
                    "generated_position_ref) "
                    "VALUES (:i,:a,:l,:act,:p,:at,:position)"
                ),
                {
                    "i": ih,
                    "a": intent.account_ref,
                    "l": intent.logical_key,
                    "act": intent.action.value,
                    "p": intent.canonical_bytes().decode(),
                    "at": now,
                    "position": paper_position_ref(intent.account_ref, intent.intent_id)
                    if intent.action == MoneyAction.OPEN
                    else None,
                },
            )
            conn.execute(
                text("INSERT INTO paper_authorization VALUES (:id,:i,:h,:p)"),
                {
                    "id": str(authorization.authorization_id),
                    "i": ih,
                    "h": authorization.content_hash(),
                    "p": authorization.canonical_bytes().decode(),
                },
            )
            conn.execute(
                text("INSERT INTO paper_reservation VALUES (:i,:a,:p,true)"),
                {"i": ih, "a": intent.account_ref, "p": reservation.canonical_bytes().decode()},
            )
            conn.execute(
                text(
                    "INSERT INTO paper_outbox "
                    "(intent_hash,account_ref,writer_epoch,state,updated_at) "
                    "VALUES (:i,:a,:e,'RESERVED',:at)"
                ),
                {"i": ih, "a": intent.account_ref, "e": account.epoch, "at": now},
            )
            self._append(
                conn,
                intent.account_ref,
                "AUTHORIZED",
                {
                    "intent": intent,
                    "authorization": authorization,
                    "reservation": reservation,
                    "account": account,
                    "market": market,
                    "spec": spec,
                },
                now,
                ih,
                history=history,
            )
            return Submission(decision, authorization, reservation)

    def outbox(self, intent_hash: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            return dict(
                conn.execute(
                    text("SELECT * FROM paper_outbox WHERE intent_hash=:i"), {"i": intent_hash}
                )
                .mappings()
                .one()
            )

    @staticmethod
    def _intent(conn: Connection, intent_hash: str) -> PaperIntent:
        payload = conn.scalar(
            text("SELECT payload FROM paper_intent WHERE intent_hash=:i"), {"i": intent_hash}
        )
        intent = PaperIntent.model_validate_json(str(payload))
        if intent.content_hash() != intent_hash:
            raise ValueError("CORRUPT_PAPER_INTENT")
        return intent

    def claim(
        self,
        intent_hash: str,
        epoch: int,
        *,
        now: datetime,
        authorization: PaperAuthorization | None = None,
    ) -> PaperAuthorization:
        with self.engine.begin() as conn:
            intent = self._intent(conn, intent_hash)
            row = self._lock(conn, intent.account_ref)
            account = self._account(conn, row)
            journal = self._journal(conn, intent.account_ref)
            auth_row = (
                conn.execute(
                    text("SELECT * FROM paper_authorization WHERE intent_hash=:i"),
                    {"i": intent_hash},
                )
                .mappings()
                .one()
            )
            auth = PaperAuthorization.model_validate_json(str(auth_row["payload"]))
            if auth.content_hash() != auth_row["content_hash"] or (
                authorization is not None and authorization.content_hash() != auth.content_hash()
            ):
                raise ValueError("ALTERED_PAPER_AUTHORIZATION")
            original = next(
                e["data"]
                for e in journal
                if e["kind"] == "AUTHORIZED" and e["intent_hash"] == intent_hash
            )
            reservation = next(
                (
                    r
                    for r in self._reservations(conn, intent.account_ref)
                    if r.intent_hash == intent_hash
                ),
                None,
            )
            original_reservation = PaperReservation.model_validate_json(
                canonical_payload(original["reservation"])
            )
            if (
                reservation != original_reservation
                or reservation is None
                or (
                    reservation.reservation_id != auth.reservation_id
                    or reservation.quantity != auth.exposure.quantity
                )
            ):
                raise ValueError("PAPER_RESERVATION_BINDING_DENIED")
            bound_account = PaperAccountSnapshot.model_validate_json(
                canonical_payload(original["account"])
            )
            market = PaperMarketSnapshot.model_validate_json(canonical_payload(original["market"]))
            spec = PaperInstrumentSpec.model_validate_json(canonical_payload(original["spec"]))
            policy_payload = conn.scalar(
                text("SELECT payload FROM paper_policy WHERE content_hash=:h"),
                {"h": row["policy_hash"]},
            )
            policy = PaperPolicy.model_validate_json(str(policy_payload))
            release_payload = conn.scalar(
                text("SELECT payload FROM paper_release WHERE content_hash=:h"),
                {"h": row["release_hash"]},
            )
            release = Release.model_validate_json(str(release_payload))
            latest_truth = int(
                conn.scalar(
                    text(
                        "SELECT COALESCE(max(sequence),0) FROM paper_truth_event "
                        "WHERE account_ref=:a"
                    ),
                    {"a": intent.account_ref},
                )
                or 0
            )
            state = conn.scalar(
                text("SELECT state FROM paper_outbox WHERE intent_hash=:i"), {"i": intent_hash}
            )
            raw_current = PaperAccountSnapshot.model_validate_json(str(row["payload"]))
            bound_base = PaperAccountSnapshot.model_validate(
                bound_account.model_dump()
                | {
                    "prior_logical_keys": raw_current.prior_logical_keys,
                    "recent_intent_times": raw_current.recent_intent_times,
                    "prior_intent_ids": raw_current.prior_intent_ids,
                }
            )
            if (
                epoch != account.epoch
                or auth.writer_epoch != epoch
                or state != "RESERVED"
                or not auth.issued_at <= now < auth.expires_at
                or row["policy_hash"] != auth.policy_hash
                or row["release_hash"] != auth.release_hash
                or bound_base.content_hash() != raw_current.content_hash()
                or not account.reconciled
                or account.unknown_orders
                or not account.journal_healthy
                or (
                    intent.action in (MoneyAction.OPEN, MoneyAction.AMEND)
                    and account.kill != KillLevel.K0
                )
                or account.kill == KillLevel.K4
                or latest_truth != int(row["truth_cursor"])
                or (now - market.as_of).total_seconds() > policy.max_market_age_seconds
                or now < market.available_at
                or (now - account.as_of).total_seconds() > policy.max_account_age_seconds
                or now < spec.observed_at
                or (now - spec.observed_at).total_seconds() > policy.max_spec_age_seconds
                or market.fx_as_of is None
                or (now - market.fx_as_of).total_seconds() > policy.max_fx_age_seconds
                or (
                    policy.input_trust == "STORE_VERIFIED"
                    and self._database_clock_untrusted(conn, policy, now)
                )
            ):
                raise ValueError("PAPER_DISPATCH_BINDING_OR_FRESHNESS_DENIED")
            # Authorization and original immutable calculation inputs are revalidated;
            # capacity remains held by this exact persisted reservation.
            if (
                auth.intent_hash != intent_hash
                or auth.account_snapshot_hash != bound_account.content_hash()
                or auth.market_hash != market.content_hash()
                or auth.spec_hash != spec.content_hash()
            ):
                raise ValueError("PAPER_AUTHORIZATION_BINDING_DENIED")
            if not verify_authorization(
                auth,
                intent,
                policy,
                market,
                spec,
                bound_account,
                release,
                reservation,
                now=now,
                reservations=self._reservations(conn, intent.account_ref),
            ):
                raise ValueError("PAPER_CURRENT_RISK_RECHECK_DENIED")
            # The journal event precedes the state change it justifies (0007 guard).
            self._append(
                conn,
                intent.account_ref,
                "DISPATCH_ATTEMPT",
                {"epoch": epoch, "authorization": auth},
                now,
                intent_hash,
            )
            conn.execute(
                text(
                    "UPDATE paper_outbox SET state='SENT_PENDING',attempts=1,updated_at=:at "
                    "WHERE intent_hash=:i"
                ),
                {"at": now, "i": intent_hash},
            )
            return auth

    def mark_unknown(self, intent_hash: str, epoch: int, *, now: datetime) -> None:
        with self.engine.begin() as conn:
            intent = self._intent(conn, intent_hash)
            account = self._account(conn, self._lock(conn, intent.account_ref))
            if account.epoch != epoch:
                raise ValueError("STALE_PAPER_WRITER")
            state = conn.scalar(
                text("SELECT state FROM paper_outbox WHERE intent_hash=:i"), {"i": intent_hash}
            )
            if state not in ("SENT_PENDING", "ACKNOWLEDGED", "PARTIALLY_FILLED", "UNKNOWN"):
                raise ValueError("UNKNOWN_REQUIRES_ATTEMPT")
            reservation = next(
                r
                for r in self._reservations(conn, intent.account_ref)
                if r.intent_hash == intent_hash
            )
            # UNKNOWN retains original worst-case capacity even following a partial.
            auth_payload = conn.scalar(
                text("SELECT payload FROM paper_authorization WHERE intent_hash=:i"),
                {"i": intent_hash},
            )
            auth = PaperAuthorization.model_validate_json(str(auth_payload))
            reservation = PaperReservation.model_validate(
                reservation.model_dump()
                | {
                    "state": "UNKNOWN",
                    "quantity": auth.exposure.quantity,
                    "notional": auth.exposure.notional,
                    "modeled_loss": auth.exposure.modeled_loss,
                    "margin": auth.exposure.margin_required,
                }
            )
            updated = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {
                    "reconciled": False,
                    "unknown_orders": True,
                    "kill": max(account.kill, KillLevel.K1),
                }
            )
            # The journal event precedes every state change it justifies (0007 guards).
            self._append(
                conn,
                intent.account_ref,
                "UNKNOWN_RECONCILE_ONLY",
                {"account": updated, "reservation": reservation},
                now,
                intent_hash,
            )
            conn.execute(
                text("UPDATE paper_outbox SET state='UNKNOWN',updated_at=:at WHERE intent_hash=:i"),
                {"at": now, "i": intent_hash},
            )
            conn.execute(
                text("UPDATE paper_reservation SET payload=:p WHERE intent_hash=:i"),
                {"p": reservation.canonical_bytes().decode(), "i": intent_hash},
            )
            self._save(conn, updated)

    def dispatch(
        self, intent_hash: str, epoch: int, truth: PaperTruth, *, now: datetime, fault: str = "NONE"
    ) -> str:
        auth = self.claim(intent_hash, epoch, now=now)
        with self.engine.connect() as conn:
            intent = self._intent(conn, intent_hash)
        truth.record_order(intent, now=now, writer_epoch=epoch, quantity=auth.exposure.quantity)
        original = next(
            e["data"]
            for e in self.journal(intent.account_ref)
            if e["kind"] == "AUTHORIZED" and e["intent_hash"] == intent_hash
        )
        truth.mark(
            intent.account_ref,
            PaperMarketSnapshot.model_validate_json(canonical_payload(original["market"])),
            now=now,
        )
        if fault in ("LOST_RESPONSE", "CRASH_AFTER_SEND"):
            self.mark_unknown(intent_hash, epoch, now=now)
            if fault == "CRASH_AFTER_SEND":
                raise RuntimeError("SIMULATED_CRASH_AFTER_SEND")
            return "UNKNOWN"
        truth.status(intent_hash, "ACKNOWLEDGED", account_ref=intent.account_ref, now=now)
        self.reconcile(intent.account_ref, now=now)
        return str(self.outbox(intent_hash)["state"])

    def journal(self, account_ref: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return self._journal(conn, account_ref)

    @staticmethod
    def _production_history(conn: Connection, release_id: str) -> tuple[Release, ...]:
        """A current production state exists only as a complete immutable chain."""
        snapshots = list(
            conn.execute(
                text(
                    "SELECT * FROM paper_production_release WHERE payload::jsonb->>'release_id'=:id"
                ),
                {"id": release_id},
            ).mappings()
        )
        if not snapshots:
            return ()
        records = list(
            conn.execute(
                text(
                    "SELECT history.* FROM paper_production_lifecycle history "
                    "JOIN paper_production_release snapshot "
                    "ON snapshot.content_hash=history.release_hash "
                    "WHERE snapshot.payload::jsonb->>'release_id'=:id ORDER BY history.sequence"
                ),
                {"id": release_id},
            ).mappings()
        )
        if len(records) != len(snapshots):
            raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
        by_hash: dict[str, Release] = {}
        snapshot_times: dict[str, datetime] = {}
        try:
            for row in snapshots:
                release = Release.model_validate_json(str(row["payload"]))
                validate_registry_release(release, fixture_registry=False, now=row["recorded_at"])
                if (
                    release.release_id != release_id
                    or release.content_hash() != row["content_hash"]
                    or digest(str(row["payload"])) != row["content_hash"]
                    or release.created_at > row["recorded_at"]
                    or (release.updated_at is not None and release.updated_at != row["recorded_at"])
                ):
                    raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
                by_hash[str(row["content_hash"])] = release
                snapshot_times[str(row["content_hash"])] = row["recorded_at"]
            chain: list[Release] = []
            seen: set[str] = set()
            previous_recorded_at: datetime | None = None
            for row in records:
                release_hash = str(row["release_hash"])
                release = by_hash[release_hash]
                payload = str(row["payload"])
                if (
                    digest(payload) != row["content_hash"]
                    or release_hash in seen
                    or row["recorded_at"] != snapshot_times[release_hash]
                    or (
                        previous_recorded_at is not None
                        and row["recorded_at"] < previous_recorded_at
                    )
                ):
                    raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
                if not chain:
                    validate_initial_release(release, fixture_registry=False)
                    if payload != release.canonical_bytes().decode():
                        raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
                else:
                    event = ReleaseTransition.model_validate_json(payload)
                    validate_release_transition(chain[-1], release, event)
                    if event.recorded_at != row["recorded_at"]:
                        raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
                    if (
                        chain[-1].state == ReleaseState.SUSPENDED
                        and release.state == ReleaseState.PAPER
                        and not any(item.state == ReleaseState.PAPER for item in chain)
                    ):
                        raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
                seen.add(release_hash)
                chain.append(release)
                previous_recorded_at = row["recorded_at"]
            if seen != set(by_hash):
                raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY")
            return tuple(chain)
        except (ValueError, KeyError) as exc:
            raise ValueError("CORRUPT_PRODUCTION_RELEASE_HISTORY") from exc

    def current_release(self, release_id: str) -> Release:
        """Derive the current production snapshot after validating its entire history."""
        with self.engine.begin() as conn:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:id,20801502))"),
                {"id": release_id},
            )
            chain = self._production_history(conn, release_id)
            if not chain:
                raise ValueError("UNKNOWN_RELEASE_IDENTITY")
            return chain[-1]

    def register_release(
        self,
        release: Release,
        *,
        now: datetime,
        transition: ReleaseTransition | None = None,
        fixture_registry: bool = False,
    ) -> None:
        if self.owner_engine is None:
            raise ValueError("PAPER_OWNER_ROLE_REQUIRED")
        now = utc_time(now)
        release = Release.model_validate_json(release.canonical_bytes())
        validate_registry_release(release, fixture_registry=fixture_registry, now=now)
        table = "paper_release" if fixture_registry else "paper_production_release"
        history = "paper_lifecycle" if fixture_registry else "paper_production_lifecycle"
        with self.owner_engine.begin() as conn:
            if not fixture_registry:
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:id,20801502))"),
                    {"id": release.release_id},
                )
                chain = self._production_history(conn, release.release_id)
                if not chain:
                    if transition is not None:
                        raise ValueError("RELEASE_TRANSITION_REQUIRES_HISTORY")
                    validate_initial_release(release, fixture_registry=False)
                    if release.created_at > now:
                        raise ValueError("RELEASE_HISTORY_BINDING_DENIED")
                else:
                    if transition is None:
                        raise ValueError("RELEASE_IDENTITY_ALREADY_REGISTERED")
                    transition = ReleaseTransition.model_validate_json(transition.canonical_bytes())
                    if transition.release_id != release.release_id:
                        raise ValueError("RELEASE_HISTORY_BINDING_DENIED")
                    if transition.prior_hash != chain[-1].content_hash():
                        raise ValueError("RELEASE_CURRENT_STATE_MISMATCH")
                    prior_recorded_at = conn.scalar(
                        text(
                            "SELECT recorded_at FROM paper_production_release WHERE content_hash=:h"
                        ),
                        {"h": chain[-1].content_hash()},
                    )
                    if (
                        transition.recorded_at != now
                        or prior_recorded_at is None
                        or now < prior_recorded_at
                    ):
                        raise ValueError("RELEASE_HISTORY_BINDING_DENIED")
                    validate_release_transition(chain[-1], release, transition)
                    if (
                        chain[-1].state == ReleaseState.SUSPENDED
                        and release.state == ReleaseState.PAPER
                        and not any(item.state == ReleaseState.PAPER for item in chain)
                    ):
                        raise ValueError("PRODUCTION_PAPER_HISTORY_REQUIRED")
            elif transition is not None:
                prior_payload = conn.scalar(
                    text(f"SELECT payload FROM {table} WHERE content_hash=:h"),
                    {"h": transition.prior_hash},
                )
                if prior_payload is None:
                    raise ValueError("RELEASE_HISTORY_BINDING_DENIED")
                prior = Release.model_validate_json(str(prior_payload))
                validate_release_transition(prior, release, transition)
            conn.execute(
                text(f"INSERT INTO {table} VALUES (:h,:p,:at)"),
                {"h": release.content_hash(), "p": release.canonical_bytes().decode(), "at": now},
            )
            payload = (transition or release).canonical_bytes().decode()
            conn.execute(
                text(
                    f"INSERT INTO {history}(release_hash,payload,content_hash,recorded_at) "
                    "VALUES (:r,:p,:h,:at)"
                ),
                {"r": release.content_hash(), "p": payload, "h": digest(payload), "at": now},
            )
            if not fixture_registry:
                self._production_history(conn, release.release_id)

    def set_edge(self, account_ref: str, transition: EdgeTransition, *, now: datetime) -> None:
        relaxing = transition.to_state == EdgeState.NORMAL or (
            transition.from_state in (EdgeState.SUSPEND, EdgeState.INVESTIGATE)
            and transition.to_state not in (EdgeState.SUSPEND, EdgeState.INVESTIGATE)
        )
        if relaxing and (self.owner_engine is None or transition.actor_role != "OWNER"):
            raise ValueError("EDGE_OWNER_RESUME_REQUIRED")
        engine = self.owner_engine if relaxing else self.engine
        assert engine is not None
        with engine.begin() as conn:
            row = self._lock(conn, account_ref)
            if not relaxing:
                self._fence(account_ref, row, None, writer=False)
            account = self._account(conn, row)
            release = Release.model_validate_json(
                str(
                    conn.scalar(
                        text("SELECT payload FROM paper_release WHERE content_hash=:h"),
                        {"h": row["release_hash"]},
                    )
                )
            )
            prior = [e for e in self._journal(conn, account_ref) if e["kind"] == "EDGE_STATE"]
            current = EdgeState(prior[-1]["data"]["to_state"]) if prior else EdgeState.NORMAL
            if transition.from_state != current or transition.recorded_at != now:
                raise ValueError("EDGE_HISTORY_BINDING_DENIED")
            fixture_edge_transition(release, transition)
            self._append(conn, account_ref, "EDGE_STATE", transition, now)
            if transition.to_state != EdgeState.NORMAL:
                updated = PaperAccountSnapshot.model_validate(
                    account.model_dump() | {"kill": max(account.kill, KillLevel.K1)}
                )
                self._append(
                    conn,
                    account_ref,
                    "KILL_STATE",
                    {"actor": "deterministic.edge_fixture", "account": updated},
                    now,
                )
                self._save(conn, updated)

    def activate_release(
        self, account_ref: str, release: Release, *, actor: str, now: datetime
    ) -> None:
        if self.owner_engine is None or "agent" in actor.lower():
            raise ValueError("PAPER_OWNER_ROLE_REQUIRED")
        with self.owner_engine.begin() as conn:
            row = self._lock(conn, account_ref)
            if not conn.scalar(
                text("SELECT 1 FROM paper_release WHERE content_hash=:h"),
                {"h": release.content_hash()},
            ):
                raise ValueError("UNREGISTERED_FIXTURE_RELEASE")
            account = self._account(conn, row)
            updated = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {"kill": max(account.kill, KillLevel.K1), "reconciled": False}
            )
            self._append(
                conn,
                account_ref,
                "OWNER_RELEASE_PIN",
                {"actor": actor, "release_hash": release.content_hash(), "account": updated},
                now,
            )
            self._save(conn, updated, release_hash=release.content_hash())

    def activate_policy(
        self, account_ref: str, policy: PaperPolicy, *, actor: str, now: datetime
    ) -> None:
        if self.owner_engine is None or "agent" in actor.lower():
            raise ValueError("PAPER_OWNER_ROLE_REQUIRED")
        policy = PaperPolicy.model_validate_json(policy.canonical_bytes())
        with self.owner_engine.begin() as conn:
            row = self._lock(conn, account_ref)
            account = self._account(conn, row)
            conn.execute(
                text("INSERT INTO paper_policy VALUES (:h,:p,:at) ON CONFLICT DO NOTHING"),
                {"h": policy.content_hash(), "p": policy.canonical_bytes().decode(), "at": now},
            )
            updated = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {"kill": max(account.kill, KillLevel.K1), "reconciled": False}
            )
            self._append(
                conn,
                account_ref,
                "OWNER_POLICY_PIN",
                {"actor": actor, "policy_hash": policy.content_hash(), "account": updated},
                now,
            )
            self._save(conn, updated, policy_hash=policy.content_hash())

    def reconcile(self, account_ref: str, *, now: datetime, epoch: int | None = None) -> bool:
        return self._reconcile(account_ref, now=utc_time(now), epoch=epoch)

    @staticmethod
    def _apply_truth(
        fold: _TruthFold,
        event: dict[str, Any],
        accepted: list[dict[str, Any]],
        bound: dict[str, _Bound],
        baseline: PaperAccountSnapshot,
        day_start_at: datetime,
        cursor: int,
        account_ref: str,
    ) -> None:
        """Apply one truth fact to `fold`; any invalid fact raises before it is accepted."""
        ih = str(event["intent_hash"])
        data = event["data"]
        kind = event["kind"]
        if kind == "ORDER":
            if ih not in bound:
                raise ValueError("UNBOUND_VIRTUAL_ORDER")
            order_intent = bound[ih].intent
            if order_intent.action == MoneyAction.OPEN and (
                order_intent.position_ref is not None
                or paper_position_ref(account_ref, order_intent.intent_id) in fold.positions
            ):
                raise ValueError("OPEN_POSITION_IDENTITY_COLLISION")
            fold.orders[ih] = data
        elif kind == "FILL":
            if ih not in bound or ih not in fold.orders:
                raise ValueError("UNBOUND_VIRTUAL_FILL")
            intent = bound[ih].intent
            auth = bound[ih].authorization
            spec = bound[ih].spec
            q, price = Decimal(str(data["quantity"])), Decimal(str(data["price"]))
            if not q.is_finite() or not price.is_finite() or q <= 0 or price <= 0:
                raise ValueError("CORRUPT_VIRTUAL_FILL")
            fx = bound[ih].market.adverse_fx
            if fx is None:
                raise ValueError("VIRTUAL_FX_UNKNOWN")
            total = auth.exposure.quantity
            prior_fills = sum(
                (Decimal(str(fill["quantity"])) for fill in fold.fills.get(ih, [])), Decimal("0")
            )
            if prior_fills + q > total:
                raise ValueError("VIRTUAL_OVERFILL_OR_UNBOUND_FILL")
            costs = (
                auth.exposure.modeled_loss
                if intent.action == MoneyAction.CLOSE
                else max(
                    Decimal("0"),
                    auth.exposure.modeled_loss
                    - total * spec.contract_multiplier * abs(intent.entry - intent.stop) * fx,
                )
            )
            fee = bounded_amount(costs * q / total, ceiling=True) if total else Decimal("0")
            value = q * price * spec.contract_multiplier * fx
            if intent.action == MoneyAction.OPEN:
                if intent.position_ref is not None:
                    raise ValueError("OPEN_REQUIRES_NEW_POSITION")
                ref = paper_position_ref(account_ref, intent.intent_id)
                old = fold.positions.get(ref)
                if old is not None and fold.owners.get(ref) != ih:
                    raise ValueError("OPEN_POSITION_IDENTITY_COLLISION")
                if old is not None and (
                    old.instrument_id != intent.instrument_id
                    or old.bucket != auth.exposure.bucket
                    or old.stop_price != intent.stop
                    or old.multiplier != spec.contract_multiplier
                ):
                    raise ValueError("OPEN_BOUND_POSITION_FIELDS_CHANGED")
                fold.owners[ref] = ih
                qty = q + (old.quantity if old else Decimal("0"))
                entry = (
                    q * price + (old.quantity * old.entry_price if old else Decimal("0"))
                ) / qty
                fold.positions[ref] = PaperPosition(
                    position_ref=ref,
                    instrument_id=intent.instrument_id,
                    bucket=auth.exposure.bucket,
                    quantity=qty,
                    entry_price=bounded_amount(entry, ceiling=True),
                    mark_price=price,
                    stop_price=intent.stop,
                    multiplier=spec.contract_multiplier,
                    adverse_fx=fx,
                    modeled_costs=bounded_amount(
                        (old.modeled_costs if old else Decimal("0")) + fee, ceiling=True
                    ),
                    margin_used=bounded_amount(
                        (old.margin_used if old else Decimal("0"))
                        + auth.exposure.margin_required * q / total,
                        ceiling=True,
                    ),
                )
                fold.cash = bounded_amount(fold.cash - value - fee)
            elif intent.action == MoneyAction.CLOSE:
                ref = str(intent.position_ref)
                if ref not in fold.positions or q > fold.positions[ref].quantity:
                    raise ValueError("VIRTUAL_OVER_CLOSE_OR_UNKNOWN_POSITION")
                old = fold.positions[ref]
                remaining = old.quantity - q
                if remaining:
                    fold.positions[ref] = PaperPosition.model_validate(
                        old.model_dump()
                        | {
                            "quantity": remaining,
                            "margin_used": bounded_amount(
                                old.margin_used * remaining / old.quantity, ceiling=True
                            ),
                            "modeled_costs": bounded_amount(
                                old.modeled_costs * remaining / old.quantity, ceiling=True
                            ),
                        }
                    )
                else:
                    del fold.positions[ref]
                fold.cash = bounded_amount(fold.cash + value - fee)
            else:
                raise ValueError("VIRTUAL_FILL_FOR_NONFILL_ACTION")
            if fold.cash < 0:
                raise ValueError("VIRTUAL_NEGATIVE_CASH")
            fold.fills.setdefault(ih, []).append(data)
        elif kind == "STATUS":
            status = str(data["status"])
            if status == "REJECTED":
                fold.rejected.add(ih)
            # A late acknowledgment cannot overwrite a terminal virtual fact.
            if fold.statuses.get(ih) not in ("CANCELED", "EXPIRED", "REJECTED"):
                fold.statuses[ih] = status
        elif kind == "RESOLUTION":
            validate_resolution(list(accepted), ih, data)
            fold.resolutions[ih] = data
        elif kind == "EXTERNAL_POSITION":
            p = PaperPosition.model_validate_json(canonical_payload(data))
            validate_position_mark(
                p, event["recorded_at"], list(accepted), baseline_positions=baseline.positions
            )
            fold.positions[p.position_ref] = p
            fold.owners[p.position_ref] = None
            original_mark = ObservedMark.from_position(p)
            candidate_mark = (
                ObservedMark(
                    original_mark.price,
                    original_mark.adverse_fx,
                    original_mark.observed_at,
                    p.mark_available_at or event["recorded_at"],
                    original_mark.fx_as_of,
                    p.content_hash(),
                    str(event["content_hash"]),
                )
                if original_mark is not None
                else None
            )
            previous_position_mark = fold.position_marks.get(p.position_ref)
            if candidate_mark is not None and (
                previous_position_mark is None
                or candidate_mark.observed_at > previous_position_mark.observed_at
            ):
                fold.position_marks[p.position_ref] = candidate_mark
            fold.external_new |= int(event["sequence"]) > cursor
        elif kind == "ADJUSTMENT":
            amount = exact_decimal(data["amount"])
            if data.get("semantics") != "OBSERVED_VIRTUAL_ONLY":
                raise ValueError("CORRUPT_VIRTUAL_ADJUSTMENT")
            fold.cash += amount
            fold.total_flows += amount
            if event["recorded_at"] >= day_start_at:
                fold.day_flows += amount
            if fold.cash < 0:
                raise ValueError("VIRTUAL_NEGATIVE_CASH")
        elif kind == "MARKET_MARK":
            validate_market_mark(
                data, event["recorded_at"], list(accepted), baseline_positions=baseline.positions
            )
            market_mark = PaperMarketSnapshot.model_validate_json(canonical_payload(data))
            assert market_mark.adverse_fx is not None and market_mark.fx_as_of is not None
            previous_mark = fold.marks.get(market_mark.instrument_id)
            if previous_mark is None or market_mark.as_of > previous_mark.observed_at:
                fold.marks[market_mark.instrument_id] = ObservedMark(
                    market_mark.bid,
                    market_mark.adverse_fx,
                    market_mark.as_of,
                    market_mark.available_at,
                    market_mark.fx_as_of,
                    market_mark.content_hash(),
                    str(event["content_hash"]),
                    market_mark.clock_offset_ms,
                )
        elif kind == "SPEC_OBSERVATION":
            validate_spec_observation(data, event["recorded_at"])
        else:
            raise ValueError("UNKNOWN_VIRTUAL_FACT_KIND")

    def _reconcile(self, account_ref: str, *, now: datetime, epoch: int | None) -> bool:
        with self.engine.begin() as conn, localcontext() as context:
            context.prec = 100
            row = self._lock(conn, account_ref)
            self._fence(account_ref, row, epoch, writer=False)
            account = self._account(conn, row)
            journal = self._journal(conn, account_ref)
            self._reservations(conn, account_ref)
            events = truth_rows(conn, account_ref)
            baseline = PaperAccountSnapshot.model_validate_json(
                canonical_payload(journal[0]["data"]["account"])
            )
            if now < baseline.as_of or any(now < event["recorded_at"] for event in events):
                raise ValueError("PAPER_RECONCILIATION_CLOCK_BEFORE_TRUTH")
            policy = self._pinned_policy(conn, row)
            all_outbox = (
                conn.execute(
                    text(
                        "SELECT o.* FROM paper_outbox o JOIN paper_intent i "
                        "ON i.intent_hash=o.intent_hash WHERE o.account_ref=:a "
                        "ORDER BY i.recorded_at,i.intent_hash"
                    ),
                    {"a": account_ref},
                )
                .mappings()
                .all()
            )
            bound: dict[str, _Bound] = {}
            for outbox in all_outbox:
                ih = str(outbox["intent_hash"])
                original = next(
                    e["data"]
                    for e in journal
                    if e["kind"] == "AUTHORIZED" and e["intent_hash"] == ih
                )
                bound[ih] = _Bound(
                    self._intent(conn, ih),
                    PaperAuthorization.model_validate_json(
                        str(
                            conn.scalar(
                                text(
                                    "SELECT payload FROM paper_authorization WHERE intent_hash=:i"
                                ),
                                {"i": ih},
                            )
                        )
                    ),
                    PaperInstrumentSpec.model_validate_json(canonical_payload(original["spec"])),
                    PaperMarketSnapshot.model_validate_json(canonical_payload(original["market"])),
                )
            cursor = int(row["truth_cursor"])
            fold = _TruthFold(
                positions={p.position_ref: p for p in baseline.positions},
                owners={p.position_ref: None for p in baseline.positions},
                marks={},
                position_marks={
                    p.position_ref: ObservedMark.from_position(p) for p in baseline.positions
                },
                cash=baseline.cash,
                day_flows=(
                    baseline.day_net_flows
                    if baseline.day_start_at == account.day_start_at
                    else Decimal("0")
                ),
                total_flows=baseline.net_flows_since_high_water,
            )
            # P-9: a fact that fails validation is quarantined once, with a journaled
            # correction fact, and excluded from every later fold; it is never deleted.
            quarantined = self._quarantined(journal)
            quarantined_intents = {
                str(e["data"]["intent_hash"])
                for e in journal
                if e["kind"] == "TRUTH_QUARANTINE" and e["data"]["intent_hash"] is not None
            }
            accepted: list[dict[str, Any]] = []
            new_quarantine: list[tuple[dict[str, Any], str]] = []
            for event in events:
                if event["content_hash"] in quarantined:
                    continue
                trial = fold.copy()
                try:
                    self._apply_truth(
                        trial,
                        event,
                        accepted,
                        bound,
                        baseline,
                        account.day_start_at,
                        cursor,
                        account_ref,
                    )
                except INVALID_TRUTH as error:
                    new_quarantine.append((event, type(error).__name__ + ":" + str(error)[:200]))
                    continue
                fold = trial
                accepted.append(event)
            for event, cause in new_quarantine:
                self._append(
                    conn,
                    account_ref,
                    "TRUTH_QUARANTINE",
                    {
                        "truth_sequence": event["sequence"],
                        "truth_event_id": event["event_id"],
                        "truth_content_hash": event["content_hash"],
                        "truth_kind": event["kind"],
                        "intent_hash": event["intent_hash"],
                        "reason": cause,
                        "semantics": "INVALID_TRUTH_EXCLUDED_NOT_DELETED",
                    },
                    now,
                )
                if event["intent_hash"] is not None:
                    quarantined_intents.add(str(event["intent_hash"]))
            unresolved = False
            for outbox in all_outbox:
                ih = str(outbox["intent_hash"])
                auth = bound[ih].authorization
                reservation_payload = conn.scalar(
                    text("SELECT payload FROM paper_reservation WHERE intent_hash=:i"), {"i": ih}
                )
                reservation = PaperReservation.model_validate_json(str(reservation_payload))
                quantity = auth.exposure.quantity
                actual = sum(
                    (Decimal(str(fill["quantity"])) for fill in fold.fills.get(ih, [])),
                    Decimal("0"),
                )
                state = str(outbox["state"])
                contradiction = actual > 0 and ih in fold.rejected
                resolution = fold.resolutions.get(ih)
                finality = resolution is not None and resolution[
                    "observed_facts_hash"
                ] == resolution_facts(accepted, ih)
                reason: str | None = None
                if finality:
                    assert resolution is not None
                    state = str(resolution["status"])
                elif ih in quarantined_intents:
                    # Invalid truth for this order: worst-case capacity, never a guess.
                    state = "UNKNOWN"
                    reason = "QUARANTINED_TRUTH_FOR_ORDER"
                elif contradiction:
                    state = "UNKNOWN"
                    reason = "REJECTED_WITH_FILL_UNRESOLVED"
                elif actual == quantity and quantity > 0:
                    state = "FILLED"
                elif ih in fold.orders:
                    state = fold.statuses.get(ih, "UNKNOWN")
                    if state not in ("CANCELED", "REJECTED", "EXPIRED", "UNKNOWN") and actual:
                        state = "PARTIALLY_FILLED"
                elif state == "EXPIRED" and int(outbox["attempts"]) == 0:
                    state = "EXPIRED"
                elif state == "RESERVED":
                    # P-8: authorized but never dispatched. At its expiry the reservation is
                    # released by this journaled reconciliation; it can never be sent later.
                    if now >= reservation.expires_at:
                        state = "EXPIRED"
                        reason = "RESERVATION_EXPIRED_UNDISPATCHED"
                else:
                    state = "UNKNOWN"
                if state == "UNKNOWN":
                    unresolved = True
                terminal = state in ("FILLED", "CANCELED", "REJECTED", "EXPIRED")
                ratio = (
                    Decimal("0")
                    if terminal
                    else (
                        Decimal("1")
                        if state == "UNKNOWN"
                        else (quantity - actual) / quantity
                        if quantity
                        else Decimal("1")
                    )
                )
                updated_res = PaperReservation.model_validate(
                    reservation.model_dump()
                    | {
                        "state": "RELEASED"
                        if terminal
                        else "UNKNOWN"
                        if state == "UNKNOWN"
                        else "PARTIAL"
                        if actual
                        else "ACTIVE",
                        "quantity": Decimal("0")
                        if terminal
                        else quantity
                        if state == "UNKNOWN"
                        else quantity - actual,
                        "notional": bounded_amount(auth.exposure.notional * ratio, ceiling=True),
                        "modeled_loss": bounded_amount(
                            auth.exposure.modeled_loss * ratio, ceiling=True
                        ),
                        "margin": bounded_amount(
                            auth.exposure.margin_required * ratio, ceiling=True
                        ),
                    }
                )
                if (
                    state != outbox["state"]
                    or actual != outbox["filled_quantity"]
                    or updated_res != reservation
                ):
                    self._append(
                        conn,
                        account_ref,
                        "RECONCILED_ORDER",
                        {
                            "state": state,
                            "filled_quantity": actual,
                            "reservation": updated_res,
                            "reason": reason,
                            "authoritative_finality": resolution if finality else None,
                        },
                        now,
                        ih,
                    )
                conn.execute(
                    text(
                        "UPDATE paper_outbox SET state=:s,filled_quantity=:q,updated_at=:at "
                        "WHERE intent_hash=:i"
                    ),
                    {"s": state, "q": actual, "at": now, "i": ih},
                )
                conn.execute(
                    text(
                        "UPDATE paper_reservation SET payload=:p,active=:active "
                        "WHERE intent_hash=:i"
                    ),
                    {"p": updated_res.canonical_bytes().decode(), "active": not terminal, "i": ih},
                )
            positions = fold.positions
            marks_fresh = True
            mark_health: list[PaperMarkHealth] = []
            for ref, position in tuple(positions.items()):
                mark = fold.marks.get(position.instrument_id)
                position_mark = fold.position_marks.get(ref)
                if position_mark is not None and (
                    mark is None or position_mark.observed_at > mark.observed_at
                ):
                    mark = position_mark
                if mark is None:
                    marks_fresh = False
                    mark_health.append(PaperMarkHealth(position_ref=ref, state="UNPRICEABLE"))
                    continue
                fresh = (
                    timedelta(0)
                    <= now - mark.observed_at
                    <= timedelta(seconds=policy.max_market_age_seconds)
                    and timedelta(0)
                    <= now - mark.fx_as_of
                    <= timedelta(seconds=policy.max_fx_age_seconds)
                    and mark.available_at <= now
                    and abs(mark.clock_offset_ms) <= policy.max_clock_offset_ms
                )
                marks_fresh &= fresh
                mark_health.append(
                    PaperMarkHealth(
                        position_ref=ref,
                        state="FRESH" if fresh else "STALE",
                        fact_hash=mark.fact_hash,
                        snapshot_hash=mark.snapshot_hash,
                        observed_at=mark.observed_at,
                        available_at=mark.available_at,
                        fx_as_of=mark.fx_as_of,
                    )
                )
                positions[ref] = PaperPosition.model_validate(
                    position.model_dump()
                    | {
                        "mark_price": mark.price,
                        "adverse_fx": mark.adverse_fx,
                        "mark_as_of": mark.observed_at,
                        "mark_available_at": mark.available_at,
                        "fx_as_of": mark.fx_as_of,
                        "mark_snapshot_hash": mark.snapshot_hash,
                        "mark_fact_hash": mark.fact_hash,
                    }
                )
            equity = bounded_amount(
                fold.cash
                + sum(
                    (
                        p.quantity * p.mark_price * p.multiplier * p.adverse_fx
                        for p in positions.values()
                    ),
                    Decimal("0"),
                )
            )
            high = max(account.high_water_equity, equity - fold.total_flows)
            paused = unresolved or fold.external_new or not marks_fresh or bool(new_quarantine)
            updated = PaperAccountSnapshot.model_validate(
                account.model_dump()
                | {
                    "snapshot_id": uuid4(),
                    "as_of": now if marks_fresh else account.as_of,
                    "reconciled_at": now if marks_fresh else account.reconciled_at,
                    "cash": fold.cash,
                    "equity": equity,
                    "high_water_equity": high,
                    "positions": tuple(positions[k] for k in sorted(positions)),
                    "day_net_flows": fold.day_flows,
                    "net_flows_since_high_water": fold.total_flows,
                    "reconciled": not paused,
                    "unknown_orders": unresolved,
                    "kill": max(account.kill, KillLevel.K1) if paused else account.kill,
                }
            )
            updated = self._latch_loss(conn, updated, policy, now)
            cursor = int(events[-1]["sequence"]) if events else cursor
            prior_health = [e for e in journal if e["kind"] == "MARK_HEALTH"]
            if not prior_health or canonical_payload(
                prior_health[-1]["data"]["marks"]
            ) != canonical_payload(mark_health):
                self._append(
                    conn,
                    account_ref,
                    "MARK_HEALTH",
                    {
                        "marks": mark_health,
                        "marks_fresh": marks_fresh,
                        "evaluated_at": now,
                        "truth_cursor": cursor,
                        "policy_hash": policy.content_hash(),
                    },
                    now,
                )
            self._append(
                conn,
                account_ref,
                "RECONCILIATION",
                {
                    "account": updated,
                    "truth_cursor": cursor,
                    "external_fact_quarantine": fold.external_new,
                    "truth_quarantine": [event["content_hash"] for event, _ in new_quarantine],
                },
                now,
            )
            self._save(conn, updated, cursor=cursor)
            return updated.reconciled

    def ledger_replay(self, account_ref: str) -> PaperLedgerReplay:
        """OBV2-11: replay the verified journal and truth, compared field by field with the
        stored account. A tampered stored account is counted, never raised."""
        with self.engine.begin() as conn:
            row = self._lock(conn, account_ref)
            journal = self._journal(conn, account_ref)
            truth = truth_rows(conn, account_ref)
            return replay_ledger(
                account_ref,
                journal,
                truth,
                stored_payload=str(row["payload"]),
                stored_columns={
                    "writer_epoch": int(row["writer_epoch"]),
                    "kill_level": str(row["kill_level"]),
                    "reconciled": bool(row["reconciled"]),
                    "truth_cursor": int(row["truth_cursor"]),
                },
            )
