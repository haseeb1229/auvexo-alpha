"""M5-02/04/06/09: fixed bytes/process/job proofs; no SDK initialize or terminal launch."""

import ast
import ctypes
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Thread
from types import SimpleNamespace

import psutil
import pytest
from test_ds03_authority import authority_fixture

from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.infrastructure import ds03_mt5_binding as module


def failure(call):
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        call()


def test_runtime_paths_derive_only_home_and_accept_no_override(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("AUVEXO_MT5_PATH", str(tmp_path / "arbitrary.exe"))
    expected = tmp_path / "Desktop/Auvexo Alpha MT5 Readonly Runtime"
    assert module.runtime_root() == expected
    assert module.terminal_path() == expected / "terminal/terminal64.exe"
    assert module.fixed_path_hashes() == tuple(
        module._path_hash(p) for p in (expected, module.terminal_path(), expected / "terminal")
    )
    with pytest.raises(TypeError):
        module.terminal_path(tmp_path / "arbitrary.exe")


@pytest.mark.parametrize("case", ["symlink", "junction", "reparse", "hardlink", "not_file"])
def test_plain_path_refuses_link_redirect_and_nonfile_without_following(case, monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "win32")
    follows = []

    class UnsafePath:
        parents = ()

        def stat(self, *, follow_symlinks):
            follows.append(follow_symlinks)
            return SimpleNamespace(
                st_file_attributes=0x400 if case == "reparse" else 0,
                st_nlink=2 if case == "hardlink" else 1,
            )

        def is_symlink(self):
            return case == "symlink"

        def is_junction(self):
            return case == "junction"

        def is_file(self):
            return case != "not_file"

    failure(lambda: module._plain_path(UnsafePath(), file=True))
    assert follows and not any(follows)


def test_profile_identity_ignores_contents_but_refuses_replaced_directory(monkeypatch, tmp_path):
    profile = tmp_path / "synthetic-profile"
    profile.mkdir()
    executable = profile / "terminal64.exe"
    executable.write_bytes(b"synthetic terminal image")
    monkeypatch.setattr(module, "terminal_path", lambda: executable)
    monkeypatch.setattr(module, "_plain_path", lambda path, *, file: None)
    before = module._profile_identity()
    (profile / "synthetic-settings.bin").write_bytes(b"ordinary profile write")
    os.utime(profile, None)
    assert module._profile_identity() == before
    profile.rename(tmp_path / "synthetic-old-profile")
    profile.mkdir()
    executable.write_bytes(b"synthetic terminal image")
    assert module._profile_identity() != before


def package_fixture(monkeypatch, tmp_path):
    payload = {
        "MetaTrader5/__init__.py": b"# synthetic package, never imported\n",
        "MetaTrader5/_core.cp313-win_amd64.pyd": b"synthetic not-executable binary",
        "metatrader5-5.0.6231.dist-info/LICENSE.txt": b"synthetic license fixture",
    }
    for name, data in payload.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    distribution = SimpleNamespace(
        version="5.0.6231", files=list(payload), locate_file=lambda name: tmp_path / name
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "_PACKAGE_FILES", expected)
    monkeypatch.setattr(module, "_plain_path", lambda path, *, file: None)
    monkeypatch.setattr(module.importlib.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(module.importlib.metadata, "version", lambda name: "2.4.6")
    return distribution, expected


def test_package_checks_record_and_actual_payload_without_import(monkeypatch, tmp_path):
    distribution, expected = package_fixture(monkeypatch, tmp_path)
    before = sys.modules.get("MetaTrader5")
    assert module.verify_installed_package() == module._hash(module._canonical(expected))
    assert sys.modules.get("MetaTrader5") is before
    (tmp_path / "MetaTrader5/__pycache__").mkdir()
    # Empty cache directory has no executable payload; cached bytecode is tested below.
    assert module.verify_installed_package() == module._hash(module._canonical(expected))


@pytest.mark.parametrize(
    "case",
    [
        "extra_file",
        "unrecorded_pyc",
        "record_extra",
        "record_missing",
        "bad_hash",
        "bad_version",
        "bad_numpy",
        "empty_record",
    ],
)
def test_package_drift_unlisted_cache_record_hash_and_versions_refuse(case, monkeypatch, tmp_path):
    distribution, expected = package_fixture(monkeypatch, tmp_path)
    if case == "extra_file":
        (tmp_path / "MetaTrader5/unreviewed.dll").write_bytes(b"synthetic extra")
    elif case == "unrecorded_pyc":
        cache = tmp_path / "MetaTrader5/__pycache__/__init__.cpython-313.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"synthetic unreviewed cache")
    elif case == "record_extra":
        distribution.files.append("MetaTrader5/other.py")
    elif case == "record_missing":
        distribution.files.remove("metatrader5-5.0.6231.dist-info/LICENSE.txt")
    elif case == "bad_hash":
        (tmp_path / "MetaTrader5/_core.cp313-win_amd64.pyd").write_bytes(b"changed synthetic")
    elif case == "bad_version":
        distribution.version = "0.0.0"
    elif case == "bad_numpy":
        monkeypatch.setattr(module.importlib.metadata, "version", lambda name: "0.0.0")
    else:
        distribution.files = []
    failure(module.verify_installed_package)


def test_linux_package_and_native_apis_refuse_before_distribution_or_process(monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "linux")

    def unexpected(*args, **kwargs):
        raise AssertionError("Windows API/package discovery must not run on Linux")

    monkeypatch.setattr(module.importlib.metadata, "distribution", unexpected)
    failure(module.verify_installed_package)
    failure(module._terminal_pids)
    failure(module.provider_job)


class NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *arguments):
        return self.function(*arguments)


@pytest.mark.parametrize("clean_end", [True, False])
def test_toolhelp_filters_basename_before_any_privileged_candidate_queries(clean_end, monkeypatch):
    entries = [(1, "System"), (2, "terminal64.exe"), (3, "TERMINAL64.EXE"), (4, "other.exe")]
    state = {"index": 0, "closed": False, "error": 0}

    def fill(pointer):
        pid, name = entries[state["index"]]
        pointer._obj.th32ProcessID = pid
        pointer._obj.szExeFile = name
        return True

    def first(handle, pointer):
        return fill(pointer)

    def next_entry(handle, pointer):
        state["index"] += 1
        if state["index"] == len(entries):
            state["error"] = 18 if clean_end else 5
            return False
        return fill(pointer)

    def close(handle):
        state["closed"] = True
        return True

    api = SimpleNamespace(
        CreateToolhelp32Snapshot=NativeCall(lambda flags, pid: 123),
        Process32FirstW=NativeCall(first),
        Process32NextW=NativeCall(next_entry),
        CloseHandle=NativeCall(close),
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda *a, **kw: api, raising=False)
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: state["error"], raising=False)
    if clean_end:
        assert module._terminal_pids() == (2, 3)
    else:
        failure(module._terminal_pids)
    assert state["closed"]


