"""Local clock/resource and exact build checks for the optional OI collector."""

import hashlib
import importlib
import json
import re
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from auvexo_alpha.domain.oi_schedule import OIClockProof, OICollectionConfig


def oi_code_hash(root: Path) -> str:
    paths = sorted((root / "src").rglob("*.py")) + [
        root / "tools/run_oi_collection.py",
        root / "tools/oi_task.py",
    ]
    parts = [
        (p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths
    ]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("ascii")).hexdigest()


def require_build(root: Path, config: OICollectionConfig) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        timeout=3,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        text=True,
        timeout=3,
    ).strip()
    if (
        dirty
        or revision != config.git_revision
        or oi_code_hash(root) != config.code_hash
        or hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest() != config.lock_hash
        or hashlib.sha256(
            (root / "docs/phase6/EXPERIMENT_PREREGISTRATION.md").read_bytes()
        ).hexdigest()
        != config.preregistration_hash
    ):
        raise ValueError("OI_BUILD_BINDING")


class _AvailableMemory(Protocol):
    available: int


class _FreeDisk(Protocol):
    free: int


class _ResourceProbe(Protocol):
    def virtual_memory(self) -> _AvailableMemory: ...
    def cpu_percent(self, interval: float) -> float: ...
    def disk_usage(self, path: str) -> _FreeDisk: ...


def resources_ready(root: Path) -> bool:
    # psutil is a pinned runtime dependency for the fail-closed resource preflight.
    # Missing or failed measurement yields rather than assuming resource headroom.
    try:
        probe = cast(_ResourceProbe, importlib.import_module("psutil"))
        return bool(
            probe.virtual_memory().available >= 2 * 1024**3
            and probe.cpu_percent(interval=0.05) < 80
            and probe.disk_usage(str(root)).free >= 60 * 1024**3
        )
    except (ImportError, OSError):
        return False


def inspect_clock(source: str) -> OIClockProof:
    """Read only; localized/ambiguous output refuses collection, never changes Windows time."""
    result = subprocess.run(
        ["w32tm", "/query", "/status", "/verbose"],
        capture_output=True,
        timeout=3,
        check=True,
        text=True,
    )
    output = result.stdout

    def field(name: str) -> str:
        found = re.search(r"^" + re.escape(name) + r":\s*(.+)$", output, re.MULTILINE)
        if found is None:
            raise ValueError("OI_CLOCK_UNTRUSTED")
        return found[1].strip()

    def seconds(name: str) -> Decimal:
        found = re.fullmatch(r"(-?[0-9]{1,10}(?:\.[0-9]{1,9})?)s", field(name))
        if found is None:
            raise ValueError("OI_CLOCK_UNTRUSTED")
        return Decimal(found[1])

    leap = re.match(r"^0(?:\D|$)", field("Leap Indicator"))
    stratum = re.match(r"^([0-9]{1,2})(?:\D|$)", field("Stratum"))
    age = seconds("Time since Last Good Sync Time")
    dispersion = seconds("Root Dispersion")
    delay = seconds("Root Delay")
    bound = abs(seconds("Phase Offset")) + dispersion + delay / 2
    if (
        not leap
        or not stratum
        or not 1 <= int(stratum[1]) <= 15
        or field("Source") != source
        or source.strip().casefold()
        in {
            "local cmos clock",
            "free-running system clock",
            "local clock",
            "lo",
            "localhost",
            "127.0.0.1",
            "::1",
        }
        or dispersion < 0
        or delay < 0
        or not 0 <= age <= 3600
        or bound > 1
    ):
        raise ValueError("OI_CLOCK_UNTRUSTED")
    return OIClockProof(
        source=source,
        inspected_at=datetime.now(UTC),
        time_since_sync_seconds=int(age.to_integral_value(rounding="ROUND_CEILING")),
        offset_bound_ms=int((bound * 1000).to_integral_value(rounding="ROUND_CEILING")),
        evidence_hash=hashlib.sha256(output.encode("utf8")).hexdigest(),
    )
