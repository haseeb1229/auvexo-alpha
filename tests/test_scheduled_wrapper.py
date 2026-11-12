import importlib.util
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from auvexo_alpha import data_cli
from auvexo_alpha.application.data_schedule import (
    CATCHUP_BUDGET,
    START_TOLERANCE,
    WARMUP_LEAD,
    catchup_permitted,
    prewindow,
    qualification_window,
)

spec = importlib.util.spec_from_file_location(
    "scheduled_wrapper", Path("tools/run_daily_window.py")
)
wrapper = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(Path("tools").resolve()))
spec.loader.exec_module(wrapper)


def test_only_pre_window_start_is_allowed():
    target, end = qualification_window(date(2026, 10, 18))
    start = target - WARMUP_LEAD
    pakistan = timezone(timedelta(hours=5))
    assert start == datetime(2026, 10, 18, 17, 57, tzinfo=UTC)
    assert start.astimezone(pakistan).isoformat() == "2026-10-18T22:57:00+05:00"
    assert target.astimezone(pakistan).isoformat() == "2026-10-18T23:00:00+05:00"
    assert end.astimezone(pakistan).isoformat() == "2026-10-18T23:12:00+05:00"
    assert wrapper.target_window(start) == target
    assert wrapper.target_window(start.astimezone(pakistan)) == target
    assert wrapper.target_window(target - timedelta(minutes=4)) == target
    assert wrapper.target_window(target - timedelta(microseconds=1)) == target
    for wrong in (
        target - timedelta(minutes=4, microseconds=1),
        target,
        target + timedelta(seconds=1),
        start + timedelta(hours=1),
        datetime(2026, 10, 17, 23, 57, tzinfo=UTC),
        start - timedelta(days=1),
    ):
        with pytest.raises(ValueError, match="OUTSIDE_PREWINDOW"):
            wrapper.target_window(wrong)
    with pytest.raises(ValueError, match="NAIVE"):
        wrapper.target_window(start.replace(tzinfo=None))


def test_warmup_overrun_refuses_late_collection(tmp_path, monkeypatch):
    target, _ = qualification_window(date(2026, 10, 18))
    clock = [target - WARMUP_LEAD]

    class Clock:
        @staticmethod
        def now(tz):
            return clock[0]

    calls = []

    def warmup(arguments, log, timeout):
        calls.append(arguments)
        clock[0] = target + timedelta(seconds=16)
        return {"returncode": 0, "errors": []}

    monkeypatch.setattr(wrapper, "datetime", Clock)
    monkeypatch.setattr(wrapper, "LOCAL", tmp_path)
    monkeypatch.setattr(wrapper, "protect", lambda path: path.mkdir())
    monkeypatch.setattr(wrapper, "run_bounded", warmup)
    monkeypatch.setattr(sys, "argv", ["run_daily_window.py", "--scheduled"])
    assert wrapper.main() == 1
    # Only the warm-up is given the backlog catch-up mode.
    assert calls == [["collect", "--enable-public-data", "--cycles", "2", "--catchup"]]
    receipt = next((tmp_path / "scheduled-data").glob("*.json")).read_text()
    assert "MISSED_START" in receipt and '"collection"' not in receipt


def test_rotation_removes_only_old_wrapper_logs(tmp_path):
    now = datetime.now(UTC)
    old = tmp_path / "20261001T000000000000Z-abcdef012345.log"
    old.write_text("old bounded output")
    os.utime(old, (0, 0))
    summary = tmp_path / "20261001T000000000000Z-abcdef012345.json"
    summary.write_text("keep observation summary")
    other = tmp_path / "accepted.raw"
    other.write_text("never clean unknown artifacts")
    wrapper.storage_budget(tmp_path, now)
    assert not old.exists() and summary.exists() and other.exists()


def test_storage_budget_refuses_growth_without_deleting_summaries(tmp_path, monkeypatch):
    summary = tmp_path / "receipt.json"
    summary.write_text("permanent")
    monkeypatch.setattr(wrapper, "DIRECTORY_LIMIT", 1)
    with pytest.raises(ValueError, match="QUOTA"):
        wrapper.storage_budget(tmp_path, datetime.now(UTC))
    assert summary.exists()


