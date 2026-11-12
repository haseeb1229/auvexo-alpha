"""CLI failure evidence, lease scope, warm-up catch-up and receipt parsing; no database."""

import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import (
    DataError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from test_data_clock_proof import CLOCK_URL, LEAK, MINUTE, World, collector_for

from auvexo_alpha import data_cli
from auvexo_alpha.application.data_reporting import ScheduledSummary
from auvexo_alpha.domain.market_data import IngestionEvent
from auvexo_alpha.infrastructure.public_http import SourceError

FAILED = {
    "code": "DATA_OPERATION_FAILED",
    "execution_enabled": False,
    "detail": "inspect durable data events; no success inferred",
}
SECRETS = ("hunter2", "secret.txt", "owner", "SELECT", "password")


def database(kind):
    return kind("SELECT secret FROM " + LEAK, {"password": "hunter2"}, Exception(LEAK))


def validation_error():
    with pytest.raises(ValidationError) as failure:
        IngestionEvent.model_validate({"reason": LEAK})
    return failure.value


CLASSIFIED = [
    (ValueError("QUOTA"), "QUOTA"),
    (ValueError("COLLECTOR_ALREADY_RUNNING"), "COLLECTOR_ALREADY_RUNNING"),
    (ValueError("LOCAL_CLOCK_SKEW"), "LOCAL_CLOCK_SKEW"),
    (SourceError("RATE_LIMIT", 60), "RATE_LIMIT"),
    (ValueError("A" * 64), "A" * 64),
    (ValueError("A" * 65), "UNCLASSIFIED"),
    (ValueError("AB"), "UNCLASSIFIED"),
    (ValueError(""), "UNCLASSIFIED"),
    (ValueError(LEAK), "UNCLASSIFIED"),
    (ValueError("QUOTA " + LEAK), "UNCLASSIFIED"),
    (ValueError("QUOTA\n"), "UNCLASSIFIED"),
    (ValueError("QUOTA", LEAK), "UNCLASSIFIED"),
    (ValueError("Quota"), "UNCLASSIFIED"),
    (ValueError("1QUOTA"), "UNCLASSIFIED"),
    (ValueError("_QUOTA"), "UNCLASSIFIED"),
    (ValueError("QUOTA-EXCEEDED"), "UNCLASSIFIED"),
    (ValueError("invalid data quota"), "UNCLASSIFIED"),
    (OSError(LEAK), "OS_ERROR"),
    (PermissionError(13, "Access is denied", LEAK), "OS_ERROR"),
    (FileNotFoundError(2, "No such file", LEAK), "OS_ERROR"),
    (database(OperationalError), "DATABASE_UNAVAILABLE"),
    (database(InterfaceError), "DATABASE_UNAVAILABLE"),
    (PoolTimeoutError(LEAK), "DATABASE_UNAVAILABLE"),
    (DisconnectionError(LEAK), "DATABASE_UNAVAILABLE"),
    (database(IntegrityError), "DATABASE_ERROR"),
    (database(ProgrammingError), "DATABASE_ERROR"),
    (database(DataError), "DATABASE_ERROR"),
    (SQLAlchemyError(LEAK), "DATABASE_ERROR"),
]


@pytest.mark.parametrize("error,reason", CLASSIFIED)
def test_every_failure_class_maps_to_one_stable_code(error, reason):
    assert data_cli.failure_reason(error) == reason


def test_validation_text_is_never_a_reason():
    assert data_cli.failure_reason(validation_error()) == "UNCLASSIFIED"


class Lease:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *details):
        return False

    def scalar(self, statement):
        self.engine.statements.append(str(statement))
        return self.engine.lock

    def execute(self, statement):
        self.engine.statements.append(str(statement))


class FakeEngine:
    def __init__(self, lock=True):
        self.lock, self.connections, self.statements, self.disposed = lock, 0, [], False

    def connect(self):
        self.connections += 1
        return Lease(self)

    def dispose(self):
        self.disposed = True


class ReportStore:
    def __init__(self, engine, root, managed_root):
        self.engine = engine

    def manifests(self):
        return []

    def events(self):
        return []

    def verified_manifests(self):
        return []

    def reconcile(self):
        return {"verified_manifests": 0, "unpublished_orphans": 0, "staging_files": 0}


