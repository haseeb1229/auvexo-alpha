"""R12-8 provider-runtime install/verify tool: temporary roots and a fake pip only.

Nothing here imports MetaTrader5, runs pip, contacts a network or touches the real
fixed runtime root.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_WHEEL = b"synthetic wheel bytes; never opened or installed"
PAYLOAD = {
    "MetaTrader5/__init__.py": b"# synthetic package, never imported\n",
    "MetaTrader5/_core.cp313-win_amd64.pyd": b"synthetic not-executable binary",
    "metatrader5-5.0.6231.dist-info/LICENSE.txt": b"synthetic license fixture",
}


def load_tool():
    spec = importlib.util.spec_from_file_location("mt5_runtime_tool", ROOT / "tools/mt5_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_distribution(site, name, version, files):
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="ascii"
    )
    record = [f"{path},sha256={sha(data)},{len(data)}" for path, data in files.items()]
    record.append(f"{info.name}/RECORD,,")
    for path, data in files.items():
        target = site / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (info / "RECORD").write_text("\n".join(record) + "\n", encoding="ascii")


class Runtime:
    def __init__(self, tool, tmp_path, monkeypatch):
        self.tool, self.root = tool, tmp_path / "synthetic-runtime-root"
        self.base = self.root / ".local/python/python.exe"
        self.python = self.root / ".venv/Scripts/python.exe"
        self.site = self.root / ".venv/Lib/site-packages"
        for path, data in (
            (self.base, b"synthetic base interpreter"),
            (self.base.parent / "python313.dll", b"synthetic runtime library"),
            (self.python, b"synthetic venv redirector"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / ".venv/pyvenv.cfg").write_text(
            f"home = {self.base.parent}\ninclude-system-site-packages = false\n"
            "version_info = 3.13\n",
            encoding="utf-8",
        )
        self.site.mkdir(parents=True)
        self.wheelhouse = tmp_path / "synthetic-wheelhouse"
        self.wheelhouse.mkdir()
        (self.wheelhouse / tool.WHEEL_NAME).write_bytes(SYNTHETIC_WHEEL)
        self.requirements = tmp_path / "synthetic-requirements.txt"
        self.requirements.write_text(
            "# synthetic hash-locked export\n"
            "metatrader5==5.0.6231 ; sys_platform == 'win32' \\\n"
            f"    --hash=sha256:{sha(SYNTHETIC_WHEEL)}\n"
            "    # via auvexo-alpha\n"
            f"numpy==2.4.6 --hash=sha256:{'a' * 64}\n",
            encoding="ascii",
        )
        self.expected = sha(b"synthetic base interpreter")
        self.facts = [[3, 13, 9], 8, "win32", "cpython", str(self.base), 1, 1]
        self.commands = []
        binding = tool.binding
        monkeypatch.setattr(binding, "WHEEL_HASH", sha(SYNTHETIC_WHEEL))
        monkeypatch.setattr(
            binding, "_PACKAGE_FILES", {path: sha(data) for path, data in PAYLOAD.items()}
        )
        monkeypatch.setattr(binding, "runtime_root", lambda: tmp_path / "fixed-runtime-root")

    def probe(self, python, cwd):
        assert python == self.python and cwd == self.root
        return self.facts

    def pip(self, command, environment, cwd):
        """Fake pip: records its exact invocation and writes a copied payload."""
        self.commands.append((command, environment, cwd))
        write_distribution(self.site, "metatrader5", "5.0.6231", PAYLOAD)
        write_distribution(self.site, "numpy", "2.4.6", {"numpy/__init__.py": b"# synthetic\n"})
        return 0

    def install(self, **changes):
        arguments = (
            dict(
                requirements=self.requirements,
                wheelhouse=self.wheelhouse,
                expected_base_sha256=self.expected,
                future_onboarding=False,
                runner=self.pip,
                probe=self.probe,
            )
            | changes
        )
        return self.tool.install_runtime(self.root, **arguments)

    def verify(self, **changes):
        arguments = (
            dict(expected_base_sha256=self.expected, future_onboarding=False, probe=self.probe)
            | changes
        )
        return self.tool.verify_runtime(self.root, **arguments)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    return Runtime(load_tool(), tmp_path, monkeypatch)


def refused(call, code):
    with pytest.raises(ValueError) as captured:
        call()
    assert captured.value.code == code
    assert str(captured.value) == "MT5_RUNTIME_" + code


def test_install_is_offline_copy_mode_without_compilation_and_exactly_hash_locked(runtime):
    before = sys.modules.get("MetaTrader5")
    report = runtime.install()
    assert sys.modules.get("MetaTrader5") is before
    ((command, environment, cwd),) = runtime.commands
    assert command[:5] == [str(runtime.python), "-I", "-B", "-m", "pip"]
    for flag in (
        "--isolated",
        "--no-compile",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--no-cache-dir",
    ):
        assert flag in command
    assert command[command.index("--find-links") + 1] == str(runtime.wheelhouse)
    assert command[command.index("--requirement") + 1] == str(runtime.requirements)
    joined = " ".join(command)
    for forbidden in ("--index-url", "--extra-index-url", "--compile", "--link-mode", "uv "):
        assert forbidden not in joined
    assert set(environment) <= {"SYSTEMROOT", "WINDIR", "SystemRoot", "windir"}
    assert cwd == runtime.root
    assert report["status"] == "VERIFIED" and report["python"] == "3.13.9"
    assert report["wheel_hash"] == sha(SYNTHETIC_WHEEL)
    assert report["package_manifest_hash"] == runtime.tool.binding._hash(
        runtime.tool.binding._canonical(runtime.tool.binding._PACKAGE_FILES)
    )
    assert runtime.verify() == report | {"files": report["files"]}


def test_real_fixed_runtime_root_requires_explicit_future_onboarding_flag(runtime, tmp_path):
    fixed = tmp_path / "fixed-runtime-root"
    fixed.mkdir()
    refused(lambda: runtime.tool.require_root(fixed, future_onboarding=False), "ROOT_REFUSED")
    refused(lambda: runtime.tool.require_root(fixed, future_onboarding=1), "ROOT_REFUSED")
    assert runtime.tool.require_root(fixed, future_onboarding=True) == fixed
    for bad in (Path("relative-root"), tmp_path / "missing", runtime.requirements):
        refused(
            lambda value=bad: runtime.tool.require_root(value, future_onboarding=True),
            "ROOT_REFUSED",
        )
    output = io.StringIO()
    with redirect_stdout(output):
        code = runtime.tool.main(["verify", "--root", str(fixed), "--python-sha256", "a" * 64])
    assert code == 2
    assert json.loads(output.getvalue()) == {"status": "REFUSED", "reason": "ROOT_REFUSED"}
    assert str(fixed) not in output.getvalue()


def directory_alias(link, target):
    """A junction on Windows (no privilege needed), a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    return link


