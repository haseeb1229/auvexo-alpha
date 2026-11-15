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
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, cast

import auvexo_alpha
from auvexo_alpha.domain.oi_schedule import (
    OI_START_ACCEPTANCE_PATH,
    OIAcceptedStart,
    OIClockProof,
    OICollectionConfig,
    OIRuntimeIdentity,
    OIStartAcceptanceFile,
)

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


def _acceptance_only_descendant(git: str, root: Path, revision: str, reviewed: str) -> bool:
    """HEAD may add exactly the committed START acceptance file on top of the release.

    The acceptance binds the configuration, which binds the release revision, so it can
    never be inside that revision. Any other difference from the release refuses.
    """
    base = subprocess.check_output(
        [git, "--no-optional-locks", "-C", str(root), "merge-base", reviewed, revision],
        text=True,
        timeout=3,
    ).strip()
    changed = subprocess.check_output(
        [
            git,
            "--no-optional-locks",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            reviewed,
            revision,
        ],
        text=True,
        timeout=3,
    )
    return base == reviewed and [p for p in changed.split("\0") if p] == [OI_START_ACCEPTANCE_PATH]


def require_build(root: Path, config: OICollectionConfig) -> str:
    """Prove the exact clean reviewed build and return the HEAD commit that was proven."""
    git = str(git_executable(root))
    revision = head_commit(root)
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
        or (
            revision != config.git_revision
            and not _acceptance_only_descendant(git, root, revision, config.git_revision)
        )
        or oi_code_hash(root) != config.code_hash
        or hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest() != config.lock_hash
        or hashlib.sha256(
            (root / "docs/phase6/EXPERIMENT_PREREGISTRATION.md").read_bytes()
        ).hexdigest()
        != config.preregistration_hash
    ):
        raise ValueError("OI_BUILD_BINDING")
    return revision


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("OI_START_ACCEPTANCE_INVALID")
        result[key] = value
    return result


def committed_start_acceptances(root: Path, commit: str) -> OIStartAcceptanceFile:
    """Read the reviewed acceptance file from the commit's tree, never the working tree.

    The collector writes no Git object or ref. With the clean-tree gate, a START it could
    use must therefore exist as a reviewable commit in the pinned checkout's history.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("OI_START_ACCEPTANCE_INVALID")
    git = str(git_executable(root))
    blob = f"{commit}:{OI_START_ACCEPTANCE_PATH}"
    size = subprocess.check_output(
        [git, "--no-optional-locks", "-C", str(root), "cat-file", "-s", blob],
        text=True,
        timeout=3,
    ).strip()
    if not size.isascii() or not size.isdecimal() or not 1 <= int(size) <= 65536:
        raise ValueError("OI_START_ACCEPTANCE_INVALID")
    raw = subprocess.check_output(
        [git, "--no-optional-locks", "-C", str(root), "cat-file", "blob", blob], timeout=3
    )
    if len(raw) != int(size):
        raise ValueError("OI_START_ACCEPTANCE_INVALID")
    try:
        json.loads(raw, object_pairs_hook=_unique_keys)
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("OI_START_ACCEPTANCE_INVALID") from error
    return OIStartAcceptanceFile.model_validate_json(raw)


def head_commit(root: Path) -> str:
    revision = subprocess.check_output(
        [str(git_executable(root)), "--no-optional-locks", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        timeout=3,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("OI_BUILD_BINDING")
    return revision


def load_accepted_start(root: Path, commit: str, digest: str) -> OIAcceptedStart:
    """The exact committed START selected by the task's digest argument."""
    return OIAcceptedStart(
        acceptance_commit=commit,
        acceptance=committed_start_acceptances(root, commit).select(digest),
    )


def runtime_identity(root: Path) -> OIRuntimeIdentity:
    """This process's checkout and interpreter, compared with the accepted START."""
    executable = Path(sys.executable).resolve()
    base = Path(sys.base_prefix) / (
        "python.exe"
        if sys.platform == "win32"
        else f"bin/python{sys.version_info.major}.{sys.version_info.minor}"
    )
    return OIRuntimeIdentity(
        checkout_root=str(root.resolve()),
        python_executable=str(executable),
        python_executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        base_interpreter_sha256=hashlib.sha256(base.resolve().read_bytes()).hexdigest(),
    )


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


def system_executable(name: str, refusal: str) -> Path:
    """Absolute tool from the native system directory, never PATH or cwd.

    A bare tool name makes CreateProcess search the interpreter's directory and the
    current directory before System32, where a planted file could fabricate evidence
    (a trusted clock, a scheduler log). The system directory comes from the OS itself,
    not from an environment variable. Any failure raises ValueError(`refusal`).
    """
    if sys.platform != "win32":
        raise ValueError(refusal)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    api.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetSystemDirectoryW(buffer, len(buffer))
    if not count or count >= len(buffer):
        raise ValueError(refusal)
    system = Path(buffer.value)
    tool = system / name
    if not system.is_absolute() or not tool.is_file():
        raise ValueError(refusal)
    return tool


def w32tm_executable() -> Path:
    """The Windows Time tool; see `system_executable`."""
    return system_executable("w32tm.exe", "OI_CLOCK_UNTRUSTED")


