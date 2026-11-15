"""Read-only Task Scheduler provenance of the current process (ADR-032 OBV2-06).

A run counts as scheduled only if its launched process is a direct child of the Task
Scheduler service and the Task Scheduler operational log records that process creation,
a time trigger for the same task instance inside the start window, and no user trigger
for that instance. Nothing here changes a task, a log setting or another process.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from xml.etree.ElementTree import Element, ParseError, fromstring, tostring

import psutil

from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.observation import ObservationProvenance
from auvexo_alpha.infrastructure.oi_runtime import system_executable

TASK_LOG = "Microsoft-Windows-TaskScheduler/Operational"
EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
TIME_TRIGGER, USER_TRIGGER, PROCESS_CREATED = "107", "110", "129"
# Task Scheduler writes these events a few milliseconds around the trigger instant.
LOG_SLACK = timedelta(seconds=2)


@dataclass(frozen=True)
class ProcessLink:
    pid: int
    name: str
    exe: str


class SchedulerLog(Protocol):
    def enabled(self) -> bool: ...
    def events(self, start: datetime, end: datetime) -> str: ...


@dataclass(frozen=True)
class _Event:
    event_id: str
    created: datetime
    activity: str | None
    data: dict[str, str]
    element: Element


def _events(xml: str) -> list[_Event]:
    root = fromstring("<Events>" + xml + "</Events>")
    found: list[_Event] = []
    for event in root.findall(EVENT_NS + "Event"):
        system = event.find(EVENT_NS + "System")
        if system is None:
            raise ValueError("TASK_SCHEDULER_EVENT_INVALID")
        identifier = system.findtext(EVENT_NS + "EventID")
        created = system.find(EVENT_NS + "TimeCreated")
        correlation = system.find(EVENT_NS + "Correlation")
        stamp = None if created is None else created.get("SystemTime")
        if identifier is None or stamp is None:
            raise ValueError("TASK_SCHEDULER_EVENT_INVALID")
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z", stamp)
        if match is None:
            raise ValueError("TASK_SCHEDULER_EVENT_INVALID")
        when = utc_time(match[1] + "." + (match[2] or "0").ljust(6, "0")[:6] + "Z")
        data = {
            str(item.get("Name")): (item.text or "").strip()
            for item in event.iter(EVENT_NS + "Data")
            if item.get("Name")
        }
        activity = None if correlation is None else correlation.get("ActivityID")
        found.append(
            _Event(
                identifier.strip(),
                when,
                activity.strip().lower() if activity else None,
                data,
                event,
            )
        )
    return found


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def evaluate_provenance(
    *,
    task_path: str,
    window_start: datetime,
    window_end: datetime,
    chain: Sequence[ProcessLink],
    schedule_pid: int | None,
    launcher: str | None,
    log: SchedulerLog,
) -> ObservationProvenance:
    """Decide provenance from injected process facts and log XML; fails closed."""

    def result(status: str, reason: str, hashed: bytes | None = None) -> ObservationProvenance:
        return ObservationProvenance.model_validate(
            {
                "status": status,
                "reason": reason,
                "evidence_hash": None if hashed is None else hashlib.sha256(hashed).hexdigest(),
            }
        )

    if schedule_pid is None:
        return result("UNVERIFIABLE", "SCHEDULE_SERVICE_UNKNOWN")
    if len(chain) >= 2 and chain[1].pid == schedule_pid:
        launched = chain[0]
    elif (
        len(chain) >= 3
        and launcher is not None
        and chain[1].name.lower() == "python.exe"
        and _same_path(chain[1].exe, launcher)
        and chain[2].pid == schedule_pid
    ):
        # The virtual-environment launcher the task starts runs the interpreter as its child.
        launched = chain[1]
    else:
        return result("NOT_SCHEDULED", "PARENT_NOT_TASK_SCHEDULER")
    if not log.enabled():
        return result("UNVERIFIABLE", "TASK_SCHEDULER_LOG_DISABLED")
    try:
        events = _events(log.events(window_start - LOG_SLACK, window_end + LOG_SLACK))
    except (ParseError, ValueError):
        return result("UNVERIFIABLE", "TASK_SCHEDULER_LOG_UNREADABLE")
    created = [
        e
        for e in events
        if e.event_id == PROCESS_CREATED
        and e.data.get("TaskName") == task_path
        and e.data.get("ProcessID") == str(launched.pid)
        and _same_path(e.data.get("Path", ""), launched.exe)
    ]
    if len(created) != 1:
        return result("NOT_SCHEDULED", "NO_TASK_PROCESS_CREATION")
    instance = created[0].activity
    if instance is None:
        return result("UNVERIFIABLE", "TASK_INSTANCE_UNBOUND")

    def same_instance(event: _Event) -> bool:
        named = event.data.get("InstanceId", "").strip().lower()
        return event.data.get("TaskName") == task_path and instance in (named, event.activity)

    if any(e.event_id == USER_TRIGGER and same_instance(e) for e in events):
        return result("NOT_SCHEDULED", "USER_TRIGGERED")
    triggers = [
        e
        for e in events
        if e.event_id == TIME_TRIGGER
        and same_instance(e)
        and window_start <= e.created <= window_end
    ]
    if len(triggers) != 1:
        return result("NOT_SCHEDULED", "NO_TIME_TRIGGER_IN_START_WINDOW")
    evidence = b"\n".join(tostring(e.element) for e in (triggers[0], created[0]))
    return result("VERIFIED", "TIME_TRIGGERED_TASK_INSTANCE", evidence)


class WindowsSchedulerLog:
    """System32 `wevtutil`, argument lists only; reads configuration and events."""

    def __init__(self, tool: Callable[[], Path] | None = None) -> None:
        self.tool = tool or (lambda: system_executable("wevtutil.exe", "TASK_SCHEDULER_LOG"))

    def _run(self, *arguments: str) -> str:
        return subprocess.run(
            [str(self.tool()), *arguments],
            capture_output=True,
            timeout=10,
            check=True,
            text=True,
        ).stdout

    def enabled(self) -> bool:
        found = re.search(r"^enabled:\s*(true|false)\s*$", self._run("gl", TASK_LOG), re.M)
        if found is None:
            raise ValueError("TASK_SCHEDULER_LOG_STATE_UNKNOWN")
        return found[1] == "true"

    def events(self, start: datetime, end: datetime) -> str:
        def stamp(value: datetime) -> str:
            return utc_time(value).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        query = (
            f"*[System[(EventID={TIME_TRIGGER} or EventID={USER_TRIGGER} or "
            f"EventID={PROCESS_CREATED}) and TimeCreated[@SystemTime>='{stamp(start)}' "
            f"and @SystemTime<='{stamp(end)}']]]"
        )
        return self._run("qe", TASK_LOG, "/f:xml", "/q:" + query)


def process_chain(depth: int = 3) -> tuple[ProcessLink, ...]:
    """This process and its ancestors, nearest first; read-only."""
    links: list[ProcessLink] = []
    process: psutil.Process | None = psutil.Process(os.getpid())
    while process is not None and len(links) < depth:
        links.append(ProcessLink(process.pid, process.name(), process.exe()))
        process = process.parent()
    return tuple(links)


def schedule_service_pid() -> int | None:
    """Process identifier of the running Task Scheduler service, or None."""
    if sys.platform != "win32":
        return None
    return psutil.win_service_get("Schedule").pid() or None


def current_provenance(
    task_path: str,
    *,
    window_start: datetime,
    window_end: datetime,
    log: SchedulerLog | None = None,
) -> ObservationProvenance:
    """Provenance of this process; an unreadable process tree or log is UNVERIFIABLE."""
    # A virtual environment's own launcher; the task's command names exactly this file.
    launcher = str(Path(sys.prefix) / "Scripts" / "python.exe")
    try:
        return evaluate_provenance(
            task_path=task_path,
            window_start=window_start,
            window_end=window_end,
            chain=process_chain(),
            schedule_pid=schedule_service_pid(),
            launcher=launcher,
            log=log or WindowsSchedulerLog(),
        )
    except (OSError, ValueError, subprocess.SubprocessError, psutil.Error):
        # Evidence only: a provenance that cannot be read is recorded as UNVERIFIABLE,
        # which can never let a night count.
        return ObservationProvenance(status="UNVERIFIABLE", reason="PROVENANCE_READ_FAILED")