def process_fixture(monkeypatch, tmp_path):
    executable = tmp_path / "synthetic-profile/terminal64.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic terminal bytes")
    monkeypatch.setattr(module, "terminal_path", lambda: executable)
    monkeypatch.setattr(module, "_plain_path", lambda path, *, file: None)
    paths = (
        module._path_hash(tmp_path),
        module._path_hash(executable),
        module._path_hash(executable.parent),
    )
    monkeypatch.setattr(module, "fixed_path_hashes", lambda: paths)
    binding = authority_fixture()[2].model_copy(
        update={
            "terminal_binary_hash": module._hash(executable.read_bytes()),
            "fixed_runtime_path_hash": paths[0],
            "fixed_terminal_path_hash": paths[1],
            "fixed_profile_path_hash": paths[2],
            "profile_identity_hash": module._profile_identity(),
        }
    )
    states = {
        101: dict(exe=str(executable), owner="synthetic-owner", created=10.0),
        202: dict(
            exe=str(tmp_path / "other/terminal64.exe"), owner="synthetic-other", created=20.0
        ),
    }
    queries = []

    class Process:
        def __init__(self, pid=None):
            self.pid = pid
            if pid is not None:
                assert pid in states
                queries.append(pid)

        def exe(self):
            state = states[self.pid]
            if "error" in state:
                raise state["error"]
            return state["exe"]

        def username(self):
            if self.pid is None:
                return "synthetic-owner"
            assert self.pid != 202, "unrelated image must not receive owner queries"
            return states[self.pid]["owner"]

        def create_time(self):
            return states[self.pid]["created"]

    monkeypatch.setattr(module.psutil, "Process", Process)
    monkeypatch.setattr(module, "measure_binding", lambda **kwargs: binding)
    monkeypatch.setattr(module, "_terminal_pids", lambda: (101, 202))
    return binding, states, queries, executable


