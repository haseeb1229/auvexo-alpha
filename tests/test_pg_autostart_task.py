"""Candidate PostgreSQL autostart task XML; never registers, starts or stops anything."""

from datetime import date
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest

from tools.pg_autostart_task import NS, TASK_NAME, TASK_VERSION, task_definition

CHECKOUT = Path.cwd() / "synthetic-noncounting-checkout"


def _values(xml: str, name: str) -> list[str]:
    return [node.text or "" for node in fromstring(xml).iter("{" + NS + "}" + name)]


def _value(xml: str, name: str) -> str:
    (only,) = _values(xml, name)
    return only


def test_definition_only_starts_an_existing_cluster_with_pg_ctl() -> None:
    xml = task_definition(
        owner_identity="synthetic\\limited.owner", checkout=CHECKOUT, first_day=date(2026, 12, 1)
    )
    assert _value(xml, "URI") == "\\" + TASK_NAME
    assert TASK_VERSION in _value(xml, "Description")
    command = Path(_value(xml, "Command"))
    assert command == CHECKOUT / ".local/toolchains/postgres/pgsql/bin/pg_ctl.exe"
    arguments = _value(xml, "Arguments")
    assert arguments.endswith(" start")
    assert str(CHECKOUT / ".local/postgres-data") in arguments
    # No initialisation, no Python, no SQL and no stop or restart verb.
    for forbidden in ("initdb", "python", "psql", "stop", "restart", "--create", "-c "):
        assert forbidden not in arguments.lower() and forbidden not in str(command).lower()
    assert _value(xml, "WorkingDirectory") == str(CHECKOUT)


def test_least_privilege_interactive_no_password_no_wake_no_kill() -> None:
    xml = task_definition(
        owner_identity="synthetic\\limited.owner", checkout=CHECKOUT, first_day=date(2026, 12, 1)
    )
    assert _value(xml, "LogonType") == "InteractiveToken"
    assert _value(xml, "RunLevel") == "LeastPrivilege"
    assert _value(xml, "WakeToRun") == "false"
    assert _value(xml, "MultipleInstancesPolicy") == "IgnoreNew"
    # Ending the task must never be able to terminate a postmaster it launched.
    assert _value(xml, "AllowHardTerminate") == "false"
    assert "Password" not in xml and "HighestAvailable" not in xml
    # Logon plus a daily retry at 20:35 Asia/Karachi, before the 20:45 protected window.
    assert _values(xml, "UserId") == ["synthetic\\limited.owner"] * 2
    assert _value(xml, "StartBoundary") == "2026-12-01T15:35:00Z"
    assert _value(xml, "Delay") == "PT2M"


def test_rejects_service_identities_relative_paths_and_nul() -> None:
    base = dict(owner_identity="synthetic", checkout=CHECKOUT, first_day=date(2026, 12, 1))
    for owner in ("SYSTEM", "NT AUTHORITY\\SYSTEM", "nt authority\\network service", "S-1-5-18"):
        with pytest.raises(ValueError, match="INTERACTIVE_OWNER_REQUIRED"):
            task_definition(**(base | {"owner_identity": owner}))
    with pytest.raises(ValueError, match="ABSOLUTE_PATHS"):
        task_definition(**(base | {"checkout": Path("relative")}))
    for bad in ({"owner_identity": "a\x00b"}, {"owner_identity": "  "}):
        with pytest.raises(ValueError, match="TASK_CONFIG"):
            task_definition(**(base | bad))
    with pytest.raises(ValueError, match="DATE_INVALID"):
        task_definition(**(base | {"first_day": "2026-12-01"}))