def no_git(*arguments, **options):
    raise AssertionError("read-only commands need no code revision")


def run_main(monkeypatch, capsys, argv, store, engine=None, git=no_git):
    monkeypatch.setenv("DATA_DB_PASSWORD", "synthetic-" + "0" * 32)
    monkeypatch.setattr(sys, "argv", ["auvexo-data", *argv])
    monkeypatch.setattr(data_cli.signal, "signal", lambda signum, handler: None)
    monkeypatch.setattr(data_cli, "create_engine", lambda *a, **k: engine or FakeEngine())
    monkeypatch.setattr(data_cli, "DataStore", store)
    monkeypatch.setattr(data_cli.subprocess, "check_output", git)
    code = data_cli.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, captured.out


@pytest.mark.parametrize("error,reason", CLASSIFIED)
def test_main_reports_the_reason_and_never_the_exception_text(monkeypatch, capsys, error, reason):
    def broken(engine, root, managed_root):
        raise error

    code, out = run_main(monkeypatch, capsys, ["verify"], broken)
    assert code == 1 and json.loads(out) == FAILED | {"reason": reason}
    assert not any(secret in out for secret in SECRETS)


@pytest.mark.parametrize(
    "argv",
    [["coverage"], ["verify"], ["evidence"], ["qualification", "--start-day", "2026-10-18"]],
)
def test_read_only_commands_never_take_the_collector_lease(monkeypatch, capsys, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    engine = FakeEngine()
    code, out = run_main(monkeypatch, capsys, argv, ReportStore, engine)
    assert code == 0 and json.loads(out) is not None
    assert engine.connections == 0 and engine.statements == [] and engine.disposed


def test_collection_commands_still_need_the_exclusive_lease(monkeypatch, capsys):
    engine = FakeEngine(lock=False)
    code, out = run_main(
        monkeypatch,
        capsys,
        ["collect", "--enable-public-data", "--cycles", "1"],
        ReportStore,
        engine,
        git=lambda *arguments, **options: "",
    )
    assert code == 1 and json.loads(out) == FAILED | {"reason": "COLLECTOR_ALREADY_RUNNING"}
    assert engine.connections == 1
    assert engine.statements == ["SELECT pg_try_advisory_lock(20801403)"]


def test_catchup_is_refused_outside_collect_and_collection_stays_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["auvexo-data", "verify", "--catchup"])
    with pytest.raises(SystemExit) as refused:
        data_cli.main()
    assert refused.value.code == 2
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["auvexo-data", "collect", "--catchup"])
    assert data_cli.main() == 2
    assert json.loads(capsys.readouterr().out)["code"] == "COLLECTOR_DISABLED"


SCHEDULE = "public-data-2300-pkt-v1"
STARTED = datetime(2026, 10, 18, 17, 57, 3, 250000, tzinfo=UTC)


