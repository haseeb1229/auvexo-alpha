"""One-shot isolated synthetic PAPER backup/restore; same disk is not disaster recovery."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from uuid import uuid4

import psycopg
from local_db import run_pg
from paper_local import (
    LOCAL,
    ROOT,
    admin_args,
    engine_for,
    isolated_database,
    migrate,
    provision_services,
    require_migration,
    snapshot,
)
from psycopg import sql

sys.path.insert(0, str(ROOT / "tests"))
from paper_fixtures import fixture_bundle  # noqa: E402

from auvexo_alpha.domain.paper import PaperReason  # noqa: E402
from auvexo_alpha.domain.paper_lifecycle import KillLevel  # noqa: E402
from auvexo_alpha.infrastructure.paper_store import PaperStore, PaperTruth  # noqa: E402


def main() -> None:
    began = time.monotonic()
    directory = LOCAL / ("paper-recovery-" + uuid4().hex[:12])
    directory.mkdir(parents=True)
    dump = directory / "paper-metadata.dump"
    with isolated_database() as source, isolated_database(prefix="auvexo_restore") as target:
        require_migration(source)
        require_migration(source)
        engines = [
            engine_for(source, role)
            for role in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        b = fixture_bundle(account_ref="paper.recovery.synthetic")
        store = PaperStore(engines[0], owner_engine=engines[1])
        truth = PaperTruth(engines[2])
        try:
            store.initialize(b.account, b.policy, b.release, now=b.now)
            epoch = store.acquire_writer(b.account.account_ref, now=b.now)
            assert store.reconcile(b.account.account_ref, now=b.now)
            store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
            b.account = store.account(b.account.account_ref)
            intent = b.rebind()
            first = store.authorize(intent, b.policy, b.market, b.spec, b.release, now=b.now)
            assert first.decision.status == "APPROVED"
            store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
            truth.fill(
                intent.content_hash(),
                Decimal("0.004"),
                intent.entry,
                account_ref=b.account.account_ref,
                now=b.now,
            )
            assert store.reconcile(b.account.account_ref, now=b.now)
            b.account = store.account(b.account.account_ref)
            denied_intent = b.rebind(
                intent_id=uuid4(), logical_key="recovery.denied", quantity=Decimal("1000")
            )
            denied = store.authorize(
                denied_intent, b.policy, b.market, b.spec, b.release, now=b.now
            )
            assert denied.decision.status == "DENIED"
            assert set(denied.decision.reasons) & {
                PaperReason.DAILY_LOSS_CAP,
                PaperReason.DRAWDOWN_CAP,
            }
            # The deliberately oversized proposal conservatively latches K2.
            # A separate fixture order requires the existing audited owner path,
            # not an implicit reset or a snapshot from before the denial.
            assert store.account(b.account.account_ref).kill == KillLevel.K2
            store.resume(b.account.account_ref, actor="owner.fixture.recovery", now=b.now)
            b.account = store.account(b.account.account_ref)
            second_intent = b.rebind(intent_id=uuid4(), logical_key="recovery.unknown")
            second = store.authorize(
                second_intent, b.policy, b.market, b.spec, b.release, now=b.now
            )
            assert second.decision.status == "APPROVED"
            try:
                store.dispatch(
                    second_intent.content_hash(),
                    epoch,
                    truth,
                    now=b.now,
                    fault="CRASH_AFTER_SEND",
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("Injected crash did not occur")
            assert store.outbox(second_intent.content_hash())["state"] == "UNKNOWN"
            store.set_kill(b.account.account_ref, KillLevel.K4, actor="owner.fixture", now=b.now)
            expected = snapshot(source)
            with psycopg.connect(dbname=source, **admin_args()) as conn:
                virtual_totals = conn.execute(
                    "SELECT sum((payload::jsonb->>'quantity')::numeric),"
                    "sum((payload::jsonb->>'modeled_loss')::numeric),count(*) "
                    "FROM paper_reservation WHERE active"
                ).fetchone()
            refused = migrate(source, "downgrade", "0004_research_ledger")
            assert refused.returncode and b"destructive downgrade disabled" in refused.stderr
            assert snapshot(source) == expected
            args = admin_args()
            pg_env = os.environ | dict(
                PGHOST=str(args["host"]),
                PGPORT=str(args["port"]),
                PGUSER=str(args["user"]),
                PGPASSWORD=str(args["password"]),
            )
            run_pg("pg_dump", "-Fc", "-f", str(dump), source, env=pg_env)
            run_pg(
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "-d",
                target,
                str(dump),
                env=pg_env,
            )
            assert snapshot(target) == expected
            with psycopg.connect(dbname=target, **admin_args()) as conn:
                assert (
                    conn.execute(
                        "SELECT sum((payload::jsonb->>'quantity')::numeric),"
                        "sum((payload::jsonb->>'modeled_loss')::numeric),count(*) "
                        "FROM paper_reservation WHERE active"
                    ).fetchone()
                    == virtual_totals
                )
        finally:
            for engine in engines:
                engine.dispose()
        provision_services(target)
        restored_engine = engine_for(target, "auvexo_paper")
        restored_truth_engine = engine_for(target, "auvexo_paper_truth")
        restored = PaperStore(restored_engine)
        restored_truth = PaperTruth(restored_truth_engine)
        try:
            assert restored.account(b.account.account_ref).kill == KillLevel.K4
            assert restored.outbox(second_intent.content_hash())["state"] == "UNKNOWN"
            assert restored.journal(b.account.account_ref)
            restored.acquire_writer(b.account.account_ref, now=b.now)
            assert not restored.reconcile(b.account.account_ref, now=b.now)
            restored_truth.status(
                second_intent.content_hash(),
                "ACKNOWLEDGED",
                account_ref=b.account.account_ref,
                now=b.now,
            )
            assert restored.reconcile(b.account.account_ref, now=b.now)
            assert restored.account(b.account.account_ref).kill == KillLevel.K4
            assert sum(
                p.quantity for p in restored.account(b.account.account_ref).positions
            ) == Decimal("0.004")
            assert len(restored.reservations(b.account.account_ref)) == 2
            with psycopg.connect(dbname=target, **admin_args()) as conn:
                for table in (
                    "paper_policy",
                    "paper_release",
                    "paper_intent",
                    "paper_authorization",
                    "paper_journal",
                    "paper_denial",
                    "paper_lifecycle",
                    "paper_truth_event",
                    "paper_production_release",
                    "paper_production_lifecycle",
                ):
                    try:
                        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
                    except psycopg.errors.RaiseException:
                        conn.rollback()
                    else:
                        raise AssertionError("Restored immutable trigger absent")
        finally:
            restored_engine.dispose()
            restored_truth_engine.dispose()
        report = dict(
            status="PASS",
            evidence_kind="SYNTHETIC_ENGINEERING_ONLY",
            tables_and_triggers=expected,
            table_count=len(expected) - 1,
            migration_idempotent=True,
            destructive_downgrade_refused=True,
            partial_position_quantity="0.004",
            restored_virtual_totals=dict(
                reserved_quantity=str(virtual_totals[0]),
                modeled_loss=str(virtual_totals[1]),
                active_count=virtual_totals[2],
            ),
            active_reservations=2,
            unknown_preserved=True,
            restart_reconciled_without_retry=True,
            kill_state_preserved="K4",
            restored_triggers=True,
            dump_bytes=dump.stat().st_size,
            dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
            elapsed_seconds=round(time.monotonic() - began, 3),
            limitation="Isolated same-disk synthetic TEST backup; not disaster recovery",
        )
    (LOCAL / "paper-recovery-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
