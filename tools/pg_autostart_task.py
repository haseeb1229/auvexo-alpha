"""Generate a candidate task that keeps an existing cluster running; never register it.

The action is `pg_ctl start` on an existing data directory and nothing else: no
initialisation, no role or database statements, no Python and no repository code. If
the cluster is already running, pg_ctl exits non-zero and changes nothing. If another
server holds the port, the new postmaster fails to bind and the log says so. Nothing is
started, stopped or registered by this tool.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time
from pathlib import Path
from subprocess import list2cmdline
from xml.etree.ElementTree import Element, SubElement, tostring

TASK_NAME = "AuvexoAlpha-PostgreSQL-Autostart"
TASK_VERSION = "postgresql.autostart.task.v1"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
# 20:35 Asia/Karachi: before the 21:00 PAPER run and the 20:45 protected window.
DAILY_START_UTC = time(15, 35)
SERVICE_IDENTITIES = {
    "system",
    "ntauthority\\system",
    "ntauthority\\localservice",
    "ntauthority\\networkservice",
    "s-1-5-18",
    "s-1-5-19",
    "s-1-5-20",
}


def _inside(path: Path, root: Path) -> bool:
    return path.is_absolute() and path.resolve().is_relative_to(root.resolve())


def task_definition(*, owner_identity: str, checkout: Path, first_day: date) -> str:
    if type(first_day) is not date:
        raise ValueError("AUTOSTART_TASK_DATE_INVALID")
    if not owner_identity.strip() or "\x00" in owner_identity or "\x00" in str(checkout):
        raise ValueError("AUTOSTART_TASK_CONFIG")
    if owner_identity.strip().casefold().replace(" ", "") in SERVICE_IDENTITIES:
        raise ValueError("AUTOSTART_TASK_INTERACTIVE_OWNER_REQUIRED")
    if not checkout.is_absolute():
        raise ValueError("AUTOSTART_TASK_ABSOLUTE_PATHS_REQUIRED")
    pg_ctl = checkout / ".local/toolchains/postgres/pgsql/bin/pg_ctl.exe"
    data = checkout / ".local/postgres-data"
    log = checkout / ".local/postgres-start.log"
    if not all(_inside(path, checkout) for path in (pg_ctl, data, log)):
        raise ValueError("AUTOSTART_TASK_PATH_OUTSIDE_CHECKOUT")
    root = Element("Task", {"version": "1.4", "xmlns": NS})
    info = SubElement(root, "RegistrationInfo")
    SubElement(info, "URI").text = "\\" + TASK_NAME
    SubElement(info, "Description").text = (
        TASK_VERSION + "; candidate definition only; owner installs after review"
    )
    triggers = SubElement(root, "Triggers")
    logon = SubElement(triggers, "LogonTrigger")
    SubElement(logon, "Enabled").text = "true"
    SubElement(logon, "UserId").text = owner_identity
    SubElement(logon, "Delay").text = "PT2M"
    daily = SubElement(triggers, "CalendarTrigger")
    SubElement(daily, "StartBoundary").text = (
        datetime.combine(first_day, DAILY_START_UTC, UTC).isoformat().replace("+00:00", "Z")
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
        ("AllowHardTerminate", "false"),
        ("StartWhenAvailable", "true"),
        ("RunOnlyIfNetworkAvailable", "false"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT5M"),
        ("Priority", "7"),
    ):
        SubElement(settings, name).text = value
    action = SubElement(SubElement(root, "Actions", {"Context": "Owner"}), "Exec")
    SubElement(action, "Command").text = str(pg_ctl)
    SubElement(action, "Arguments").text = list2cmdline(
        ["-D", str(data), "-l", str(log), "-w", "-t", "60", "start"]
    )
    SubElement(action, "WorkingDirectory").text = str(checkout)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + tostring(root, encoding="unicode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, help="interactive owner account")
    parser.add_argument("--checkout", required=True, type=Path, help="checkout holding the cluster")
    parser.add_argument("--first-day", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    xml = task_definition(
        owner_identity=args.owner, checkout=args.checkout, first_day=args.first_day
    )
    args.output.write_text(xml, encoding="utf-16")
    print(TASK_NAME + ": DEFINITION_ONLY; task not registered or started")


if __name__ == "__main__":
    main()