def write_summary(directory, started=STARTED, name=None, **changes):
    payload = {
        "started_at": started.isoformat(),
        "schedule_id": SCHEDULE,
        "mode": "scheduled",
        "status": "COMMAND_COMPLETE",
        "qualification": "NOT_INFERRED; use verified calendar qualification command",
    } | changes
    stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / (name or f"{stamp}-0123456789ab.json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_qualification_command_binds_days_to_wrapper_receipts(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".local" / "scheduled-data"
    directory.mkdir(parents=True)
    write_summary(directory)
    write_summary(directory, STARTED + timedelta(days=1), status="FAILED")
    (directory / "20261020T175700000000Z-0123456789ab.json").write_text("{damaged")
    code, out = run_main(
        monkeypatch, capsys, ["qualification", "--start-day", "2026-10-18"], ReportStore
    )
    report = json.loads(out)
    assert code == 0 and report["status"] == "OPEN"
    assert [day["scheduled_summary"] for day in report["days"]] == [
        "MATCHED",
        "NOT_COMPLETE",
        "MISSING",
        "MISSING",
        "MISSING",
        "MISSING",
        "MISSING",
    ]
    # A receipt without verified events is never a qualifying day.
    assert all(day["status"] != "PASS" for day in report["days"])
    assert report["scheduled_summary_files"] == {"accepted": 2, "rejected": 1}


def test_summary_reader_is_strict_bounded_and_read_only(tmp_path):
    directory = tmp_path / "scheduled-data"
    assert data_cli.scheduled_summaries(directory) == ([], 0)
    directory.mkdir()
    karachi = (STARTED + timedelta(days=1)).astimezone(timezone(timedelta(hours=5)))
    write_summary(directory)
    write_summary(directory, karachi, status="MISSED_START")
    # Unrelated files are not receipts and are ignored.
    for name in ("receipt.json", "accepted.raw", "20261018T175703250000Z-0123456789ab.log"):
        (directory / name).write_text("{}")
    # Receipt-named files that are not exactly a wrapper receipt are rejected, not guessed.
    day = timedelta(days=1)
    (directory / "20261101T175700000000Z-0123456789ab.json").write_text("{damaged")
    (directory / "20261102T175700000000Z-0123456789ab.json").write_text("[]")
    (directory / "20261103T175700000000Z-0123456789ab.json").write_bytes(b"[" * 60000)
    (directory / "20261104T175700000000Z-0123456789ab.json").write_bytes(b"\xff\xfe")
    (directory / "20261105T175700000000Z-0123456789ab.json").mkdir()
    write_summary(directory, STARTED + 20 * day, name="20261106T175700000000Z-0123456789ab.json")
    naive = write_summary(directory, STARTED + 21 * day)
    naive.write_text(naive.read_text().replace("+00:00", ""))
    write_summary(directory, STARTED + 22 * day, status=5)
    write_summary(directory, STARTED + 23 * day, mode=None)
    write_summary(directory, STARTED + 24 * day, schedule_id="s" * 65)
    write_summary(directory, STARTED + 25 * day, padding="p" * data_cli.MAX_SUMMARY_BYTES)
    write_summary(directory, STARTED + 26 * day, started_at="yesterday evening")
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir()}

    accepted, rejected = data_cli.scheduled_summaries(directory)

    assert accepted == [
        ScheduledSummary(STARTED, SCHEDULE, "scheduled", "COMMAND_COMPLETE"),
        ScheduledSummary(STARTED + day, SCHEDULE, "scheduled", "MISSED_START"),
    ]
    assert accepted[1].started_at.utcoffset() == timedelta(0)
    assert rejected == 12
    assert before == {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir()}


def test_summary_reader_refuses_an_unsafe_directory_and_an_unbounded_scan(tmp_path, monkeypatch):
    not_a_directory = tmp_path / "scheduled-data"
    not_a_directory.write_text("")
    with pytest.raises(ValueError, match="^UNSAFE_LOG_DIRECTORY$"):
        data_cli.scheduled_summaries(not_a_directory)
    directory = tmp_path / "receipts"
    directory.mkdir()
    write_summary(directory)
    write_summary(directory, STARTED + timedelta(days=1))
    monkeypatch.setattr(data_cli, "MAX_SUMMARIES", 1)
    with pytest.raises(ValueError, match="^REPORT_BUDGET_EXCEEDED$"):
        data_cli.scheduled_summaries(directory)


def backlog(monkeypatch, provider_now):
    """Both feeds 2,500 minutes behind, with the CLI on the same host clock."""
    world = World(provider_now=provider_now)
    collector, store = collector_for(monkeypatch, world)

    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.local_now()

    monkeypatch.setattr(data_cli, "datetime", HostClock)
    head = provider_now.replace(second=0, microsecond=0)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        store.behind(f"DS-02.{symbol}.1m", head - 2500 * MINUTE)
    return world, collector, store, head


def test_warmup_catchup_clears_the_backlog_before_the_normal_cycles(monkeypatch):
    world, collector, store, head = backlog(
        monkeypatch, datetime(2026, 10, 21, 17, 57, 10, tzinfo=UTC)
    )
    result = data_cli.collect(collector, Event(), 1, True)
    assert result["catchup"] == {"BTCUSDT": "CAUGHT_UP", "ETHUSDT": "CAUGHT_UP"}
    assert result["status"] == "STOPPED" and result["requests"] == collector.http.requests == 12
    assert {c.next_open for c in store.checkpoints.values()} == {head}
    # The normal cycle then finds nothing owed, exactly as on an ordinary night.
    assert len(world.klines_urls()) == 6
    assert (store.events[-1].feed_key, store.events[-1].reason) == (
        "public.collector",
        "BUDGET_COMPLETE",
    )


