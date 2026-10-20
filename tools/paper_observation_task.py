"""Generate the future PAPER observation task definition; never register or start it."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time
from pathlib import Path
from subprocess import list2cmdline
from xml.etree.ElementTree import Element, SubElement, tostring

TASK_NAME = "AuvexoAlpha-Paper-Observation"
TASK_VERSION = "paper.observation.task.v1"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def task_definition(
    *, owner_identity: str, python: Path, script: Path, config: Path, first_day: date
) -> str:
    if type(first_day) is not date:
        raise ValueError("OBSERVATION_TASK_DATE_INVALID")
    if not owner_identity.strip() or any(
        "\x00" in str(item) for item in (owner_identity, python, script, config)
    ):
        raise ValueError("OBSERVATION_TASK_CONFIG")
    if owner_identity.strip().casefold().replace(" ", "") in {
        "system",
        "ntauthority\\system",
        "ntauthority\\localservice",
        "ntauthority\\networkservice",
        "s-1-5-18",
        "s-1-5-19",
        "s-1-5-20",
    }:
        raise ValueError("OBSERVATION_TASK_INTERACTIVE_OWNER_REQUIRED")
    if not all(path.is_absolute() for path in (python, script, config)):
        raise ValueError("OBSERVATION_TASK_ABSOLUTE_PATHS_REQUIRED")
    root = Element("Task", {"version": "1.4", "xmlns": NS})
    info = SubElement(root, "RegistrationInfo")
    SubElement(info, "URI").text = "\\" + TASK_NAME
    SubElement(info, "Description").text = (
        TASK_VERSION + "; definition only; separate reviewed owner START required"
    )
    triggers = SubElement(root, "Triggers")
    daily = SubElement(triggers, "CalendarTrigger")
    SubElement(daily, "StartBoundary").text = (
        datetime.combine(first_day, time(16), UTC).isoformat().replace("+00:00", "Z")
    )
    SubElement(daily, "Enabled").text = "true"
    SubElement(SubElement(daily, "ScheduleByDay"), "DaysInterval").text = "1"
    principal = SubElement(SubElement(root, "Principals"), "Principal", {"id": "Owner"})
    SubElement(principal, "UserId").text = owner_identity
    SubElement(principal, "LogonType").text = "InteractiveToken"
    SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = SubElement(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "false"),
        ("RunOnlyIfNetworkAvailable", "true"),
        ("AllowStartOnDemand", "false"),
        ("Enabled", "true"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT1H15S"),
        ("Priority", "7"),
    ):
        SubElement(settings, name).text = value
    action = SubElement(SubElement(root, "Actions", {"Context": "Owner"}), "Exec")
    SubElement(action, "Command").text = str(python)
    SubElement(action, "Arguments").text = list2cmdline(
        [str(script), "--config", str(config), "--scheduled"]
    )
    SubElement(action, "WorkingDirectory").text = str(script.parent.parent)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + tostring(root, encoding="unicode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--first-day", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    xml = task_definition(
        owner_identity=args.owner,
        python=args.python,
        script=args.script,
        config=args.config,
        first_day=args.first_day,
    )
    args.output.write_text(xml, encoding="utf-16")
    print(TASK_NAME + ": DEFINITION_ONLY; task not registered or started")


if __name__ == "__main__":
    main()