def test_target_process_identity_and_drift_are_independently_bound(monkeypatch, tmp_path):
    binding, states, queries, executable = process_fixture(monkeypatch, tmp_path)
    first = module.probe_terminal_process(binding)
    assert first.process_ref.startswith("ds03.process.")
    assert first.profile_hash == binding.profile_identity_hash
    assert queries == [101, 202]
    assert module.verify_terminal_process(first, binding) == first
    states[101]["created"] = 11.0
    failure(lambda: module.verify_terminal_process(first, binding))
    states[101]["created"] = 10.0
    executable.write_bytes(b"changed binary")
    failure(lambda: module.probe_terminal_process(binding))


@pytest.mark.parametrize("case", ["owner", "denied", "disappeared", "none", "duplicate", "profile"])
def test_unknown_candidate_wrong_owner_missing_duplicate_or_profile_drift_refuses(
    case, monkeypatch, tmp_path
):
    binding, states, queries, executable = process_fixture(monkeypatch, tmp_path)
    if case == "owner":
        states[101]["owner"] = "synthetic-unexpected"
    elif case == "denied":
        states[101]["error"] = psutil.AccessDenied(101)
    elif case == "disappeared":
        states[101]["error"] = psutil.NoSuchProcess(101)
    elif case == "none":
        monkeypatch.setattr(module, "_terminal_pids", lambda: ())
    elif case == "duplicate":
        states[303] = dict(states[101])
        monkeypatch.setattr(module, "_terminal_pids", lambda: (101, 303))
    else:
        binding = binding.model_copy(update={"profile_identity_hash": "0" * 64})
    failure(lambda: module.probe_terminal_process(binding))


@pytest.mark.skipif(os.name != "nt", reason="native read-only Toolhelp proof requires Windows")
def test_native_toolhelp_readonly_candidate_inventory_never_launches_terminal():
    pids = module._terminal_pids()
    assert type(pids) is tuple and len(set(pids)) == len(pids)
    assert all(type(pid) is int and pid > 0 for pid in pids)


@pytest.mark.skipif(os.name != "nt", reason="native exact Windows SDK install proof")
def test_native_exact_package_verification_does_not_import_or_initialize():
    before = sys.modules.get("MetaTrader5")
    assert module.verify_installed_package() == module._hash(
        module._canonical(module._PACKAGE_FILES)
    )
    assert sys.modules.get("MetaTrader5") is before


