"""OBV2-06 scheduler provenance from injected process facts and event XML; read-only."""

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from auvexo_alpha.infrastructure import scheduler_provenance
from auvexo_alpha.infrastructure.scheduler_provenance import (
    ProcessLink,
    WindowsSchedulerLog,
    current_provenance,
    evaluate_provenance,
)

TASK = "\\AuvexoAlpha-Paper-Observation"
START = datetime(2026, 11, 20, 16, tzinfo=UTC)
END = START + timedelta(seconds=15)
SCHEDULE = 1880
INSTANCE = "{4f6c1d2e-8a9b-4c3d-9e1f-0a1b2c3d4e5f}"
LAUNCHER = "C:\\Owner\\Alpha\\.venv\\Scripts\\python.exe"
INTERPRETER = "C:\\Python313\\python.exe"


def event(event_id, data, *, at=START + timedelta(milliseconds=12), activity=INSTANCE):
    """Shape of one `wevtutil qe /f:xml` Task Scheduler Operational record."""
    correlation = "" if activity is None else f"<Correlation ActivityID='{activity}'/>"
    fields = "".join(f"<Data Name='{name}'>{value}</Data>" for name, value in data.items())
    return (
        "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
        "<Provider Name='Microsoft-Windows-TaskScheduler' "
        "Guid='{de7b24ea-73c8-4a09-985d-5bdadcfa9017}'/>"
        f"<EventID>{event_id}</EventID><Version>0</Version><Level>4</Level>"
        f"<TimeCreated SystemTime='{at.strftime('%Y-%m-%dT%H:%M:%S.%f')}0Z'/>"
        f"<EventRecordID>7</EventRecordID>{correlation}"
        "<Execution ProcessID='1880' ThreadID='4242'/>"
        "<Channel>Microsoft-Windows-TaskScheduler/Operational</Channel>"
        "<Computer>synthetic-host</Computer><Security UserID='S-1-5-18'/></System>"
        f"<EventData Name='synthetic'>{fields}</EventData></Event>"
    )


def time_trigger(**changes):
    return event("107", {"TaskName": TASK, "InstanceId": INSTANCE}, **changes)


def user_trigger(**changes):
    return event(
        "110", {"TaskName": TASK, "InstanceId": INSTANCE, "UserContext": "owner"}, **changes
    )


def created(pid=4100, path=LAUNCHER, **changes):
    return event(
        "129",
        {"TaskName": TASK, "Path": path, "ProcessID": str(pid), "Priority": "7"},
        **changes,
    )


class Log:
    def __init__(self, xml="", *, enabled=True, error=None):
        self.xml, self.on, self.error, self.queries = xml, enabled, error, []

    def enabled(self):
        return self.on

    def events(self, start, end):
        self.queries.append((start, end))
        if self.error is not None:
            raise self.error
        return self.xml


# The task starts the virtual environment's launcher, which runs the interpreter.
VENV_CHAIN = (
    ProcessLink(5200, "python.exe", INTERPRETER),
    ProcessLink(4100, "python.exe", LAUNCHER),
    ProcessLink(SCHEDULE, "svchost.exe", "C:\\Windows\\System32\\svchost.exe"),
)


def decide(log, *, chain=VENV_CHAIN, schedule=SCHEDULE):
    return evaluate_provenance(
        task_path=TASK,
        window_start=START,
        window_end=END,
        chain=chain,
        schedule_pid=schedule,
        launcher=LAUNCHER,
        log=log,
    )


def test_time_triggered_instance_launched_by_the_scheduler_is_verified():
    log = Log(time_trigger() + created())
    result = decide(log)
    assert (result.status, result.reason) == ("VERIFIED", "TIME_TRIGGERED_TASK_INSTANCE")
    assert result.evidence_hash is not None
    # The query covers the start window plus two seconds of logging slack each side.
    assert log.queries == [(START - timedelta(seconds=2), END + timedelta(seconds=2))]


def test_a_directly_launched_interpreter_is_verified_too():
    chain = (ProcessLink(4100, "python.exe", INTERPRETER), VENV_CHAIN[2])
    assert decide(Log(time_trigger() + created(path=INTERPRETER)), chain=chain).status == (
        "VERIFIED"
    )


@pytest.mark.parametrize(
    "chain",
    (
        # A person in a terminal: the interpreter's parent is a shell.
        (VENV_CHAIN[0], ProcessLink(3000, "powershell.exe", "C:\\pwsh.exe"), VENV_CHAIN[2]),
        # A launcher that is not this environment's own.
        (
            VENV_CHAIN[0],
            ProcessLink(4100, "python.exe", "C:\\Other\\.venv\\Scripts\\python.exe"),
            VENV_CHAIN[2],
        ),
        # Two hops below the scheduler is not its child.
        (
            VENV_CHAIN[0],
            VENV_CHAIN[1],
            ProcessLink(3000, "cmd.exe", "C:\\cmd.exe"),
            VENV_CHAIN[2],
        ),
        (VENV_CHAIN[0],),
    ),
)
def test_a_process_not_started_by_the_scheduler_never_counts(chain):
    log = Log(time_trigger() + created())
    result = decide(log, chain=chain)
    assert (result.status, result.reason) == ("NOT_SCHEDULED", "PARENT_NOT_TASK_SCHEDULER")
    assert log.queries == []