@pytest.mark.parametrize(
    "mode,timeout,reason", [("flood", 15, "LOG_LIMIT"), ("hang", 1, "CHILD_DEADLINE")]
)
def test_child_deadline_and_output_budget_stop_owned_process(
    tmp_path, monkeypatch, mode, timeout, reason
):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "data_local.py").write_text(
        "import sys,time\n"
        "if sys.argv[1]=='flood':\n"
        " sys.stdout.write('x'*(2*1024*1024));sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    log = tmp_path / "bounded.log"
    result = wrapper.run_bounded([mode], log, timeout)
    assert reason in result["errors"] and result["returncode"] != 0
    assert log.stat().st_size <= wrapper.LOG_LIMIT


def test_prewindow_and_catchup_guard_boundaries():
    target, end = qualification_window(date(2026, 10, 18))
    assert prewindow(date(2026, 10, 18)) == (target - START_TOLERANCE, target)
    assert prewindow(date(2026, 10, 18))[0] == datetime(2026, 10, 18, 17, 56, tzinfo=UTC)
    # Backlog polls may not start within thirty seconds of the window, nor inside it.
    assert catchup_permitted(datetime(2026, 10, 18, 17, 57, tzinfo=UTC))
    assert catchup_permitted(datetime(2026, 10, 18, 17, 59, 29, 999999, tzinfo=UTC))
    assert not catchup_permitted(datetime(2026, 10, 18, 17, 59, 30, tzinfo=UTC))
    assert not catchup_permitted(target)
    assert not catchup_permitted(end - timedelta(microseconds=1))
    assert catchup_permitted(end)
    assert not catchup_permitted(datetime(2026, 10, 18, 23, 5, tzinfo=timezone(timedelta(hours=5))))
    with pytest.raises(ValueError, match="NAIVE"):
        catchup_permitted(datetime(2026, 10, 18, 17, 57))
    # The child stops catching up well inside the wrapper's 150-second warm-up deadline.
    assert CATCHUP_BUDGET == timedelta(seconds=90)


CHILD = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "with Path('child-calls.jsonl').open('a') as stream:\n"
    "    stream.write(json.dumps(sys.argv[1:]) + chr(10))\n"
    "text, code = json.loads(Path('child-output.json').read_text())\n"
    "sys.stdout.write(text)\n"
    "raise SystemExit(code)\n"
)
LEAK = "C:\\Users\\owner\\secret.txt password=hunter2"
COMPLETE = json.dumps({"status": "STOPPED", "requests": 4, "bytes": 10}, indent=2) + "\n\n"


def failure(reason):
    return json.dumps({"code": "DATA_OPERATION_FAILED", "reason": reason}) + "\n"


def unexpected_child(arguments, log, timeout):
    raise AssertionError("a refused start must not launch a child")


def run_scheduled(tmp_path, monkeypatch, moments, child=None, bounded=unexpected_child):
    """Drive main() --scheduled with a scripted wrapper clock and a synthetic child."""
    moments = list(moments)

    class Clock:
        @staticmethod
        def now(tz):
            return moments.pop(0) if len(moments) > 1 else moments[0]

    monkeypatch.setattr(wrapper, "datetime", Clock)
    monkeypatch.setattr(wrapper, "LOCAL", tmp_path)
    monkeypatch.setattr(wrapper, "protect", lambda path: path.mkdir())
    if child is None:
        monkeypatch.setattr(wrapper, "run_bounded", bounded)
    else:
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "data_local.py").write_text(CHILD)
        (tmp_path / "child-output.json").write_text(json.dumps(child))
        monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_daily_window.py", "--scheduled"])
    code = wrapper.main()
    directory = tmp_path / "scheduled-data"
    (path,) = directory.glob("*.json")
    return code, json.loads(path.read_text()), path


TARGET, _ = qualification_window(date(2026, 10, 18))


@pytest.mark.parametrize(
    "started",
    [
        TARGET + timedelta(minutes=26, seconds=28),
        TARGET,
        TARGET - START_TOLERANCE - timedelta(microseconds=1),
        TARGET - WARMUP_LEAD - timedelta(days=1),
        TARGET - timedelta(hours=9),
    ],
)
def test_refused_start_leaves_a_summary_and_collects_nothing(
    tmp_path, monkeypatch, capsys, started
):
    code, summary, path = run_scheduled(tmp_path, monkeypatch, [started])
    assert code == 1
    assert summary["status"] == "REFUSED_OUTSIDE_PREWINDOW"
    assert summary["reason"] == "OUTSIDE_PREWINDOW_START"
    assert summary["mode"] == "scheduled" and summary["schedule_id"] == "public-data-2300-pkt-v1"
    assert summary["started_at"] == started.isoformat()
    assert summary["qualification"].startswith("NOT_INFERRED")
    assert "warmup" not in summary and "collection" not in summary
    # Exactly the one receipt: no log, no child, nothing rolled forward to another day.
    assert [entry.name for entry in path.parent.iterdir()] == [path.name]
    assert json.loads(capsys.readouterr().out) == summary
    # The qualification reader accepts the receipt, and it can satisfy no day.
    (parsed,), rejected = data_cli.scheduled_summaries(path.parent)
    assert rejected == 0 and parsed.started_at == started
    assert (parsed.mode, parsed.status) == ("scheduled", "REFUSED_OUTSIDE_PREWINDOW")


