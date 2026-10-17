import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "scheduled_wrapper", Path("tools/run_daily_window.py")
)
wrapper = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(Path("tools").resolve()))
spec.loader.exec_module(wrapper)


def test_only_pre_window_start_is_allowed():
    start = datetime(2026, 10, 17, 23, 57, tzinfo=UTC)
    assert wrapper.target_window(start) == datetime(2026, 10, 18, tzinfo=UTC)
    for wrong in (start - timedelta(minutes=5), start + timedelta(hours=1)):
        with pytest.raises(ValueError, match="OUTSIDE_PREWINDOW"):
            wrapper.target_window(wrong)


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
