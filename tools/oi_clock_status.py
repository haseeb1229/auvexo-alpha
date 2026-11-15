"""Read-only report of every open-interest clock-gate input and which one fails.

    python tools/oi_clock_status.py [--source "time.windows.com,0x9"]

It runs the gate's own query (System32 ``w32tm /query /status /verbose``), applies the
unchanged gate thresholds input by input, and reads the Windows Time client settings
from the registry for context. It changes no time, service, registry or task state and
starts no network request. Exit code 0 means every gate input passes, 2 otherwise.
"""

import argparse
import json
import subprocess
import sys

from auvexo_alpha.domain.oi_schedule import windows_clock_source
from auvexo_alpha.infrastructure.oi_runtime import diagnose_clock_status, read_clock_status

_W32TIME = r"SYSTEM\CurrentControlSet\Services\W32Time"
_SETTINGS = (
    ("Parameters", "NtpServer"),
    ("Parameters", "Type"),
    ("TimeProviders\\NtpClient", "SpecialPollInterval"),
    ("Config", "MaxAllowedPhaseOffset"),
)


def time_service_settings() -> dict[str, object]:
    """Registry values that decide how often Windows Time syncs; read access only."""
    if sys.platform != "win32":
        return {"available": False}
    import winreg

    settings: dict[str, object] = {"available": True}
    for key, name in _SETTINGS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{_W32TIME}\\{key}") as handle:
                value, _kind = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            value = "ABSENT"
        settings[name] = value if isinstance(value, (int, str)) else "UNSUPPORTED_TYPE"
    return settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=windows_clock_source)
    args = parser.parse_args()
    try:
        output = read_clock_status()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"trusted": False, "query_error": type(error).__name__}))
        return 2
    diagnosis = diagnose_clock_status(output, args.source)
    print(
        json.dumps(
            {
                "trusted": diagnosis.trusted,
                "failing": list(diagnosis.failing),
                "checks": [
                    {
                        "input": check.name,
                        "observed": check.observed,
                        "requirement": check.requirement,
                        "status": check.status,
                    }
                    for check in diagnosis.checks
                ],
                "time_service_settings": time_service_settings(),
            },
            indent=2,
        )
    )
    return 0 if diagnosis.trusted else 2


if __name__ == "__main__":
    raise SystemExit(main())