_LOCAL_CLOCK_SOURCES = frozenset(
    {
        "local cmos clock",
        "free-running system clock",
        "local clock",
        "lo",
        "localhost",
        "127.0.0.1",
        "::1",
    }
)
ClockCheckStatus = Literal["PASS", "FAIL", "NOT_CHECKED"]


@dataclass(frozen=True)
class OIClockCheck:
    """One gate input: the observed text, the unchanged requirement and its outcome."""

    name: str
    observed: str | None
    requirement: str
    status: ClockCheckStatus


@dataclass(frozen=True)
class OIClockDiagnosis:
    checks: tuple[OIClockCheck, ...]
    age: Decimal | None
    bound: Decimal | None

    @property
    def trusted(self) -> bool:
        return all(check.status == "PASS" for check in self.checks)

    @property
    def failing(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if check.status == "FAIL")


def diagnose_clock_status(output: str, source: str | None) -> OIClockDiagnosis:
    """Evaluate every input of the frozen clock gate separately; read-only, no threshold change.

    The thresholds are exactly those of the accepted gate: leap indicator 0, stratum 1-15,
    a non-local source equal to the configured one, time since the last good sync within
    3600 s, nonnegative dispersion and delay, and |phase offset| + dispersion + delay/2
    at most 1 s. ``source`` None reports the configured-source comparison as NOT_CHECKED.
    """

    def field(name: str) -> str | None:
        found = re.search(r"^" + re.escape(name) + r":\s*(.+)$", output, re.MULTILINE)
        return None if found is None else found[1].strip()

    def seconds(name: str) -> Decimal | None:
        found = re.fullmatch(r"(-?[0-9]{1,10}(?:\.[0-9]{1,9})?)s", field(name) or "")
        return None if found is None else Decimal(found[1])

    def check(name: str, observed: str | None, requirement: str, ok: bool) -> OIClockCheck:
        return OIClockCheck(name, observed, requirement, "PASS" if ok else "FAIL")

    leap, stratum, observed_source = field("Leap Indicator"), field("Stratum"), field("Source")
    stratum_match = re.match(r"^([0-9]{1,2})(?:\D|$)", stratum or "")
    age = seconds("Time since Last Good Sync Time")
    dispersion, delay = seconds("Root Dispersion"), seconds("Root Delay")
    phase = seconds("Phase Offset")
    bound = (
        None
        if phase is None or dispersion is None or delay is None
        else abs(phase) + dispersion + delay / 2
    )
    checks = [
        check(
            "leap_indicator",
            leap,
            "0 (no warning)",
            re.match(r"^0(?:\D|$)", leap or "") is not None,
        ),
        check(
            "stratum",
            stratum,
            "1 to 15",
            stratum_match is not None and 1 <= int(stratum_match[1]) <= 15,
        ),
        check(
            "source_not_local",
            observed_source,
            "not a local, free-running or loopback clock",
            observed_source is not None
            and observed_source.casefold() not in _LOCAL_CLOCK_SOURCES
            and (source is None or source.strip().casefold() not in _LOCAL_CLOCK_SOURCES),
        ),
        check(
            "time_since_last_good_sync",
            field("Time since Last Good Sync Time"),
            "0 to 3600 s",
            age is not None and 0 <= age <= 3600,
        ),
        check(
            "root_dispersion",
            field("Root Dispersion"),
            "nonnegative seconds",
            dispersion is not None and dispersion >= 0,
        ),
        check(
            "root_delay",
            field("Root Delay"),
            "nonnegative seconds",
            delay is not None and delay >= 0,
        ),
        check("phase_offset", field("Phase Offset"), "seconds", phase is not None),
        check(
            "offset_bound",
            None if bound is None else f"{bound}s",
            "|phase offset| + root dispersion + root delay / 2 <= 1 s",
            bound is not None and bound <= 1,
        ),
    ]
    if source is None:
        checks.append(
            OIClockCheck(
                "source_equals_configured",
                observed_source,
                "configured clock_source",
                "NOT_CHECKED",
            )
        )
    else:
        checks.append(
            check("source_equals_configured", observed_source, source, observed_source == source)
        )
    return OIClockDiagnosis(tuple(checks), age, bound)


def read_clock_status() -> str:
    """The single read-only Windows Time query the gate and the diagnostic both use."""
    return subprocess.run(
        [str(w32tm_executable()), "/query", "/status", "/verbose"],
        capture_output=True,
        timeout=3,
        check=True,
        text=True,
    ).stdout


def inspect_clock(source: str) -> OIClockProof:
    """Read only; localized/ambiguous output refuses collection, never changes Windows time."""
    output = read_clock_status()
    diagnosis = diagnose_clock_status(output, source)
    if not diagnosis.trusted or diagnosis.age is None or diagnosis.bound is None:
        raise ValueError("OI_CLOCK_UNTRUSTED")
    return OIClockProof(
        source=source,
        inspected_at=datetime.now(UTC),
        time_since_sync_seconds=int(diagnosis.age.to_integral_value(rounding="ROUND_CEILING")),
        offset_bound_ms=int((diagnosis.bound * 1000).to_integral_value(rounding="ROUND_CEILING")),
        evidence_hash=hashlib.sha256(output.encode("utf8")).hexdigest(),
    )
