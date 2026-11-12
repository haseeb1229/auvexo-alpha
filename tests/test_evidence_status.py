"""Read-only evidence reporting: wrapper summaries are classified, never promoted."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from auvexo_alpha.application.evidence_status import classify_nights, summarize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import evidence_status as tool  # noqa: E402

SCHEDULE = "public-data-2300-pkt-v1"


def summary(started: str, status: str) -> dict[str, object]:
    return {"started_at": started, "schedule_id": SCHEDULE, "mode": "scheduled", "status": status}


def states(summaries: list[dict[str, object]], last: date) -> dict[str, str]:
    nights, _ = classify_nights(summaries, last_day=last)
    return {night.day.isoformat(): night.state for night in nights}


def test_each_night_is_classified_from_the_first_eligible_day() -> None:
    # Literal expectations written by hand from the schedule: pre-window is
    # 17:56:00 <= start < 18:00:00 UTC; the first eligible day is 2026-10-18.
    observed = states(
        [
            summary("2026-10-18T17:59:44.7+00:00", "MISSED_START"),
            summary("2026-10-19T17:57:03+00:00", "COMMAND_COMPLETE"),
            summary("2026-10-20T17:57:03+00:00", "FAILED"),
            summary("2026-10-21T18:26:28+00:00", "REFUSED_OUTSIDE_PREWINDOW"),
            # 2026-10-22 has no summary at all.
            summary("2026-10-23T17:57:00+00:00", "COMMAND_COMPLETE"),
            summary("2026-10-23T17:58:00+00:00", "COMMAND_COMPLETE"),
        ],
        date(2026, 10, 23),
    )
    assert observed == {
        "2026-10-18": "MISSED_START",
        "2026-10-19": "COMPLETE",
        "2026-10-20": "FAILED",
        "2026-10-21": "REFUSED",
        "2026-10-22": "NO_SUMMARY",
        "2026-10-23": "AMBIGUOUS",
    }


@pytest.mark.parametrize(
    ("started", "expected"),
    [
        ("2026-10-19T17:55:59.999999+00:00", "AMBIGUOUS"),  # more than four minutes early
        ("2026-10-19T17:56:00+00:00", "COMPLETE"),  # the tolerance bound itself is inside
        ("2026-10-19T17:59:59.999999+00:00", "COMPLETE"),
        ("2026-10-19T18:00:00+00:00", "AMBIGUOUS"),  # at the window start is too late
        ("2026-10-19T22:57:03+05:00", "COMPLETE"),  # the same instant written in Karachi time
    ],
)
def test_completed_run_counts_only_with_an_on_time_start(started: str, expected: str) -> None:
    assert (
        states([summary(started, "COMMAND_COMPLETE")], date(2026, 10, 19))["2026-10-19"] == expected
    )


def test_manual_preflight_foreign_schedule_and_garbage_never_count() -> None:
    preflight = summary("2026-10-19T17:57:00+00:00", "COMMAND_COMPLETE") | {"mode": "preflight"}
    foreign = summary("2026-10-19T17:57:00+00:00", "COMMAND_COMPLETE") | {"schedule_id": "other"}
    naive = summary("2026-10-19T17:57:00", "COMMAND_COMPLETE")
    nights, unreadable = classify_nights(
        [preflight, foreign, naive, {"started_at": 5}, {}], last_day=date(2026, 10, 19)
    )
    assert [night.state for night in nights] == ["NO_SUMMARY", "NO_SUMMARY"]
    assert unreadable == 1  # only the scheduled summary with an unusable start time


def test_summary_is_an_upper_bound_and_never_claims_qualification() -> None:
    nights, _ = classify_nights(
        [
            summary("2026-10-18T17:57:00+00:00", "COMMAND_COMPLETE"),
            summary("2026-10-19T17:57:00+00:00", "COMMAND_COMPLETE"),
            summary("2026-10-20T17:57:00+00:00", "FAILED"),
            summary("2026-10-21T17:57:00+00:00", "COMMAND_COMPLETE"),
        ],
        last_day=date(2026, 10, 22),
    )
    result = summarize(nights)
    assert result["nights"] == 5
    assert result["wrapper_complete_nights"] == 3
    assert result["longest_consecutive_complete"] == 2
    assert result["current_consecutive_complete"] == 0  # 2026-10-22 has no summary
    assert result["by_state"] == {"COMPLETE": 3, "FAILED": 1, "NO_SUMMARY": 1}
    assert result["qualification"] == "NOT_INFERRED"


def test_only_short_code_reasons_are_surfaced() -> None:
    leaky = summary("2026-10-18T17:57:00+00:00", "FAILED") | {
        "reason": "C:\\Users\\someone\\secret.txt password=hunter2"
    }
    coded = summary("2026-10-19T17:57:00+00:00", "FAILED") | {"reason": "DATABASE_UNAVAILABLE"}
    nights, _ = classify_nights([leaky, coded], last_day=date(2026, 10, 19))
    assert [night.reason for night in nights] == ["FAILED", "DATABASE_UNAVAILABLE"]


def _checkout(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (tmp_path / ".git/refs/heads").mkdir(parents=True)
    (tmp_path / ".git/refs/heads/main").write_text("a" * 40 + "\n", encoding="ascii")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/run_daily_window.py").write_text("", encoding="ascii")
    return tmp_path


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
    }


def test_tool_reports_without_writing_anything(tmp_path: Path, capsys) -> None:
    root = _checkout(tmp_path)
    scheduled = root / ".local/scheduled-data"
    scheduled.mkdir(parents=True)
    (scheduled / "a.json").write_text(
        json.dumps(summary("2026-10-18T17:57:00+00:00", "FAILED")), encoding="utf-8"
    )
    (scheduled / "broken.json").write_text("{not json", encoding="utf-8")
    (scheduled / "list.json").write_text("[]", encoding="utf-8")
    (scheduled / "run.log").write_text("ignored", encoding="utf-8")
    data = root / ".local/postgres-data"
    data.mkdir()
    (data / "PG_VERSION").write_text("17\n", encoding="ascii")
    (data / "postmaster.pid").write_text("999999999\n", encoding="ascii")
    before = _snapshot(root)

    assert tool.main(["--root", str(root), "--as-of", "2026-10-19"]) == 0

    assert _snapshot(root) == before, "the report must not create, touch or change any file"
    result = json.loads(capsys.readouterr().out)
    assert result["read_only"] is True
    assert result["checkout_head"] == "a" * 40
    public = result["phase2_public_data"]
    assert public["summary"]["by_state"] == {"FAILED": 1, "NO_SUMMARY": 1}
    assert public["summary"]["wrapper_complete_nights"] == 0
    assert public["unreadable_summaries"] == 2
    assert result["phase4_paper_observation"]["qualified_dates"] == "UNKNOWN"
    assert result["postgresql_cluster"] == {
        "data_directory_present": True,
        "pid_file": "STALE",
        "process": "NOT_RUNNING",
        "last_log_write": None,
    }


def test_tool_refuses_a_directory_that_is_not_a_checkout(tmp_path: Path, capsys) -> None:
    assert tool.main(["--root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "NOT_AN_AUVEXO_CHECKOUT"


def test_open_window_night_is_not_reported_until_it_closes(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    before_close = tool.report(root, datetime(2026, 10, 19, 18, 11, 59, tzinfo=UTC))
    after_close = tool.report(root, datetime(2026, 10, 19, 18, 12, 0, tzinfo=UTC))
    assert before_close["phase2_public_data"]["last_closed_day"] == "2026-10-18"
    assert after_close["phase2_public_data"]["last_closed_day"] == "2026-10-19"


def test_tool_source_has_no_write_database_or_process_start_calls() -> None:
    import ast

    tree = ast.parse(Path(tool.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not called & {
        "write_text", "write_bytes", "open", "mkdir", "unlink", "rename", "replace", "touch",
        "connect", "create_engine", "run", "Popen", "check_output", "system",
    }  # fmt: skip
    imported = {
        (node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported & {"subprocess", "psycopg", "sqlalchemy", "socket", "shutil"}