def test_unknown_scheduler_service_or_disabled_log_is_unverifiable():
    assert decide(Log(), schedule=None).reason == "SCHEDULE_SERVICE_UNKNOWN"
    result = decide(Log(time_trigger() + created(), enabled=False))
    assert (result.status, result.reason) == ("UNVERIFIABLE", "TASK_SCHEDULER_LOG_DISABLED")


def test_run_from_the_task_scheduler_ui_records_a_user_trigger_and_never_counts():
    result = decide(Log(user_trigger() + created()))
    assert (result.status, result.reason) == ("NOT_SCHEDULED", "USER_TRIGGERED")
    # Even beside a time trigger, a user trigger for the same instance refuses.
    assert decide(Log(time_trigger() + user_trigger() + created())).reason == "USER_TRIGGERED"


@pytest.mark.parametrize(
    "xml,reason",
    (
        (time_trigger(at=START - timedelta(microseconds=1)) + created(), "NO_TIME_TRIGGER"),
        (time_trigger(at=END + timedelta(microseconds=1)) + created(), "NO_TIME_TRIGGER"),
        (
            time_trigger(activity="{00000000-0000-0000-0000-000000000000}").replace(
                INSTANCE, "{00000000-0000-0000-0000-000000000001}"
            )
            + created(),
            "NO_TIME_TRIGGER",
        ),
        (time_trigger().replace(TASK, "\\Other") + created(), "NO_TIME_TRIGGER"),
        (time_trigger(), "NO_TASK_PROCESS_CREATION"),
        (time_trigger() + created(pid=4101), "NO_TASK_PROCESS_CREATION"),
        (time_trigger() + created(path=INTERPRETER), "NO_TASK_PROCESS_CREATION"),
        (time_trigger() + created() + created(), "NO_TASK_PROCESS_CREATION"),
    ),
)
def test_missing_or_mismatched_log_facts_never_count(xml, reason):
    result = decide(Log(xml))
    assert result.status == "NOT_SCHEDULED" and result.reason.startswith(reason)


def test_exact_window_edges_count():
    for at in (START, END):
        assert decide(Log(time_trigger(at=at) + created())).status == "VERIFIED"


def test_process_creation_without_an_instance_or_unparseable_log_is_unverifiable():
    assert decide(Log(time_trigger() + created(activity=None))).reason == "TASK_INSTANCE_UNBOUND"
    assert decide(Log("<Event")).reason == "TASK_SCHEDULER_LOG_UNREADABLE"
    malformed = time_trigger().replace("SystemTime='", "SystemTime='x")
    assert decide(Log(malformed + created())).reason == "TASK_SCHEDULER_LOG_UNREADABLE"


def test_windows_log_reader_uses_the_system_tool_and_argument_lists_only(monkeypatch):
    calls = []
    outputs = iter(["name: Microsoft-Windows-TaskScheduler/Operational\nenabled: true\n", "<x/>"])

    def run(arguments, **options):
        calls.append((arguments, options))
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(scheduler_provenance.subprocess, "run", run)
    reader = WindowsSchedulerLog(lambda: Path("C:\\Windows\\System32\\wevtutil.exe"))
    assert reader.enabled() is True
    assert reader.events(START, END) == "<x/>"
    (gl, gl_options), (qe, _) = calls
    assert gl == ["C:\\Windows\\System32\\wevtutil.exe", "gl", scheduler_provenance.TASK_LOG]
    assert gl_options["check"] is True and "shell" not in gl_options
    assert qe[:4] == [
        "C:\\Windows\\System32\\wevtutil.exe",
        "qe",
        scheduler_provenance.TASK_LOG,
        "/f:xml",
    ]
    assert "@SystemTime>='2026-11-20T16:00:00.000Z'" in qe[4]
    assert "@SystemTime<='2026-11-20T16:00:15.000Z'" in qe[4]


def test_unknown_log_state_and_read_failures_are_unverifiable_not_raised(monkeypatch):
    def run(arguments, **options):
        return SimpleNamespace(stdout="enabled: maybe\n")

    monkeypatch.setattr(scheduler_provenance.subprocess, "run", run)
    reader = WindowsSchedulerLog(lambda: Path("wevtutil.exe"))
    with pytest.raises(ValueError, match="TASK_SCHEDULER_LOG_STATE_UNKNOWN"):
        reader.enabled()
    direct = (ProcessLink(4100, "python.exe", INTERPRETER), VENV_CHAIN[2])
    monkeypatch.setattr(scheduler_provenance, "process_chain", lambda: direct)
    monkeypatch.setattr(scheduler_provenance, "schedule_service_pid", lambda: SCHEDULE)
    result = current_provenance(TASK, window_start=START, window_end=END, log=reader)
    assert (result.status, result.reason) == ("UNVERIFIABLE", "PROVENANCE_READ_FAILED")

    def timeout(arguments, **options):
        raise subprocess.TimeoutExpired(arguments, 10)

    monkeypatch.setattr(scheduler_provenance.subprocess, "run", timeout)
    result = current_provenance(TASK, window_start=START, window_end=END, log=reader)
    assert result.status == "UNVERIFIABLE"
    verified = current_provenance(
        TASK,
        window_start=START,
        window_end=END,
        log=Log(time_trigger() + created(path=INTERPRETER)),
    )
    assert verified.status == "VERIFIED"