@pytest.mark.parametrize(
    "provider_now",
    [
        datetime(2026, 10, 21, 17, 59, 30, tzinfo=UTC),
        datetime(2026, 10, 21, 18, 0, 10, tzinfo=UTC),
        datetime(2026, 10, 21, 18, 11, 50, tzinfo=UTC),
    ],
)
def test_catchup_never_runs_at_or_inside_the_qualifying_window(monkeypatch, provider_now):
    world, collector, store, head = backlog(monkeypatch, provider_now)
    result = data_cli.collect(collector, Event(), 1, True)
    assert result["catchup"] == {"BTCUSDT": "WINDOW_GUARD", "ETHUSDT": "WINDOW_GUARD"}
    # Only the ordinary cycle polled: one capped request per symbol, as without the flag.
    assert len(world.klines_urls()) == 2 and result["requests"] == 4
    assert {c.next_open for c in store.checkpoints.values()} == {head - 1500 * MINUTE}

    plain_world, plain, plain_store, _ = backlog(monkeypatch, provider_now)
    plain_result = data_cli.collect(plain, Event(), 1, False)
    assert "catchup" not in plain_result and plain_result["requests"] == 4
    assert [e.reason for e in plain_store.events] == [e.reason for e in store.events]
    assert plain_store.checkpoints == store.checkpoints


def test_catchup_stops_at_its_time_budget_and_on_cancellation(monkeypatch):
    world, collector, store, _ = backlog(
        monkeypatch, datetime(2026, 10, 21, 17, 57, 10, tzinfo=UTC)
    )
    # Monotonic readings: start, one permitted BTC poll, then the 90-second budget is spent.
    readings = iter([0.0, 89.9, 90.0, 90.0, 90.0])
    monkeypatch.setattr(data_cli, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    result = data_cli.collect(collector, Event(), 1, True)
    assert result["catchup"] == {"BTCUSDT": "DEADLINE", "ETHUSDT": "DEADLINE"}
    assert len(world.klines_urls()) == 3

    world, collector, store, head = backlog(
        monkeypatch, datetime(2026, 10, 21, 17, 57, 10, tzinfo=UTC)
    )
    monkeypatch.setattr(data_cli, "time", SimpleNamespace(monotonic=lambda: 0.0))
    cancelled = Event()
    cancelled.set()
    result = data_cli.collect(collector, cancelled, 1, True)
    assert result["catchup"] == {"BTCUSDT": "CANCELLED", "ETHUSDT": "CANCELLED"}
    assert world.urls == [] and store.events[-1].reason == "CANCELLED"


def test_full_window_with_clock_proofs_fits_the_http_budget_and_cadence(monkeypatch):
    # The collection child starts about five seconds into the window, after a warm-up
    # that left both checkpoints at 17:58. Waits and round trips advance simulated time.
    opened = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
    world = World(provider_now=opened + timedelta(seconds=5), latency=timedelta(milliseconds=300))
    collector, store = collector_for(monkeypatch, world)

    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.local_now()

    monkeypatch.setattr(data_cli, "datetime", HostClock)
    monkeypatch.setattr(
        data_cli,
        "time",
        SimpleNamespace(monotonic=lambda: (world.provider_now - opened).total_seconds()),
    )
    for symbol in ("BTCUSDT", "ETHUSDT"):
        store.behind(f"DS-02.{symbol}.1m", opened - 2 * MINUTE)
    cancel = SimpleNamespace(is_set=lambda: False, wait=world.wait)

    result = data_cli.collect(collector, cancel, 12, False)

    # Twelve cycles, two symbols, one clock proof and one klines request each.
    assert result["requests"] == 48 and collector.http.max_requests == 128
    assert world.urls.count(CLOCK_URL) == 24 and len(world.klines_urls()) == 24
    for symbol in ("BTCUSDT", "ETHUSDT"):
        feed = [e for e in store.events if e.feed_key == f"DS-02.{symbol}.1m"]
        times = [e.observed_at for e in feed]
        assert len(feed) == 12 and all(e.state == "FRESH" for e in feed)
        assert opened <= times[0] and times[-1] < opened + 12 * MINUTE
        assert (times[-1] - times[0]).total_seconds() >= 600
        assert all((b - a).total_seconds() <= 120 for a, b in zip(times, times[1:], strict=False))
