"""Immutable observation evidence layered on accepted PAPER/source journals."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from auvexo_alpha.application.observation_ports import ObservationRunStart, ObservationSnapshot
from auvexo_alpha.application.observation_replay import replay_observation_traces
from auvexo_alpha.application.observation_simulator import PendingSimulation, causal_fill_price
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.market_data import Candle, DataAvailabilityWindow
from auvexo_alpha.domain.observation import (
    ObservationCalendarSummary,
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationLedgerProof,
    ObservationProposalTrace,
    ObservationRunEvidence,
    ObservationSimulationTrace,
    ObservationVerification,
    observation_policy,
    observation_release,
)
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperAuthorization
from auvexo_alpha.domain.paper_lifecycle import Release
from auvexo_alpha.infrastructure.data_store import DataStore, parquet_bytes, read_bars, sha
from auvexo_alpha.infrastructure.paper_identity import enforce_paper_engine
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import canonical_payload, digest, truth_rows
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import parse_rest


class ObservationStore:
    def __init__(
        self,
        runtime_engine: Engine,
        owner_engine: Engine | None = None,
        truth_engine: Engine | None = None,
        source_store: DataStore | None = None,
    ) -> None:
        for engine, group in (
            (runtime_engine, "auvexo_paper"),
            (owner_engine, "auvexo_paper_owner"),
            (truth_engine, "auvexo_paper_truth"),
        ):
            if engine is not None:
                if not (engine.url.database or "").startswith("auvexo_paperobs_"):
                    raise ValueError("PERSISTENT_OBSERVATION_NAMESPACE_REQUIRED")
                enforce_paper_engine(engine, group)
                if engine is not runtime_engine:
                    continue
                with engine.connect() as conn:
                    if (
                        conn.scalar(text("SELECT version_num FROM alembic_version"))
                        != "0005_paper_core"
                        or conn.scalar(text("SELECT version_num FROM paper_observation_version"))
                        != "obs0001_qualification"
                    ):
                        raise ValueError("OBSERVATION_SCHEMA_NOT_READY")
        self.engine = runtime_engine
        self.owner_engine = owner_engine
        self.truth_engine = truth_engine
        self.source_store = source_store
        self.paper = PaperStore(runtime_engine, owner_engine)

    def started_run(self, run_id: UUID) -> ObservationRunStart:
        return ObservationRunStart(utc_time(self.run(run_id)["started_at"]))

    def run_snapshot(self, run_id: UUID) -> ObservationSnapshot:
        return ObservationSnapshot(**self.snapshot(run_id))

    def pinned_release(self, config: ObservationConfig) -> Release:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT release.payload,release.content_hash FROM paper_release release "
                    "JOIN paper_account account ON account.release_hash=release.content_hash "
                    "WHERE account.account_ref=:a"
                ),
                {"a": config.account_ref},
            ).one_or_none()
            if conn.scalar(text("SELECT count(*) FROM paper_production_release")) != 0:
                raise ValueError("OBSERVATION_PRODUCTION_REGISTRY_NOT_EMPTY")
        if row is None:
            raise ValueError("OBSERVATION_ACCOUNT_NOT_PREPARED")
        release = Release.model_validate_json(str(row[0]))
        if release.content_hash() != row[1] or release.config_hash != config.content_hash():
            raise ValueError("OBSERVATION_RELEASE_PIN_MISMATCH")
        return release

    def prepare(self, config: ObservationConfig, *, now: datetime) -> str:
        if self.owner_engine is None:
            raise ValueError("OBSERVATION_OWNER_REQUIRED")
        config = ObservationConfig.model_validate_json(config.canonical_bytes())
        self._rights(config, now)
        with self.owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_campaign(campaign_hash,payload) "
                    "VALUES (:h,:p) ON CONFLICT DO NOTHING"
                ),
                {"h": config.content_hash(), "p": config.canonical_bytes().decode()},
            )
            existing = conn.scalar(
                text("SELECT payload FROM paper_observation_campaign WHERE campaign_hash=:h"),
                {"h": config.content_hash()},
            )
            if existing != config.canonical_bytes().decode():
                raise ValueError("OBSERVATION_CONFIG_CORRUPT")
        with self.engine.connect() as conn:
            present = conn.scalar(
                text("SELECT 1 FROM paper_account WHERE account_ref=:a"), {"a": config.account_ref}
            )
        if not present:
            account = PaperAccountSnapshot(
                account_ref=config.account_ref,
                epoch=0,
                snapshot_id=uuid4(),
                as_of=now,
                reconciled_at=now,
                day_start_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
                currency="USDT",
                cash=Decimal("10000"),
                equity=Decimal("10000"),
                high_water_equity=Decimal("10000"),
                day_start_equity=Decimal("10000"),
            )
            self.paper.initialize(
                account, observation_policy(config), observation_release(config, now=now), now=now
            )
        return config.content_hash()

    def verify_schema(self) -> None:
        enforce_paper_engine(self.engine, "auvexo_paper")
        with self.engine.connect() as conn:
            if conn.scalar(text("SELECT count(*) FROM paper_production_release")):
                raise ValueError("OBSERVATION_PRODUCTION_REGISTRY_NOT_EMPTY")
            if (
                conn.scalar(text("SELECT version_num FROM paper_observation_version"))
                != "obs0001_qualification"
            ):
                raise ValueError("OBSERVATION_SCHEMA_NOT_READY")

    @staticmethod
    def _rights(config: ObservationConfig, now: datetime) -> None:
        config.rights.require_research(utc_time(now))
        if config.rights != rights("DS-02") or config.source != identity("DS-02"):
            raise ValueError("OBSERVATION_CURRENT_SOURCE_RIGHTS_MISMATCH")

    def config(self, config_hash: str) -> ObservationConfig:
        with self.engine.connect() as conn:
            payload = conn.scalar(
                text("SELECT payload FROM paper_observation_campaign WHERE campaign_hash=:h"),
                {"h": config_hash},
            )
        config = ObservationConfig.model_validate_json(str(payload))
        if config.content_hash() != config_hash:
            raise ValueError("OBSERVATION_CONFIG_CORRUPT")
        return config

    def activation(self, config_hash: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT * FROM paper_observation_activation WHERE campaign_hash=:h "
                        "ORDER BY activated_at DESC,activation_id DESC LIMIT 1"
                    ),
                    {"h": config_hash},
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def begin(self, config_hash: str, *, kind: str = "PREFLIGHT", now: datetime) -> UUID:
        self.verify_schema()
        config = self.config(config_hash)
        self._rights(config, now)
        if kind not in ("PREFLIGHT", "SCHEDULED", "RESTORE"):
            raise ValueError("OBSERVATION_RUN_KIND_INVALID")
        activation = self.activation(config_hash) if kind == "SCHEDULED" else None
        if kind == "SCHEDULED" and activation is None:
            raise ValueError("OBSERVATION_PREPARED_OWNER_START_REQUIRED")
        run_id = uuid4()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_run "
                    "(run_id,campaign_hash,kind,local_date,started_at,activation_id,payload) "
                    "VALUES (:id,:c,:k,:day,:now,:a,:p)"
                ),
                {
                    "id": str(run_id),
                    "c": config_hash,
                    "k": kind,
                    "day": utc_time(now).date(),
                    "now": now,
                    "a": activation["activation_id"] if activation else None,
                    "p": canonical_payload(
                        {"config_hash": config_hash, "requested_at": now, "kind": kind}
                    ),
                },
            )
        return run_id

    def run(self, run_id: UUID | str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            return dict(
                conn.execute(
                    text("SELECT * FROM paper_observation_run WHERE run_id=:id"),
                    {"id": str(run_id)},
                )
                .mappings()
                .one()
            )

    def _verify_source(self, fact: ObservationFact, config: ObservationConfig) -> None:
        if self.source_store is None:
            raise ValueError("OBSERVATION_ARCHIVE_VERIFIER_REQUIRED")
        fact = ObservationFact.model_validate_json(fact.canonical_bytes())
        if (
            fact.manifest.source != config.source
            or fact.manifest.rights != config.rights
            or fact.candle.source.source_id != "DS-02"
            or fact.candle.symbol not in ("BTCUSDT", "ETHUSDT")
            or fact.candle.interval != "1m"
            or fact.candle.product != "SPOT"
            or fact.candle.source.source_hash != fact.manifest.source_hash
        ):
            raise ValueError("OBSERVATION_SOURCE_BINDING_DENIED")
        self.source_store.verify(fact.manifest)
        if fact.candle not in read_bars(self.source_store.path(fact.manifest)):
            raise ValueError("OBSERVATION_CANDLE_NOT_IN_VERIFIED_ARCHIVE")
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT payload,manifest_hash FROM data_manifest WHERE dataset_version=:v"),
                {"v": fact.manifest.dataset_version},
            ).one()
        if row != (fact.manifest.canonical_bytes().decode(), fact.manifest.content_hash()):
            raise ValueError("OBSERVATION_MANIFEST_LEDGER_MISMATCH")
        manifest = fact.manifest
        raw = (self.source_store.root / manifest.raw_relative_path).read_bytes()
        bars, report = parse_rest(
            raw,
            fact.candle.symbol,
            "1m",
            manifest.coverage.requested_start,
            manifest.coverage.requested_end,
            manifest.created_at,
            manifest.source_url,
            manifest.parser_version,
        )
        rebuilt = [
            Candle.model_validate(
                bar.model_dump()
                | {
                    "availability": DataAvailabilityWindow.model_validate(
                        bar.availability.model_dump()
                        | {
                            "original_first_seen_at": manifest.created_at,
                            "processed_at": manifest.processed_at,
                            "available_at": manifest.processed_at,
                        }
                    ),
                }
            )
            for bar in bars
        ]
        if (
            report != manifest.coverage
            or rebuilt != [fact.candle]
            or sha(parquet_bytes(rebuilt)) != manifest.parquet_hash
        ):
            raise ValueError("OBSERVATION_RAW_SOURCE_REPLAY_MISMATCH")

    def append_feed(self, run_id: UUID | str, fact: ObservationFact, *, now: datetime) -> str:
        if self.truth_engine is None:
            raise ValueError("OBSERVATION_TRUTH_IDENTITY_REQUIRED")
        run = self.run(run_id)
        config = self.config(str(run["campaign_hash"]))
        self._rights(config, now)
        self._verify_source(fact, config)
        if fact.candle.availability.available_at > now:
            raise ValueError("OBSERVATION_FUTURE_SOURCE_FACT")
        with self.truth_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_feed "
                    "(feed_hash,run_id,dataset_version,symbol,bar_end,available_at,payload) "
                    "VALUES (:h,:id,:v,:s,:e,:a,:p)"
                ),
                {
                    "h": fact.content_hash(),
                    "id": str(run_id),
                    "v": fact.manifest.dataset_version,
                    "s": fact.candle.symbol,
                    "e": fact.candle.end_at,
                    "a": fact.candle.availability.available_at,
                    "p": fact.canonical_bytes().decode(),
                },
            )
        return fact.content_hash()

    def feeds(self, run_id: UUID | str) -> tuple[ObservationFact, ...]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT feed_hash,payload FROM paper_observation_feed WHERE run_id=:id "
                    "ORDER BY recorded_at,feed_hash"
                ),
                {"id": str(run_id)},
            ).all()
        result = tuple(ObservationFact.model_validate_json(row[1]) for row in rows)
        if any(value.content_hash() != row[0] for value, row in zip(result, rows, strict=True)):
            raise ValueError("OBSERVATION_SOURCE_LEDGER_CORRUPT")
        return result

    def append_trace(
        self, run_id: UUID | str, trace: ObservationProposalTrace, *, now: datetime
    ) -> str:
        trace = ObservationProposalTrace.model_validate_json(trace.canonical_bytes())
        run = self.run(run_id)
        config = self.config(str(run["campaign_hash"]))
        facts = self.feeds(run_id)
        replay_observation_traces(config, facts, (trace,))
        journal = self.paper.journal(config.account_ref)
        self._trace_journal(trace, journal)
        event = next(e for e in journal if e["content_hash"] == trace.journal_event_hash)
        if event["recorded_at"] < run["started_at"] or event["recorded_at"] > now:
            raise ValueError("OBSERVATION_TRACE_RUN_TIME_DENIED")
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO paper_observation_trace VALUES (:h,:id,:f,:p,clock_timestamp())"),
                {
                    "h": trace.content_hash(),
                    "id": str(run_id),
                    "f": trace.source_observation_hash,
                    "p": trace.canonical_bytes().decode(),
                },
            )
        return trace.content_hash()

    def traces(self, run_id: UUID | str) -> tuple[ObservationProposalTrace, ...]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT trace_hash,payload FROM paper_observation_trace WHERE run_id=:id "
                    "ORDER BY recorded_at,trace_hash"
                ),
                {"id": str(run_id)},
            ).all()
        values = tuple(ObservationProposalTrace.model_validate_json(row[1]) for row in rows)
        if any(v.content_hash() != r[0] for v, r in zip(values, rows, strict=True)):
            raise ValueError("OBSERVATION_TRACE_LEDGER_CORRUPT")
        return values

    def append_simulation(
        self, run_id: UUID | str, simulation: ObservationSimulationTrace, *, now: datetime
    ) -> str:
        if self.truth_engine is None:
            raise ValueError("OBSERVATION_TRUTH_IDENTITY_REQUIRED")
        value = ObservationSimulationTrace.model_validate_json(simulation.canonical_bytes())
        facts = {f.content_hash(): f for f in self.feeds(run_id)}
        before = facts[value.proposal_source_hash].candle
        after = facts[value.fill_source_hash].candle
        if (
            after.symbol != before.symbol
            or after.end_at <= before.end_at
            or after.availability.available_at <= before.availability.available_at
            or value.observed_at < after.availability.available_at
            or now < value.observed_at
        ):
            raise ValueError("OBSERVATION_SIMULATED_FILL_LOOKAHEAD")
        config = self.config(str(self.run(run_id)["campaign_hash"]))
        trace = next(
            (t for t in self.traces(run_id) if t.intent.content_hash() == value.intent_hash), None
        )
        if (
            trace is None
            or trace.authorization is None
            or trace.source_observation_hash != value.proposal_source_hash
        ):
            raise ValueError("OBSERVATION_SIMULATION_PROPOSAL_BINDING_DENIED")
        pending = PendingSimulation(trace.intent, facts[value.proposal_source_hash], value.quantity)
        if (
            value.quantity != trace.authorization.exposure.quantity
            or causal_fill_price(pending, facts[value.fill_source_hash], now=value.observed_at)
            != value.price
        ):
            raise ValueError("OBSERVATION_SIMULATION_AUTHORIZATION_OR_PRICE_DENIED")
        with self.truth_engine.begin() as conn:
            event = (
                conn.execute(
                    text("SELECT * FROM paper_truth_event WHERE event_id=:id"),
                    {"id": str(value.truth_event_id)},
                )
                .mappings()
                .one()
            )
            payload = json.loads(str(event["payload"]))["data"]
            if (
                event["kind"] != "FILL"
                or event["intent_hash"] != value.intent_hash
                or event["account_ref"] != config.account_ref
                or Decimal(str(payload["quantity"])) != value.quantity
                or Decimal(str(payload["price"])) != value.price
                or event["recorded_at"] != value.observed_at
            ):
                raise ValueError("OBSERVATION_SIMULATION_TRUTH_BINDING_DENIED")
            conn.execute(
                text(
                    "INSERT INTO paper_observation_simulation VALUES "
                    "(:h,:run,:p,:f,:event,:payload,clock_timestamp())"
                ),
                {
                    "h": value.content_hash(),
                    "run": str(run_id),
                    "p": value.proposal_source_hash,
                    "f": value.fill_source_hash,
                    "event": str(value.truth_event_id),
                    "payload": value.canonical_bytes().decode(),
                },
            )
        return value.content_hash()

    def simulations(self, run_id: UUID | str) -> tuple[ObservationSimulationTrace, ...]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT simulation_hash,payload FROM paper_observation_simulation "
                    "WHERE run_id=:id ORDER BY recorded_at,simulation_hash"
                ),
                {"id": str(run_id)},
            ).all()
        values = tuple(ObservationSimulationTrace.model_validate_json(row[1]) for row in rows)
        if any(v.content_hash() != r[0] for v, r in zip(values, rows, strict=True)):
            raise ValueError("OBSERVATION_SIMULATION_LEDGER_CORRUPT")
        return values

    @staticmethod
    def _trace_journal(trace: ObservationProposalTrace, journal: list[dict[str, Any]]) -> None:
        event = next((e for e in journal if e["content_hash"] == trace.journal_event_hash), None)
        if event is None or event["kind"] not in ("AUTHORIZED", "DENIED"):
            raise ValueError("OBSERVATION_TRACE_JOURNAL_BINDING_DENIED")
        data = event["data"]
        if canonical_payload(data["intent"]) != trace.intent.canonical_bytes().decode():
            raise ValueError("OBSERVATION_TRACE_INTENT_BINDING_DENIED")
        if event["kind"] == "DENIED":
            if canonical_payload(data["decision"]) != trace.decision.canonical_bytes().decode():
                raise ValueError("OBSERVATION_TRACE_DECISION_BINDING_DENIED")
        elif (
            trace.authorization is None
            or trace.reservation is None
            or canonical_payload(data["authorization"])
            != trace.authorization.canonical_bytes().decode()
            or canonical_payload(data["reservation"])
            != trace.reservation.canonical_bytes().decode()
        ):
            raise ValueError("OBSERVATION_TRACE_AUTHORIZATION_BINDING_DENIED")

    @staticmethod
    def _outbox_hash(row: dict[str, Any]) -> str:
        value = format(Decimal(str(row["filled_quantity"])), "f")
        row = dict(row) | {
            "filled_quantity": value.rstrip("0").rstrip(".") if "." in value else value
        }
        row["filled_quantity"] = row["filled_quantity"] or "0"
        return digest(canonical_payload(row))

    @classmethod
    def _project_journal(
        cls, journal: list[dict[str, Any]], traces: tuple[ObservationProposalTrace, ...]
    ) -> dict[str, Any]:
        projection_kinds = {
            "INITIALIZED",
            "WRITER_ACQUIRED_PAUSE_NEW",
            "KILL_STATE",
            "OWNER_PAPER_RESUME",
            "UNKNOWN_RECONCILE_ONLY",
            "RECONCILIATION",
            "OWNER_RELEASE_PIN",
            "OWNER_POLICY_PIN",
            "UTC_DAY_ROLLOVER",
            "LOSS_BREACH_LATCH",
        }
        latest = next(
            e["data"]["account"] for e in reversed(journal) if e["kind"] in projection_kinds
        )
        account = PaperAccountSnapshot.model_validate_json(canonical_payload(latest))
        authorized = sorted(
            (e for e in journal if e["kind"] == "AUTHORIZED"),
            key=lambda event: (event["recorded_at"], event["intent_hash"]),
        )
        account = PaperAccountSnapshot.model_validate(
            account.model_dump()
            | {
                "prior_logical_keys": tuple(e["data"]["intent"]["logical_key"] for e in authorized),
                "prior_intent_ids": tuple(
                    UUID(e["data"]["intent"]["intent_id"]) for e in authorized
                ),
                "recent_intent_times": tuple(e["recorded_at"] for e in authorized),
            }
        )
        outboxes: dict[str, dict[str, Any]] = {}
        cursor = 0
        for event in journal:
            ih = event["intent_hash"]
            data = event["data"]
            if event["kind"] == "AUTHORIZED":
                auth = PaperAuthorization.model_validate_json(
                    canonical_payload(data["authorization"])
                )
                outboxes[str(ih)] = {
                    "intent_hash": ih,
                    "account_ref": account.account_ref,
                    "writer_epoch": auth.writer_epoch,
                    "state": "RESERVED",
                    "filled_quantity": Decimal("0"),
                    "attempts": 0,
                    "updated_at": event["recorded_at"],
                }
            if event["kind"] == "DISPATCH_ATTEMPT":
                outboxes[str(ih)].update(
                    state="SENT_PENDING", attempts=1, updated_at=event["recorded_at"]
                )
            elif event["kind"] == "UNKNOWN_RECONCILE_ONLY":
                outboxes[str(ih)].update(state="UNKNOWN", updated_at=event["recorded_at"])
            elif event["kind"] == "RECONCILED_ORDER":
                outboxes[str(ih)].update(
                    state=data["state"],
                    filled_quantity=Decimal(data["filled_quantity"]),
                    updated_at=event["recorded_at"],
                )
            elif event["kind"] == "RECONCILIATION":
                cursor = int(data["truth_cursor"])
                for outbox in outboxes.values():
                    outbox["updated_at"] = event["recorded_at"]
        return {
            "final_account": account,
            "truth_cursor": cursor,
            "journal_tail_hash": journal[-1]["content_hash"],
            "reservation_hashes": tuple(
                t.reservation.content_hash() for t in traces if t.reservation is not None
            ),
            "outbox_hashes": tuple(
                cls._outbox_hash(outboxes[k])
                for k in sorted(outboxes)
                if k in {t.intent.content_hash() for t in traces if t.authorization is not None}
            ),
            "unknown_order_refs": tuple(
                k for k in sorted(outboxes) if outboxes[k]["state"] in ("UNKNOWN", "SENT_PENDING")
            ),
            "mismatch_refs": () if account.reconciled else ("UNRECONCILED",),
        }

    def snapshot(self, run_id: UUID | str) -> dict[str, Any]:
        config = self.config(str(self.run(run_id)["campaign_hash"]))
        account = self.paper.account(config.account_ref)
        journal = self.paper.journal(config.account_ref)
        traces = self.traces(run_id)
        run_intents = {t.intent.content_hash() for t in traces if t.authorization is not None}
        with self.engine.connect() as conn:
            cursor = int(
                conn.scalar(
                    text("SELECT truth_cursor FROM paper_account WHERE account_ref=:a"),
                    {"a": config.account_ref},
                )
                or 0
            )
            outbox = (
                conn.execute(
                    text("SELECT * FROM paper_outbox WHERE account_ref=:a ORDER BY intent_hash"),
                    {"a": config.account_ref},
                )
                .mappings()
                .all()
            )
            fills = tuple(
                conn.scalars(
                    text(
                        "SELECT simulation_hash FROM paper_observation_simulation "
                        "WHERE run_id=:id ORDER BY recorded_at,simulation_hash"
                    ),
                    {"id": str(run_id)},
                )
            )
        return {
            "final_account": account,
            "truth_cursor": cursor,
            "journal_tail_hash": journal[-1]["content_hash"],
            "reservation_hashes": tuple(
                t.reservation.content_hash() for t in traces if t.reservation is not None
            ),
            "outbox_hashes": tuple(
                self._outbox_hash(dict(row)) for row in outbox if row["intent_hash"] in run_intents
            ),
            "fill_hashes": fills,
            "unknown_order_refs": tuple(
                str(row["intent_hash"])
                for row in outbox
                if row["state"] in ("UNKNOWN", "SENT_PENDING")
            ),
            "mismatch_refs": () if account.reconciled else ("UNRECONCILED",),
        }

    def verify(
        self, run_id: UUID | str, evidence: ObservationRunEvidence, *, now: datetime
    ) -> ObservationVerification:
        run = self.run(run_id)
        config = self.config(str(run["campaign_hash"]))
        self._rights(config, now)
        if (
            str(evidence.run_id) != str(run_id)
            or evidence.campaign_id != config.campaign_id
            or evidence.started_at != run["started_at"]
            or evidence.local_day != run["local_date"].isoformat()
            or evidence.ended_at > now
            or evidence.kind != ("SCHEDULED" if run["kind"] == "SCHEDULED" else "NON_COUNTING")
        ):
            raise ValueError("OBSERVATION_EVIDENCE_SERVER_CLOCK_BINDING_DENIED")
        facts, traces = self.feeds(run_id), self.traces(run_id)
        if (
            evidence.facts != facts
            or evidence.traces != traces
            or evidence.config_hash != config.content_hash()
        ):
            raise ValueError("OBSERVATION_EVIDENCE_LEDGER_MISMATCH")
        for fact in facts:
            self._verify_source(fact, config)
        journal = self.paper.journal(config.account_ref)
        tail = next(
            (i for i, e in enumerate(journal) if e["content_hash"] == evidence.journal_tail_hash),
            None,
        )
        if tail is None:
            raise ValueError("OBSERVATION_JOURNAL_TAIL_UNKNOWN")
        journal = journal[: tail + 1]
        run = self.run(run_id)
        journal_decisions = {
            e["content_hash"]
            for e in journal
            if e["kind"] in ("AUTHORIZED", "DENIED")
            and run["started_at"] <= e["recorded_at"] <= evidence.ended_at
        }
        if journal_decisions != {trace.journal_event_hash for trace in traces} or len(
            traces
        ) != len(journal_decisions):
            raise ValueError("OBSERVATION_UNJOURNALED_OR_MISSING_PROPOSAL_TRACE")
        for trace in traces:
            self._trace_journal(trace, journal)
        intents, decisions = replay_observation_traces(config, facts, traces)
        snapshot = self._project_journal(journal, traces)
        simulations = self.simulations(run_id)
        if evidence.simulation_traces != simulations:
            raise ValueError("OBSERVATION_SIMULATION_EVIDENCE_MISMATCH")
        by_hash = {f.content_hash(): f for f in facts}
        by_intent = {t.intent.content_hash(): t for t in traces}
        with self.engine.connect() as conn:
            truth = truth_rows(conn, config.account_ref)
        if evidence.truth_cursor != max(
            (e["sequence"] for e in truth if e["recorded_at"] <= evidence.ended_at), default=0
        ):
            raise ValueError("OBSERVATION_UNCONSUMED_TRUTH_AT_CLOSURE")
        fill_events = {
            e["event_id"]
            for e in truth
            if e["kind"] == "FILL"
            and e["sequence"] <= evidence.truth_cursor
            and run["started_at"] <= e["recorded_at"] <= evidence.ended_at
        }
        if fill_events != {str(s.truth_event_id) for s in simulations}:
            raise ValueError("OBSERVATION_UNBOUND_OR_MISSING_SIMULATED_FILL")
        for sim in simulations:
            trace = by_intent[sim.intent_hash]
            pending = PendingSimulation(
                trace.intent, by_hash[sim.proposal_source_hash], sim.quantity
            )
            expected = causal_fill_price(
                pending, by_hash[sim.fill_source_hash], now=sim.observed_at
            )
            fill = next((e for e in truth if e["event_id"] == str(sim.truth_event_id)), None)
            if (
                expected != sim.price
                or fill is None
                or fill["kind"] != "FILL"
                or (
                    Decimal(fill["data"]["quantity"]) != sim.quantity
                    or Decimal(fill["data"]["price"]) != sim.price
                    or fill["intent_hash"] != sim.intent_hash
                    or fill["recorded_at"] != sim.observed_at
                )
            ):
                raise ValueError("OBSERVATION_SIMULATED_FILL_REPLAY_MISMATCH")
        snapshot["fill_hashes"] = tuple(s.content_hash() for s in simulations)
        for key, value in snapshot.items():
            if getattr(evidence, key) != value:
                raise ValueError("OBSERVATION_FINAL_STATE_MISMATCH")
        return ObservationVerification(
            run_evidence_hash=evidence.content_hash(),
            source_fact_hashes=tuple(f.content_hash() for f in facts),
            trace_hashes=tuple(t.content_hash() for t in traces),
            journal_tail_hash=evidence.journal_tail_hash,
            replay_journal_hash=evidence.journal_tail_hash,
            replay_intent_hashes=intents,
            replay_decision_hashes=decisions,
            reservation_hashes=evidence.reservation_hashes,
            outbox_hashes=evidence.outbox_hashes,
            fill_hashes=evidence.fill_hashes,
            privilege_identity_hash=digest(
                canonical_payload(
                    {
                        "database": run["database_name"],
                        "login": "auvexo_pw_" + str(run["database_name"]).rsplit("_", 1)[1],
                    }
                )
            ),
        )

    def close(
        self, run_id: UUID | str, evidence: ObservationRunEvidence, *, now: datetime
    ) -> ObservationDayReceipt:
        from auvexo_alpha.application.observation_qualification import evaluate_observation_day

        run = self.run(run_id)
        if (
            str(evidence.run_id) != str(run_id)
            or evidence.started_at != run["started_at"]
            or evidence.local_day != run["local_date"].isoformat()
            or evidence.ended_at > now
            or evidence.kind != ("SCHEDULED" if run["kind"] == "SCHEDULED" else "NON_COUNTING")
        ):
            raise ValueError("OBSERVATION_EVIDENCE_SERVER_CLOCK_BINDING_DENIED")
        config = self.config(str(run["campaign_hash"]))
        with self.engine.begin() as conn:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:id,20802302))"),
                {"id": str(run_id)},
            )
            account_row = PaperStore._lock(conn, config.account_ref)
            account = PaperStore._account(conn, account_row)
            journal = PaperStore._journal(conn, config.account_ref)
            if (
                account != evidence.final_account
                or journal[-1]["content_hash"] != evidence.journal_tail_hash
                or int(account_row["truth_cursor"]) != evidence.truth_cursor
                or evidence.truth_cursor
                != conn.scalar(
                    text(
                        "SELECT COALESCE(max(sequence),0) FROM paper_truth_event "
                        "WHERE account_ref=:a"
                    ),
                    {"a": config.account_ref},
                )
            ):
                raise ValueError("OBSERVATION_CLOSURE_NOT_CURRENT_RECONCILED_STATE")
            witness = self.verify(run_id, evidence, now=now)
            receipt = evaluate_observation_day(config, evidence, witness, now=now)
            disposition = receipt.status if run["kind"] == "SCHEDULED" else "NON_COUNTING"
            envelope = canonical_payload(
                {"receipt": receipt, "evidence": evidence, "verification": witness}
            )
            conn.execute(
                text(
                    "INSERT INTO paper_observation_receipt "
                    "(receipt_hash,run_id,campaign_hash,local_date,disposition,payload) "
                    "VALUES (:h,:run,:c,:day,:d,:p)"
                ),
                {
                    "h": receipt.content_hash(),
                    "run": str(run_id),
                    "c": config.content_hash(),
                    "day": run["local_date"],
                    "d": disposition,
                    "p": envelope,
                },
            )
        return receipt

    def qualified_dates(self, config_hash: str, *, now: datetime) -> ObservationCalendarSummary:
        from auvexo_alpha.application.observation_qualification import (
            observation_ledger_tail,
            summarize_observation_days,
        )

        config = self.config(config_hash)
        activation = self.activation(config_hash)
        receipts = []
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT * FROM paper_observation_receipt WHERE campaign_hash=:h "
                        "AND disposition<>'NON_COUNTING' ORDER BY local_date"
                    ),
                    {"h": config_hash},
                )
                .mappings()
                .all()
            )
        if activation is None or activation["database_name"] != self.engine.url.database:
            summary = summarize_observation_days((), None, now=now)
            return ObservationCalendarSummary.model_validate(
                summary.model_dump() | {"campaign_id": config.campaign_id}
            )
        for row in rows:
            envelope = json.loads(str(row["payload"]))
            evidence = ObservationRunEvidence.model_validate_json(
                canonical_payload(envelope["evidence"])
            )
            receipt = ObservationDayReceipt.model_validate_json(
                canonical_payload(envelope["receipt"])
            )
            run = self.run(row["run_id"])
            if (
                run["kind"] != "SCHEDULED"
                or run["database_name"] != self.engine.url.database
                or run["activation_id"] != activation["activation_id"]
                or activation["reviewed_sha"] != config.git_revision
                or row["disposition"] != receipt.status
                or row["local_date"].isoformat() != receipt.local_day
                or row["campaign_hash"] != config_hash
                or row["recorded_at"] < evidence.ended_at
            ):
                raise ValueError("OBSERVATION_RECEIPT_AUTHORITY_BINDING_MISMATCH")
            witness = self.verify(row["run_id"], evidence, now=now)
            from auvexo_alpha.application.observation_qualification import evaluate_observation_day

            expected = evaluate_observation_day(config, evidence, witness, now=row["recorded_at"])
            if receipt != expected or receipt.content_hash() != row["receipt_hash"]:
                raise ValueError("OBSERVATION_RECEIPT_REPLAY_MISMATCH")
            receipts.append(receipt)
        proof = ObservationLedgerProof(
            campaign_id=config.campaign_id,
            activated_at=activation["activated_at"],
            first_eligible_day=activation["first_date"].isoformat(),
            verified_at=now,
            receipt_hashes=tuple(r.content_hash() for r in receipts),
            ledger_tail_hash=observation_ledger_tail(tuple(receipts)),
        )
        return summarize_observation_days(tuple(receipts), proof, now=now)
