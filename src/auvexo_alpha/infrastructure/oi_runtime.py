"""Local clock/resource and exact build checks for the optional OI collector."""

import ctypes
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import auvexo_alpha
from auvexo_alpha.domain.oi_schedule import OIClockProof, OICollectionConfig

# Executable code and schema live here; an untracked file in any of them is not the build.
_BUILD_SCOPES = ("src/", "tools/", "migrations/")


def oi_code_hash(root: Path) -> str:
    paths = sorted((root / "src").rglob("*.py")) + [
        root / "tools/run_oi_collection.py",
        root / "tools/oi_task.py",
    ]
    parts = [
        (p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths
    ]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("ascii")).hexdigest()


def git_executable(root: Path) -> Path:
    """One absolute git for the whole gate, never one the checkout or launch directory supplies.

    A bare name lets Windows (and ``shutil.which``) prefer the current directory, and an
    activated environment puts checkout directories on PATH; either could answer the
    revision and cleanliness questions about itself.
    """
    found = shutil.which("git")
    if found is None:
        raise ValueError("OI_BUILD_BINDING")
    lexical = Path(os.path.abspath(found))
    resolved = lexical.resolve()
    untrusted = {Path(os.path.abspath(root)), root.resolve(), Path.cwd(), Path.cwd().resolve()}
    if not resolved.is_file() or any(
        candidate.is_relative_to(directory)
        for candidate in (lexical, resolved)
        for directory in untrusted
    ):
        raise ValueError("OI_BUILD_BINDING")
    return resolved


def loaded_package_directory() -> Path:
    """Directory of the ``auvexo_alpha`` package this process actually imported."""
    origin: str | None = auvexo_alpha.__file__
    if not origin:
        raise ValueError("OI_BUILD_BINDING")
    return Path(origin).resolve().parent


def _python_sources(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*.py")
    }


def require_imported_tree(root: Path, package: Path) -> None:
    """The executing package must be byte-identical to the hashed checkout tree.

    Hashing ``root/src`` alone would accept an environment holding a stale installed
    copy while different code runs. Any changed, missing or extra ``.py`` refuses.
    """
    expected = _python_sources(root / "src" / "auvexo_alpha")
    if not expected or _python_sources(package) != expected:
        raise ValueError("OI_BUILD_BINDING")


def require_build(root: Path, config: OICollectionConfig) -> None:
    git = str(git_executable(root))
    revision = subprocess.check_output(
        [git, "--no-optional-locks", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        timeout=3,
    ).strip()
    status = subprocess.check_output(
        [
            git,
            "--no-optional-locks",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "-z",
            "--untracked-files=all",
        ],
        text=True,
        timeout=3,
    )
    # NUL-separated "XY path" entries. Any tracked change anywhere refuses, and so does
    # an untracked file under an executable scope; a rename's bare source path also does.
    dirty = any(
        entry[:2] != "??" or entry[3:].casefold().startswith(_BUILD_SCOPES)
        for entry in status.split("\0")
        if entry
    )
    require_imported_tree(root, loaded_package_directory())
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


def w32tm_executable() -> Path:
    """Absolute Windows Time tool from the native system directory, never PATH or cwd.

    A bare ``w32tm`` makes CreateProcess search the interpreter's directory and the
    current directory before System32, where a planted file could fabricate a trusted
    clock. The system directory comes from the OS itself, not from an environment variable.
    """
    if sys.platform != "win32":
        raise ValueError("OI_CLOCK_UNTRUSTED")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    api.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetSystemDirectoryW(buffer, len(buffer))
    if not count or count >= len(buffer):
        raise ValueError("OI_CLOCK_UNTRUSTED")
    system = Path(buffer.value)
    tool = system / "w32tm.exe"
    if not system.is_absolute() or not tool.is_file():
        raise ValueError("OI_CLOCK_UNTRUSTED")
    return tool


def inspect_clock(source: str) -> OIClockProof:
    """Read only; localized/ambiguous output refuses collection, never changes Windows time."""
    result = subprocess.run(
        [str(w32tm_executable()), "/query", "/status", "/verbose"],
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
