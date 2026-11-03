"""Fixed MT5 runtime/package/OS binding; no SDK import, credential or session."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
import struct
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from uuid import uuid4

import psutil

from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.domain.ds03_authority import Ds03RuntimeBinding

PACKAGE_VERSION = "5.0.6231"
WHEEL_HASH = "3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797"
_PACKAGE_FILES = {
    "MetaTrader5/__init__.py": "2e3bc321ab35b5c9e6c777665f381bc686bbf60791160838a0e84406dc0052cf",
    "MetaTrader5/_core.cp313-win_amd64.pyd": (
        "b92756775337aff9c82cac078099da63c4486884539708ae0fbda3a7000b991d"
    ),
    "metatrader5-5.0.6231.dist-info/LICENSE.txt": (
        "76bb8db55f77cab31d293ed3c7059ed5623e9c54714f0857e0d92e0783571860"
    ),
}
_SOURCE_FILES = (
    "domain/contracts.py",
    "domain/ds03.py",
    "domain/ds03_actual.py",
    "domain/ds03_authority.py",
    "application/ds03.py",
    "application/ds03_actual.py",
    "application/ds03_ports.py",
    "infrastructure/ds03_ipc.py",
    "infrastructure/ds03_process.py",
    "infrastructure/ds03_fake.py",
    "infrastructure/ds03_mt5.py",
    "infrastructure/ds03_mt5_process.py",
    "infrastructure/ds03_mt5_binding.py",
    "infrastructure/ds03_secrets.py",
    "infrastructure/ds03_metadata.py",
    "infrastructure/oi_secrets.py",
)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def runtime_root() -> Path:
    return Path.home() / "Desktop" / "Auvexo Alpha MT5 Readonly Runtime"


def terminal_path() -> Path:
    return runtime_root() / "terminal" / "terminal64.exe"


def _path_hash(path: Path) -> str:
    return _hash(os.path.normcase(os.path.abspath(path)).encode("utf-8"))


def fixed_path_hashes() -> tuple[str, str, str]:
    return (
        _path_hash(runtime_root()),
        _path_hash(terminal_path()),
        _path_hash(terminal_path().parent),
    )


def _plain_path(path: Path, *, file: bool) -> None:
    # Never resolve away a junction/reparse point before validating every component.
    for current in (path, *path.parents):
        info = current.stat(follow_symlinks=False)
        if current.is_symlink() or current.is_junction():
            raise Ds03Error()
        if sys.platform == "win32" and info.st_file_attributes & 0x400:
            raise Ds03Error()
    info = path.stat(follow_symlinks=False)
    if file and (not path.is_file() or info.st_nlink != 1):
        raise Ds03Error()
    if not file and not path.is_dir():
        raise Ds03Error()


def verify_installed_package() -> str:
    """Verify the exact wheel payload without importing its native extension."""
    try:
        if sys.platform != "win32" or sys.version_info[:2] != (3, 13) or struct.calcsize("P") != 8:
            raise Ds03Error()
        dist = importlib.metadata.distribution("metatrader5")
        if (
            dist.version != PACKAGE_VERSION
            or not dist.files
            or importlib.metadata.version("numpy") != "2.4.6"
        ):
            raise Ds03Error()
        installed = {str(p).replace("\\", "/") for p in dist.files}
        expected = set(_PACKAGE_FILES)
        # -B prevents writes, not reads: any unexpected pyc can override reviewed source.
        source = {p for p in installed if p.startswith("MetaTrader5/")}
        if source != {p for p in expected if p.startswith("MetaTrader5/")}:
            raise Ds03Error()
        package_dir = Path(str(dist.locate_file("MetaTrader5")))
        _plain_path(package_dir, file=False)
        actual_files: set[str] = set()
        for actual in package_dir.rglob("*"):
            _plain_path(actual, file=not actual.is_dir())
            if actual.is_file():
                actual_files.add("MetaTrader5/" + actual.relative_to(package_dir).as_posix())
        if actual_files != {p for p in expected if p.startswith("MetaTrader5/")}:
            raise Ds03Error()
        for name, digest in _PACKAGE_FILES.items():
            if name not in installed:
                raise Ds03Error()
            actual = Path(str(dist.locate_file(name)))
            _plain_path(actual, file=True)
            if _hash(actual.read_bytes()) != digest:
                raise Ds03Error()
        return _hash(_canonical(_PACKAGE_FILES))
    except Exception:
        raise Ds03Error() from None


def _base_python() -> Path:
    # CPython exposes this runtime fact but typeshed intentionally omits the private name.
    # Read one fixed key; there is no caller-selected attribute or callable dispatch.
    value: object = vars(sys).get("_base_executable")
    if type(value) is not str or not value:
        raise Ds03Error()
    return Path(value)


def _loaded_python_dll() -> Path:
    if sys.platform != "win32":
        raise Ds03Error()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    api.GetModuleFileNameW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetModuleFileNameW(ctypes.pythonapi._handle, buffer, len(buffer))
    if not count or count >= len(buffer):
        raise Ds03Error()
    return Path(buffer.value)


def _interpreter_manifest() -> dict[str, str]:
    base = _base_python()
    dll = _loaded_python_dll()
    config = Path(sys.prefix) / "pyvenv.cfg"
    for file in (Path(sys.executable), base, dll, config):
        _plain_path(file, file=True)
    return {
        "python": _hash(Path(sys.executable).read_bytes()),
        "base_python": _hash(base.read_bytes()),
        "python_dll": _hash(dll.read_bytes()),
        "venv_config": _hash(config.read_bytes()),
        "python_version": _hash(sys.version.encode("ascii")),
    }


def source_binding() -> str:
    """Fixed reviewed implementation inventory, exact interpreter and SDK payload."""
    try:
        package = Path(__file__).resolve().parents[1]
        manifest = {name: _hash((package / name).read_bytes()) for name in _SOURCE_FILES}
        manifest.update(_interpreter_manifest())
        manifest["mt5_package"] = verify_installed_package()
        manifest["mt5_wheel"] = WHEEL_HASH
        return _hash(_canonical(manifest))
    except Exception:
        raise Ds03Error() from None


def _profile_identity() -> str:
    path = terminal_path().parent
    _plain_path(path, file=False)
    info = path.stat(follow_symlinks=False)
    if info.st_ino == 0:
        raise Ds03Error()
    return _hash(
        _canonical({"path": _path_hash(path), "device": info.st_dev, "inode": info.st_ino})
    )


def measure_binding(
    *,
    accepted_release_sha: str,
    accepted_release_tree: str,
    terminal_build: int,
    terminal_version: str,
) -> Ds03RuntimeBinding:
    """Accepted expected build/version are checked against live SDK only after admission.

    No SDK function or package import is used here. Exact future terminal bytes bind
    the accepted offline build claim; provider observations independently verify it.
    """
    try:
        if sys.platform != "win32":
            raise Ds03Error()
        expected_python = runtime_root() / ".venv" / "Scripts" / "python.exe"
        expected_package = runtime_root() / ".venv" / "Lib" / "site-packages" / "auvexo_alpha"
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(
            str(expected_python)
        ) or Path(__file__).resolve().parents[1] != expected_package.resolve(strict=True):
            raise Ds03Error()
        base = _base_python()
        if (
            not base.is_relative_to(runtime_root() / ".local" / "python")
            or base.name.casefold() != "python.exe"
            or _loaded_python_dll() != base.parent / "python313.dll"
        ):
            raise Ds03Error()
        _plain_path(base, file=True)
        _plain_path(expected_python, file=True)
        _plain_path(expected_package, file=False)
        _plain_path(terminal_path(), file=True)
        paths = fixed_path_hashes()
        return Ds03RuntimeBinding(
            release_sha=accepted_release_sha,
            release_tree=accepted_release_tree,
            connector_source_hash=source_binding(),
            interpreter_hash=_hash(Path(sys.executable).read_bytes()),
            package_manifest_hash=verify_installed_package(),
            terminal_binary_hash=_hash(terminal_path().read_bytes()),
            terminal_build=terminal_build,
            terminal_version=terminal_version,
            fixed_runtime_path_hash=paths[0],
            fixed_terminal_path_hash=paths[1],
            fixed_profile_path_hash=paths[2],
            profile_identity_hash=_profile_identity(),
        )
    except Exception:
        raise Ds03Error() from None


@dataclass(frozen=True)
class TerminalProcessEvidence:
    process_ref: str
    profile_hash: str
    terminal_path_hash: str
    terminal_binary_hash: str


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _terminal_pids() -> tuple[int, ...]:
    # Toolhelp exposes image basenames without opening privileged unrelated processes.
    # Only exact terminal64.exe candidates subsequently receive limited native queries.
    if sys.platform != "win32":
        raise Ds03Error()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    api.Process32FirstW.restype = wintypes.BOOL
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    api.Process32NextW.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        raise Ds03Error()
    found: list[int] = []
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        success = api.Process32FirstW(snapshot, ctypes.byref(entry))
        if not success:
            raise Ds03Error()
        while success:
            if entry.szExeFile.casefold() == "terminal64.exe":
                found.append(int(entry.th32ProcessID))
            success = api.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES is the only clean exhaustion.
            raise Ds03Error()
    finally:
        if not api.CloseHandle(snapshot):
            raise Ds03Error()
    return tuple(found)


def probe_terminal_process(binding: Ds03RuntimeBinding) -> TerminalProcessEvidence:
    """Unique exact image/owner/process-creation identity, never provider-reported PID."""
    try:
        if (
            measure_binding(
                accepted_release_sha=binding.release_sha,
                accepted_release_tree=binding.release_tree,
                terminal_build=binding.terminal_build,
                terminal_version=binding.terminal_version,
            )
            != binding
        ):
            raise Ds03Error()
        _plain_path(terminal_path(), file=True)
        paths = fixed_path_hashes()
        binary_hash = _hash(terminal_path().read_bytes())
        profile = _profile_identity()
        if (
            paths
            != (
                binding.fixed_runtime_path_hash,
                binding.fixed_terminal_path_hash,
                binding.fixed_profile_path_hash,
            )
            or binary_hash != binding.terminal_binary_hash
            or profile != binding.profile_identity_hash
        ):
            raise Ds03Error()
        owner = psutil.Process().username()
        matches: list[tuple[int, float, str]] = []
        for pid in _terminal_pids():
            process = psutil.Process(pid)
            try:
                exe = process.exe()
                if os.path.normcase(os.path.abspath(exe)) == os.path.normcase(str(terminal_path())):
                    observed_owner = process.username()
                    if observed_owner != owner:
                        raise Ds03Error()
                    matches.append((process.pid, process.create_time(), observed_owner))
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                raise Ds03Error() from None
            except psutil.AccessDenied:
                # An unreadable candidate cannot establish the unique accepted image.
                raise Ds03Error() from None
        if len(matches) != 1:
            raise Ds03Error()
        pid, created, observed_owner = matches[0]
        process_hash = _hash(
            _canonical(
                {
                    "pid": pid,
                    "created": created.hex(),
                    "owner": observed_owner,
                    "binary": binary_hash,
                    "profile": profile,
                    "path": paths[1],
                }
            )
        )
        return TerminalProcessEvidence(
            "ds03.process." + process_hash, profile, paths[1], binary_hash
        )
    except Exception:
        raise Ds03Error() from None


def verify_terminal_process(
    expected: TerminalProcessEvidence, binding: Ds03RuntimeBinding
) -> TerminalProcessEvidence:
    actual = probe_terminal_process(binding)
    if actual != expected:
        raise Ds03Error()
    return actual


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _resume_suspended_primary(process_id: int) -> None:
    """Resume only the single unstarted primary thread after Job containment.

    A venv redirector cannot spawn its base interpreter before assignment because
    CREATE_SUSPENDED is mandatory. No PID-guessing or unrelated thread mutation.
    """
    if sys.platform != "win32":
        raise Ds03Error()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    api.Thread32First.restype = wintypes.BOOL
    api.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    api.Thread32Next.restype = wintypes.BOOL
    api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenThread.restype = wintypes.HANDLE
    api.ResumeThread.argtypes = [wintypes.HANDLE]
    api.ResumeThread.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    snapshot = api.CreateToolhelp32Snapshot(4, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        raise Ds03Error()
    threads: list[int] = []
    entry = _ThreadEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        success = api.Thread32First(snapshot, ctypes.byref(entry))
        if not success:
            raise Ds03Error()
        while success:
            if entry.th32OwnerProcessID == process_id:
                threads.append(int(entry.th32ThreadID))
            success = api.Thread32Next(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18 or len(threads) != 1:
            raise Ds03Error()
    finally:
        if not api.CloseHandle(snapshot):
            raise Ds03Error()
    thread = api.OpenThread(2, False, threads[0])  # THREAD_SUSPEND_RESUME only.
    if not thread:
        raise Ds03Error()
    try:
        if api.ResumeThread(thread) != 1:
            raise Ds03Error()  # Unstarted CREATE_SUSPENDED thread must have count one.
    finally:
        if not api.CloseHandle(thread):
            raise Ds03Error()


class ProviderJob:
    """Fresh session Job; child receives only its name and opens QUERY access."""

    _api: ctypes.CDLL
    _handle: int | None
    _name: str

    @property
    def name(self) -> str:
        return self._name

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise Ds03Error()
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._api.CreateJobObjectW.restype = wintypes.HANDLE
        self._api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._api.SetInformationJobObject.restype = wintypes.BOOL
        self._api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._api.AssignProcessToJobObject.restype = wintypes.BOOL
        self._api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._api.OpenProcess.restype = wintypes.HANDLE
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        self._api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._api.TerminateJobObject.restype = wintypes.BOOL
        self._name = "Local" + chr(92) + "AuvexoAlphaDS03Readonly-" + uuid4().hex
        ctypes.set_last_error(0)
        self._handle = self._api.CreateJobObjectW(None, self._name)
        if not self._handle:
            raise Ds03Error()
        if ctypes.get_last_error() == 183:  # Never adopt or terminate a pre-existing object.
            existing, self._handle = self._handle, None
            if not self._api.CloseHandle(existing):
                raise Ds03Error()
            raise Ds03Error()
        limits = _ExtendedLimit()
        # KILL_ON_JOB_CLOSE | JOB_MEMORY. No BREAKAWAY_OK or SILENT_BREAKAWAY_OK.
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x200
        limits.JobMemoryLimit = 1024**3
        if not self._api.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise Ds03Error()

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        """Caller MUST use CREATE_SUSPENDED; assignment precedes the first instruction."""
        if not self._handle or process.poll() is not None:
            raise Ds03Error()
        handle = self._api.OpenProcess(0x100 | 0x1, False, process.pid)
        if not handle:
            raise Ds03Error()
        try:
            if not self._api.AssignProcessToJobObject(self._handle, handle):
                raise Ds03Error()
            _resume_suspended_primary(process.pid)
        finally:
            if not self._api.CloseHandle(handle):
                raise Ds03Error()

    def close(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            # QUERY-only child handles cannot prolong a provider session on cancellation.
            terminated = self._api.TerminateJobObject(handle, 1)
            closed = self._api.CloseHandle(handle)
            if not terminated or not closed:
                raise Ds03Error()

    def __enter__(self) -> ProviderJob:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()


def provider_job() -> ProviderJob:
    return ProviderJob()


def _validate_job_name(value: object) -> str:
    prefix = "Local" + chr(92) + "AuvexoAlphaDS03Readonly-"
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value) != len(prefix) + 32
        or any(character not in "0123456789abcdef" for character in value[len(prefix) :])
    ):
        raise Ds03Error()
    return value


def _current_job_pids(job_name: str) -> frozenset[int]:
    """QUERY-only proof of the exact authenticated session Job, never NULL/any Job."""
    name = _validate_job_name(job_name)
    if sys.platform != "win32":
        raise Ds03Error()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenJobObjectW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.QueryInformationJobObject.restype = wintypes.BOOL
    handle = api.OpenJobObjectW(4, False, name)  # JOB_OBJECT_QUERY only, noninheritable.
    if not handle:
        raise Ds03Error()
    try:
        limits = _ExtendedLimit()
        if not api.QueryInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
        ):
            raise Ds03Error()
        if limits.JobMemoryLimit != 1024**3 or limits.BasicLimitInformation.LimitFlags != 0x2200:
            raise Ds03Error()

        class ProcessList(ctypes.Structure):
            _fields_ = [
                ("assigned", wintypes.DWORD),
                ("count", wintypes.DWORD),
                ("pids", ctypes.c_size_t * 4096),
            ]

        result = ProcessList()
        if not api.QueryInformationJobObject(
            handle, 3, ctypes.byref(result), ctypes.sizeof(result), None
        ):
            raise Ds03Error()
        if not 0 < result.count == result.assigned <= 4096:
            raise Ds03Error()
        members = frozenset(int(result.pids[index]) for index in range(result.count))
        if os.getpid() not in members:
            raise Ds03Error()
        return members
    finally:
        if not api.CloseHandle(handle):
            raise Ds03Error()


def require_terminal_in_current_job(
    binding: Ds03RuntimeBinding, evidence: TerminalProcessEvidence, *, job_name: str
) -> None:
    """Provider-child-only proof: an existing/uncontained terminal cannot be adopted."""
    try:
        if probe_terminal_process(binding) != evidence:
            raise Ds03Error()
        selected = tuple(
            pid
            for pid in _terminal_pids()
            if os.path.normcase(os.path.abspath(psutil.Process(pid).exe()))
            == os.path.normcase(str(terminal_path()))
        )
        contained = _current_job_pids(job_name)
        if len(selected) != 1 or selected[0] not in contained or os.getpid() not in contained:
            raise Ds03Error()
    except Exception:
        raise Ds03Error() from None


def verify_runtime_binding(binding: Ds03RuntimeBinding) -> None:
    """Recheck admitted static bytes before fixed credential/metadata effects."""
    if (
        measure_binding(
            accepted_release_sha=binding.release_sha,
            accepted_release_tree=binding.release_tree,
            terminal_build=binding.terminal_build,
            terminal_version=binding.terminal_version,
        )
        != binding
    ):
        raise Ds03Error()
