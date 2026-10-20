"""Future task XML and source/resource controls; never register or launch a task."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import fromstring

import pytest
from observation_fixtures import BEGIN, make_config

from tools import run_paper_observation as cli
from tools.paper_observation_task import NS, TASK_NAME, TASK_VERSION, task_definition


def definition(root_path):
    return task_definition(
        owner_identity="synthetic\\limited.owner",
        python=root_path / "python.exe",
        script=root_path / "tools" / "run_paper_observation.py",
        config=root_path / "prepared.json",
        first_day=BEGIN.date(),
    )


def test_future_task_definition_has_no_elevation_catchup_password_wake_or_overlap():
    xml = definition(Path.cwd() / "synthetic-noncounting")
    root = fromstring(xml)

    def value(name):
        return root.find(".//{" + NS + "}" + name).text

    assert value("URI") == "\\" + TASK_NAME
    assert TASK_VERSION in value("Description")
    assert value("StartBoundary") == "2026-10-21T16:00:00Z"
    assert value("DaysInterval") == "1"
    assert value("LogonType") == "InteractiveToken"
    assert value("RunLevel") == "LeastPrivilege"
    assert value("MultipleInstancesPolicy") == "IgnoreNew"
    assert value("StartWhenAvailable") == "false"
    assert value("AllowStartOnDemand") == "false"
    assert value("WakeToRun") == "false"
    # At maximum 15-second start lateness this still stops by 17:00:30 UTC.
    assert value("ExecutionTimeLimit") == "PT1H15S"
    assert value("Arguments").endswith("--scheduled")
    assert "--config" in value("Arguments")
    assert "Password" not in xml and "HighestAvailable" not in xml


def test_task_helper_rejects_relative_paths_and_nul_owner():
    root_path = Path.cwd() / "synthetic-noncounting"
    options = dict(
        owner_identity="synthetic",
        python=root_path / "python",
        script=root_path / "tools" / "runner.py",
        config=root_path / "config",
        first_day=BEGIN.date(),
    )
    for key in ("python", "script", "config"):
        with pytest.raises(ValueError, match="ABSOLUTE_PATHS"):
            task_definition(**(options | {key: Path("relative")}))
    with pytest.raises(ValueError, match="TASK_CONFIG"):
        task_definition(**(options | {"owner_identity": "bad\x00owner"}))
    for owner in ("SYSTEM", "NT AUTHORITY\\SYSTEM", "S-1-5-18"):
        with pytest.raises(ValueError, match="INTERACTIVE_OWNER_REQUIRED"):
            task_definition(**(options | {"owner_identity": owner}))


@pytest.mark.parametrize("case", ("head", "changed", "untracked"))
def test_scheduled_source_refuses_wrong_head_or_executable_drift(monkeypatch, case):
    config = make_config()
    output = iter(
        [
            config.git_revision if case != "head" else "0" * 40,
            b"src/changed.py" if case == "changed" else b"",
            b"tools/untracked.py" if case == "untracked" else b"",
        ]
    )
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *args, **kwargs: next(output))
    with pytest.raises(ValueError, match="REVIEWED_SOURCE_MISMATCH"):
        cli.verify_scheduled_source(config)


def test_scheduled_source_accepts_only_exact_clean_committed_head(monkeypatch):
    config = make_config()
    output = iter([config.git_revision, b"", b""])
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *args, **kwargs: next(output))
    assert cli.verify_scheduled_source(config) is None


def test_resource_duration_is_monotonic_despite_large_wall_clock_jump(monkeypatch):
    cpu = iter([81.0, 81.0, 81.0, 80.0])
    ticks = iter([100.0, 159.0, 160.0, 161.0])
    monkeypatch.setattr(cli.psutil, "cpu_percent", lambda: next(cpu))
    monkeypatch.setattr(
        cli.psutil, "virtual_memory", lambda: SimpleNamespace(available=4_000_000_000)
    )
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    sampler = cli.ResourceSampler()
    values = [sampler(BEGIN + timedelta(days=offset)) for offset in range(4)]
    assert [value.cpu_high_for_seconds for value in values] == [0, 59, 60, 0]