@pytest.mark.skipif(os.name != "nt", reason="native Windows Job Object containment proof")
def test_native_job_memory_limit_and_kill_on_close_for_synthetic_child_and_descendant():
    # CREATE_SUSPENDED contains the venv redirector BEFORE it can create base Python.
    job = module.provider_job()
    program = (
        "import os,subprocess,sys,time;assert sys.stdin.buffer.read(1)==b'x';"
        "from auvexo_alpha.infrastructure.ds03_mt5_binding import _current_job_pids;"
        "p=subprocess.Popen([sys.executable,'-I','-B','-c',"
        "'import os,time;print(os.getpid(),flush=True);time.sleep(30)'],"
        "stdout=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW);"
        f"actual=int(p.stdout.readline());members=_current_job_pids({job.name!r});"
        "print(p.pid,int(os.getpid() in members),int(p.pid in members),"
        "int(actual in members),flush=True);time.sleep(30);"
        "print('SYNTHETIC_NATURAL_COMPLETION',flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW | 0x4,
    )
    owned = []
    try:
        job.assign(process)
        api = job._api
        api.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        api.QueryInformationJobObject.restype = ctypes.c_int
        api.IsProcessInJob.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        ]
        api.IsProcessInJob.restype = ctypes.c_int
        limits = module._ExtendedLimit()
        assert api.QueryInformationJobObject(
            job._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
        )
        assert limits.JobMemoryLimit == 1024**3
        assert limits.BasicLimitInformation.LimitFlags & 0x2200 == 0x2200
        assert not limits.BasicLimitInformation.LimitFlags & (0x800 | 0x1000)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(b"x")
        process.stdin.flush()
        result = Queue(maxsize=1)
        Thread(target=lambda: result.put(process.stdout.readline()), daemon=True).start()
        line = result.get(timeout=5)
        if not line:
            process.wait(timeout=5)
            assert process.stderr is not None
            raise AssertionError(
                "synthetic child probe failed: " + process.stderr.read().decode(errors="replace")
            )
        parts = line.split()
        assert len(parts) == 4 and all(part.isdigit() for part in parts)
        assert parts[1:] == [b"1", b"1", b"1"]
        descendant_pid = int(parts[0])
        root = psutil.Process(process.pid)
        owned = [(child, child.create_time()) for child in root.children(recursive=True)]
        assert descendant_pid in {child.pid for child, created in owned}
        assert owned, "synthetic base interpreter and descendants must be present"
        # Query every actual base interpreter/launcher/descendant, not merely Popen's PID.
        for child, _created in [(root, root.create_time()), *owned]:
            handle = api.OpenProcess(0x1000, False, child.pid)
            assert handle
            try:
                member = ctypes.c_int()
                assert api.IsProcessInJob(handle, job._handle, ctypes.byref(member))
                assert member.value, "owned synthetic descendant escaped the job"
            finally:
                assert api.CloseHandle(handle)
        job.close()
        process.wait(timeout=5)
        for child, created in owned:
            child.wait(timeout=5)
            assert not child.is_running() or child.create_time() != created
        assert b"SYNTHETIC_NATURAL_COMPLETION" not in process.stdout.read()
    finally:
        if job is not None:
            job.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        # Failure cleanup is limited to exact captured synthetic descendants and creation times.
        for child, created in reversed(owned):
            try:
                if child.is_running() and child.create_time() == created:
                    child.kill()
                    child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()


def test_fixed_actual_launcher_suspends_before_job_assignment_and_bootstrap():
    # Inspect the fixed sibling source without importing a provider or starting a child.
    source = Path(module.__file__).with_name("ds03_mt5_process.py").read_text(encoding="utf8")
    tree = ast.parse(source)
    launches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    ]
    assert len(launches) == 1
    flags = next(
        keyword.value for keyword in launches[0].keywords if keyword.arg == "creationflags"
    )
    assert isinstance(flags, ast.Name) and flags.id == "flags"
    assignments = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "flags" for target in node.targets)
    ]
    assert any(
        isinstance(node, ast.Constant) and type(node.value) is int and node.value == 4
        for value in assignments
        for node in ast.walk(value)
    )
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "CREATE_NO_WINDOW"
        for value in assignments
        for node in ast.walk(value)
    )
    assert source.index("self._job.assign(process)") < source.index("outgoing = bootstrap_frame(")