def remove_alias(link):
    """Remove only the link itself, never its target."""
    if sys.platform == "win32":
        os.rmdir(link)
    else:
        link.unlink()


def short_name(path):
    """The 8.3 spelling of ``path`` when the volume has one, else None."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    count = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return Path(buffer.value) if count and buffer.value != str(path) else None


def test_an_alias_of_the_fixed_root_or_a_path_overlapping_it_is_refused(runtime, tmp_path):
    fixed = tmp_path / "fixed-runtime-root"
    (fixed / "inside").mkdir(parents=True)
    alias = directory_alias(tmp_path.parent / f"{tmp_path.name}-alias", tmp_path)
    try:
        aliased = alias / "fixed-runtime-root"
        assert aliased.is_dir() and aliased.resolve() == fixed.resolve()
        refused(lambda: runtime.tool.require_root(aliased, future_onboarding=False), "ROOT_REFUSED")
        assert runtime.tool.require_root(aliased, future_onboarding=True) == aliased
        # Containing or lying inside the fixed root refuses even with the onboarding flag.
        for overlapping in (fixed / "inside", alias / "fixed-runtime-root" / "inside", tmp_path):
            for flag in (False, True):
                refused(
                    lambda value=overlapping, f=flag: runtime.tool.require_root(
                        value, future_onboarding=f
                    ),
                    "ROOT_REFUSED",
                )
        short = short_name(fixed)
        if short is not None:
            refused(
                lambda: runtime.tool.require_root(short, future_onboarding=False), "ROOT_REFUSED"
            )
        # A sibling directory, even reached through the alias, is not the fixed root.
        assert runtime.tool.require_root(runtime.root, future_onboarding=False) == runtime.root
        sibling = alias / runtime.root.name
        assert runtime.tool.require_root(sibling, future_onboarding=False) == sibling
    finally:
        remove_alias(alias)


def test_a_fixed_root_that_does_not_exist_yet_is_compared_through_its_resolved_ancestor(
    runtime, tmp_path, monkeypatch
):
    outer = tmp_path / "outer"
    outer.mkdir()
    fixed = outer / "fixed-runtime-root"
    monkeypatch.setattr(runtime.tool.binding, "runtime_root", lambda: fixed)
    alias = directory_alias(tmp_path.parent / f"{tmp_path.name}-pending", tmp_path)
    try:
        assert not fixed.exists()
        for root in (outer, alias / "outer"):
            refused(
                lambda value=root: runtime.tool.require_root(value, future_onboarding=True),
                "ROOT_REFUSED",
            )
    finally:
        remove_alias(alias)


@pytest.mark.parametrize(
    "text",
    [
        "metatrader5>=5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "-e .\nmetatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "--index-url https://example.invalid/simple\n"
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5 @ https://example.invalid/x.whl --hash=sha256:{wheel}\n"
        "numpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 --hash=sha256:{a}\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel} --hash=sha256:{a}\n"
        "numpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.5 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 --hash=sha256:{a}\n"
        "NumPy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 \\\n# interrupt\n --hash=sha256:{wheel}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 \\\n",
        "metatrader5==5.0.6231 --hash=md5:{a}\nnumpy==2.4.6 --hash=sha256:{a}\n",
        "metatrader5==5.0.6231 --hash=sha256:{wheel}\nnumpy==2.4.6 --hash=sha256:{a}\né\n",
    ],
)
def test_requirements_export_must_be_pinned_hash_locked_and_bind_the_exact_wheel(text, runtime):
    raw = text.format(wheel=sha(SYNTHETIC_WHEEL), a="a" * 64).encode("utf-8")
    refused(lambda: runtime.tool.parse_requirements(raw), "REQUIREMENTS_INVALID")


def test_requirements_parser_accepts_uv_style_export_and_bounds_size(runtime):
    parsed = runtime.tool.parse_requirements(runtime.requirements.read_bytes())
    assert parsed["metatrader5"] == ("5.0.6231", frozenset({sha(SYNTHETIC_WHEEL)}))
    assert parsed["numpy"][0] == "2.4.6"
    refused(lambda: runtime.tool.parse_requirements(b""), "REQUIREMENTS_INVALID")
    refused(lambda: runtime.tool.parse_requirements(b"#" * 1_048_577), "REQUIREMENTS_INVALID")
    refused(lambda: runtime.tool.parse_requirements("text"), "REQUIREMENTS_INVALID")


@pytest.mark.parametrize("case", ["bytes", "missing", "duplicate", "name", "hardlink"])
def test_wheel_bytes_must_be_the_exact_accepted_hash(case, runtime):
    wheel = runtime.wheelhouse / runtime.tool.WHEEL_NAME
    if case == "bytes":
        wheel.write_bytes(SYNTHETIC_WHEEL + b"x")
    elif case == "missing":
        wheel.unlink()
    elif case == "duplicate":
        (runtime.wheelhouse / "metatrader5-5.0.6231-cp313-cp313-win_amd64.whl.whl").write_bytes(
            SYNTHETIC_WHEEL
        )
    elif case == "name":
        wheel.rename(runtime.wheelhouse / "MetaTrader5-5.0.6231-cp312-cp312-win_amd64.whl")
    else:
        os.link(wheel, runtime.wheelhouse.parent / "alias.whl")
    refused(lambda: runtime.tool.verify_wheel(runtime.wheelhouse), "WHEEL_MISMATCH")
    refused(runtime.install, "WHEEL_MISMATCH")
    assert runtime.commands == []


@pytest.mark.parametrize(
    "case",
    [
        "base_hash",
        "home",
        "system_site",
        "version",
        "pointer",
        "platform",
        "base",
        "site_flag",
        "dll",
    ],
)
def test_exact_interpreter_is_required_before_pip_runs(case, runtime):
    config = runtime.root / ".venv/pyvenv.cfg"
    if case == "base_hash":
        runtime.base.write_bytes(b"changed synthetic interpreter")
    elif case == "home":
        config.write_text(
            f"home = {runtime.root}\ninclude-system-site-packages = false\n", encoding="utf-8"
        )
    elif case == "system_site":
        config.write_text(
            f"home = {runtime.base.parent}\ninclude-system-site-packages = true\n",
            encoding="utf-8",
        )
    elif case == "version":
        runtime.facts[0] = [3, 12, 9]
    elif case == "pointer":
        runtime.facts[1] = 4
    elif case == "platform":
        runtime.facts[2] = "linux"
    elif case == "base":
        runtime.facts[4] = str(runtime.root / "other/python.exe")
    elif case == "site_flag":
        runtime.facts[5] = 0
    else:
        (runtime.base.parent / "python313.dll").unlink()
    refused(runtime.install, "INTERPRETER_MISMATCH")
    assert runtime.commands == []


@pytest.mark.parametrize("case", ["pycache", "pyc", "hardlink", "symlink"])
def test_compiled_linked_or_hard_linked_payload_is_refused_after_install(case, runtime):
    def pip(command, environment, cwd):
        runtime.pip(command, environment, cwd)
        if case == "pycache":
            (runtime.site / "numpy/__pycache__").mkdir()
        elif case == "pyc":
            (runtime.site / "numpy/stale.pyc").write_bytes(b"synthetic bytecode")
        elif case == "hardlink":
            # uv's default link mode: the payload shares bytes with a cache file.
            os.link(runtime.site / "numpy/__init__.py", runtime.root / "cache-copy.py")
        elif os.name == "nt":
            # A directory junction needs no privilege and is a reparse point.
            import _winapi

            _winapi.CreateJunction(str(runtime.root / ".local"), str(runtime.site / "linked"))
        else:
            (runtime.site / "linked").symlink_to(runtime.root, target_is_directory=True)
        return 0

    code = {
        "pycache": "BYTECODE_PRESENT",
        "pyc": "BYTECODE_PRESENT",
        "hardlink": "HARDLINK_PRESENT",
        "symlink": "LINK_PRESENT",
    }[case]
    refused(lambda: runtime.install(runner=pip), code)
    refused(runtime.verify, code)


@pytest.mark.parametrize("case", ["hash", "extra", "numpy", "missing"])
def test_installed_sdk_payload_reuses_the_exact_binding_verification(case, runtime):
    runtime.install()
    if case == "hash":
        (runtime.site / "MetaTrader5/_core.cp313-win_amd64.pyd").write_bytes(b"changed")
    elif case == "extra":
        (runtime.site / "MetaTrader5/unreviewed.dll").write_bytes(b"synthetic extra")
    elif case == "numpy":
        shutil.rmtree(runtime.site / "numpy-2.4.6.dist-info")
        write_distribution(runtime.site, "numpy", "2.4.5", {"numpy/x.py": b"#\n"})
    else:
        shutil.rmtree(runtime.site / "metatrader5-5.0.6231.dist-info")
    refused(runtime.verify, "PACKAGE_MISMATCH")


def test_existing_payload_is_never_upgraded_and_failed_pip_never_verifies(runtime):
    runtime.install()
    refused(runtime.install, "ALREADY_INSTALLED")
    assert len(runtime.commands) == 1
    fresh_site = runtime.site
    shutil.rmtree(fresh_site)
    fresh_site.mkdir()
    refused(lambda: runtime.install(runner=lambda *arguments: 1), "INSTALL_FAILED")


def test_tool_never_imports_the_sdk_or_selects_uv_or_a_package_index():
    tree = ast.parse((ROOT / "tools/mt5_runtime.py").read_text(encoding="utf8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"MetaTrader5", "socket", "urllib", "http", "requests", "ssl"}
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "uv" not in strings and "--index-url" not in strings
    assert not any("import MetaTrader5" in value for value in strings)
    tool = load_tool()
    # The interpreter probe runs without site: no installed distribution is importable.
    assert "MetaTrader5" not in tool._PROBE


@pytest.mark.skipif(os.name != "nt", reason="the pinned SDK payload exists only on Windows")
def test_real_pinned_sdk_payload_verifies_by_copy_without_import(tmp_path, monkeypatch):
    source = ROOT / ".venv/Lib/site-packages"
    if not (source / "MetaTrader5").is_dir():
        pytest.skip("this environment does not carry the pinned SDK payload")
    tool = load_tool()
    runtime = Runtime(tool, tmp_path, monkeypatch)
    monkeypatch.undo()
    monkeypatch.setattr(tool.binding, "runtime_root", lambda: tmp_path / "fixed-runtime-root")
    for name in ("MetaTrader5", "metatrader5-5.0.6231.dist-info", "numpy-2.4.6.dist-info"):
        shutil.copytree(source / name, runtime.site / name)
    before = sys.modules.get("MetaTrader5")
    report = runtime.verify()
    assert sys.modules.get("MetaTrader5") is before
    assert report["package_manifest_hash"] == tool.binding._hash(
        tool.binding._canonical(tool.binding._PACKAGE_FILES)
    )