def test_on_time_run_completes_and_only_the_warmup_catches_up(tmp_path, monkeypatch):
    started = TARGET - WARMUP_LEAD
    code, summary, path = run_scheduled(
        tmp_path, monkeypatch, [started, TARGET + timedelta(seconds=1)], child=(COMPLETE, 0)
    )
    assert code == 0 and summary["status"] == "COMMAND_COMPLETE" and "reason" not in summary
    assert summary["warmup"]["reason"] is None and summary["collection"]["reason"] is None
    assert summary["qualification"].startswith("NOT_INFERRED")
    calls = [json.loads(line) for line in (tmp_path / "child-calls.jsonl").read_text().splitlines()]
    assert calls == [
        ["collect", "--enable-public-data", "--cycles", "2", "--catchup"],
        ["collect", "--enable-public-data", "--cycles", "12"],
    ]
    (parsed,), rejected = data_cli.scheduled_summaries(path.parent)
    assert rejected == 0 and parsed.started_at == started
    assert (parsed.mode, parsed.status) == ("scheduled", "COMMAND_COMPLETE")


@pytest.mark.parametrize(
    "output,reason",
    [
        (failure("DATABASE_UNAVAILABLE"), "DATABASE_UNAVAILABLE"),
        (
            "warning: noise\n" + failure("COLLECTOR_ALREADY_RUNNING") + "\n",
            "COLLECTOR_ALREADY_RUNNING",
        ),
        (failure(LEAK), "UNREPORTED"),
        (failure("database_unavailable"), "UNREPORTED"),
        (failure("A" * 65), "UNREPORTED"),
        (failure(["DATABASE_UNAVAILABLE"]), "UNREPORTED"),
        (failure("DATABASE_UNAVAILABLE") + "Traceback: " + LEAK + "\n", "UNREPORTED"),
        ('{"code":"COLLECTOR_DISABLED","execution_enabled":false}\n', "UNREPORTED"),
        ('["DATABASE_UNAVAILABLE"]\n', "UNREPORTED"),
        ("", "UNREPORTED"),
    ],
)
def test_failed_night_names_the_child_reason_and_never_copies_child_text(
    tmp_path, monkeypatch, capsys, output, reason
):
    code, summary, path = run_scheduled(
        tmp_path,
        monkeypatch,
        [TARGET - WARMUP_LEAD, TARGET + timedelta(seconds=1)],
        child=(output, 1),
    )
    assert code == 1 and summary["status"] == "FAILED" and summary["reason"] == reason
    expected = None if reason == "UNREPORTED" else reason
    assert summary["collection"]["reason"] == summary["warmup"]["reason"] == expected
    assert summary["qualification"].startswith("NOT_INFERRED")
    for text in (path.read_text(), capsys.readouterr().out):
        assert "hunter2" not in text and "secret.txt" not in text


def test_wrapper_stop_cause_outranks_the_child_reason(tmp_path, monkeypatch):
    def stopped(arguments, log, timeout):
        return {"returncode": 1, "errors": ["CHILD_DEADLINE"], "reason": "DATABASE_UNAVAILABLE"}

    code, summary, _ = run_scheduled(
        tmp_path,
        monkeypatch,
        [TARGET - WARMUP_LEAD, TARGET + timedelta(seconds=1)],
        bounded=stopped,
    )
    assert code == 1 and (summary["status"], summary["reason"]) == ("FAILED", "CHILD_DEADLINE")


@pytest.mark.parametrize(
    "fault,reason",
    [
        (OSError(LEAK), "WINDOW_WRAPPER_FAILED"),
        (ValueError("SCHEDULED_LOG_QUOTA"), "SCHEDULED_LOG_QUOTA"),
        (ValueError(LEAK), "WINDOW_WRAPPER_FAILED"),
    ],
)
def test_wrapper_fault_after_the_start_is_a_recorded_failed_night(
    tmp_path, monkeypatch, capsys, fault, reason
):
    def broken(arguments, log, timeout):
        raise fault

    code, summary, path = run_scheduled(
        tmp_path, monkeypatch, [TARGET - WARMUP_LEAD], bounded=broken
    )
    assert code == 1 and (summary["status"], summary["reason"]) == ("FAILED", reason)
    assert "warmup" not in summary and "collection" not in summary
    for text in (path.read_text(), capsys.readouterr().out):
        assert "hunter2" not in text and "secret.txt" not in text


def test_child_reason_reads_only_a_bounded_tail(tmp_path):
    log = tmp_path / "child.log"
    log.write_bytes(b"x" * (wrapper.LOG_LIMIT - 200) + b"\n" + failure("QUOTA").encode())
    assert wrapper.child_reason(log) == "QUOTA"
    # A final line longer than the tail is cut mid-JSON and is therefore not trusted.
    log.write_text(json.dumps({"padding": "p" * wrapper.REASON_TAIL, "reason": "QUOTA"}) + "\n")
    assert wrapper.child_reason(log) is None
    log.write_bytes(b"[" * wrapper.REASON_TAIL)
    assert wrapper.child_reason(log) is None
    log.write_bytes(b"\xff\xfe not text\n")
    assert wrapper.child_reason(log) is None