def test_effective_interpreter_binds_base_dll_venv_config_and_exact_version(monkeypatch, tmp_path):
    executable = tmp_path / "venv/Scripts/python.exe"
    base = tmp_path / "base/python.exe"
    dll = tmp_path / "base/python313.dll"
    config = tmp_path / "venv/pyvenv.cfg"
    files = {
        executable: b"synthetic launcher",
        base: b"synthetic base",
        dll: b"synthetic Python DLL",
        config: b"synthetic configuration",
    }
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr(module.sys, "executable", str(executable))
    monkeypatch.setattr(module.sys, "prefix", str(config.parent))
    monkeypatch.setattr(module, "_base_python", lambda: base)
    monkeypatch.setattr(module, "_loaded_python_dll", lambda: dll)
    monkeypatch.setattr(module, "_plain_path", lambda path, *, file: None)
    before = module._interpreter_manifest()
    assert before["python"] == module._hash(files[executable])
    assert before["base_python"] == module._hash(files[base])
    assert before["python_dll"] == module._hash(files[dll])
    assert before["venv_config"] == module._hash(files[config])
    assert before["python_version"] == module._hash(sys.version.encode("ascii"))
    for path, key in [(base, "base_python"), (dll, "python_dll"), (config, "venv_config")]:
        path.write_bytes(files[path] + b" changed")
        after = module._interpreter_manifest()
        assert after[key] != before[key]
        assert {k for k in before if after[k] != before[k]} == {key}
        path.write_bytes(files[path])


def test_static_runtime_drift_refuses_before_candidate_process_queries(monkeypatch, tmp_path):
    binding, states, queries, executable = process_fixture(monkeypatch, tmp_path)
    changed = binding.model_copy(update={"connector_source_hash": "0" * 64})
    monkeypatch.setattr(module, "measure_binding", lambda **kwargs: changed)
    failure(lambda: module.probe_terminal_process(binding))
    assert queries == []


@pytest.mark.parametrize("case", ["same_job", "foreign_terminal", "caller_outside", "drift"])
def test_terminal_must_belong_to_the_immediate_provider_job(case, monkeypatch, tmp_path):
    binding, states, queries, executable = process_fixture(monkeypatch, tmp_path)
    evidence = module.probe_terminal_process(binding)
    members = {os.getpid(), 101}
    if case == "foreign_terminal":
        members.remove(101)
        members.add(999)
    elif case == "caller_outside":
        members.remove(os.getpid())
    elif case == "drift":
        states[101]["created"] = 11.0
    monkeypatch.setattr(module, "_current_job_pids", lambda name: frozenset(members))
    if case == "same_job":
        assert (
            module.require_terminal_in_current_job(binding, evidence, job_name=synthetic_job_name())
            is None
        )
    else:
        failure(
            lambda: module.require_terminal_in_current_job(
                binding, evidence, job_name=synthetic_job_name()
            )
        )


@pytest.mark.parametrize("case", ["valid", "memory", "flags", "truncated", "api_failure"])
def test_immediate_job_query_requires_exact_limits_and_complete_membership(case, monkeypatch):
    def query(handle, kind, pointer, length, returned):
        assert handle == 444
        if case == "api_failure":
            return False
        value = pointer._obj
        if kind == 9:
            value.JobMemoryLimit = 1024**3 + (1 if case == "memory" else 0)
            value.BasicLimitInformation.LimitFlags = 0x2200 | (0x800 if case == "flags" else 0)
        else:
            assert kind == 3
            value.assigned = 3 if case == "truncated" else 2
            value.count = 2
            value.pids[0], value.pids[1] = os.getpid(), 202
        return True

    opened, closed = [], []

    def open_query(access, inherit, name):
        opened.append((access, inherit, name))
        return 444

    api = SimpleNamespace(
        QueryInformationJobObject=NativeCall(query),
        OpenJobObjectW=NativeCall(open_query),
        CloseHandle=NativeCall(lambda handle: closed.append(handle) or True),
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda *a, **k: api, raising=False)
    if case == "valid":
        assert module._current_job_pids(synthetic_job_name()) == frozenset({os.getpid(), 202})
    else:
        failure(lambda: module._current_job_pids(synthetic_job_name()))


def synthetic_job_name():
    return "Local" + chr(92) + "AuvexoAlphaDS03Readonly-" + "a" * 32


@pytest.mark.parametrize("name", [None, "", "Local", "Global/arbitrary", "a" * 200])
def test_job_query_rejects_arbitrary_object_names_before_native_access(name, monkeypatch):
    calls = []
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda *a, **k: calls.append(True), raising=False)
    failure(lambda: module._current_job_pids(name))
    assert not calls
