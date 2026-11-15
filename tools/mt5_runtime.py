"""Future owner onboarding tool: install/verify the fixed MT5 provider runtime by copy.

The DS-03 binding refuses byte-compiled caches and hard links: pip compiles by default
and uv links by default. This tool installs only from an explicitly supplied local
wheelhouse and hash-locked requirements export, with pip in isolated, no-index,
no-compile, no-cache, binary-only, hash-required mode, then verifies the result
read-only. It never imports MetaTrader5, never starts a terminal, never initializes an
SDK session, and never touches credentials, accounts, metadata or authority. Its only
network-capable step is pip, and pip is given no index.

The real fixed runtime root, by any alias, is refused unless ``--future-onboarding`` is
given, and a root containing or inside it is always refused; that flag exists for the
separately authorized PRIVATE onboarding and nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Never

from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.infrastructure import ds03_mt5_binding as binding

type RefusalCode = Literal[
    "ARGUMENTS_INVALID",
    "ROOT_REFUSED",
    "REQUIREMENTS_INVALID",
    "WHEEL_MISMATCH",
    "INTERPRETER_MISMATCH",
    "ALREADY_INSTALLED",
    "INSTALL_FAILED",
    "PACKAGE_MISMATCH",
    "BYTECODE_PRESENT",
    "HARDLINK_PRESENT",
    "LINK_PRESENT",
]
type Runner = Callable[[list[str], dict[str, str], Path], int]

WHEEL_NAME = "MetaTrader5-5.0.6231-cp313-cp313-win_amd64.whl"
_MAX_REQUIREMENTS_BYTES = 1_048_576
_MAX_FILES = 200_000
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]{0,63})"
    r"(?:\s*;\s*(?P<marker>[A-Za-z0-9_ .'\"=<>!()-]{1,200}?))?"
    r"(?P<hashes>(?:\s+--hash=sha256:[0-9a-f]{64})+)$"
)
_PROBE = (
    "import json,struct,sys;"
    "print(json.dumps([list(sys.version_info[:3]),struct.calcsize('P'),sys.platform,"
    "sys.implementation.name,sys._base_executable,sys.flags.no_site,"
    "sys.flags.dont_write_bytecode]))"
)


class RuntimeRefusal(ValueError):
    """Closed refusal code only; no path, package text or tool output."""

    def __init__(self, code: RefusalCode) -> None:
        self.code = code
        super().__init__("MT5_RUNTIME_" + code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _linked(path: Path) -> bool:
    info = path.lstat()
    return (
        stat.S_ISLNK(info.st_mode)
        or path.is_junction()
        or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    )


def _plain_file(path: Path, code: RefusalCode) -> None:
    if not path.exists() or _linked(path) or not path.is_file() or path.lstat().st_nlink != 1:
        raise RuntimeRefusal(code)


def _canonical(path: Path) -> Path:
    """Final path: 8.3 short names, junctions, symlinks and substituted drives resolved.

    A path that does not exist yet resolves through its nearest existing ancestor.
    """
    return Path(os.path.normcase(os.path.realpath(path)))


def require_root(root: Path, *, future_onboarding: bool) -> Path:
    """An explicit existing directory that neither is, contains nor lies inside the real
    fixed runtime, which only the onboarding flag admits, and then only exactly.

    Comparison is on final resolved paths, so no alias spelling of the fixed root passes.
    """
    if not isinstance(root, Path) or not root.is_absolute():
        raise RuntimeRefusal("ROOT_REFUSED")
    if not root.exists() or _linked(root) or not root.is_dir():
        raise RuntimeRefusal("ROOT_REFUSED")
    fixed, candidate = _canonical(binding.runtime_root()), _canonical(root)
    if (candidate.is_relative_to(fixed) or fixed.is_relative_to(candidate)) and (
        future_onboarding is not True or candidate != fixed
    ):
        raise RuntimeRefusal("ROOT_REFUSED")
    return root


def parse_requirements(raw: bytes) -> dict[str, tuple[str, frozenset[str]]]:
    """Strict pinned, hash-locked export: every requirement ``name==version`` plus hashes.

    Continuation lines are joined and comment lines ignored. Editable, URL, path, option
    or unpinned lines refuse. The SDK must be pinned to exactly the accepted wheel hash.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_REQUIREMENTS_BYTES:
        raise RuntimeRefusal("REQUIREMENTS_INVALID")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise RuntimeRefusal("REQUIREMENTS_INVALID") from None
    logical: list[str] = []
    pending = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.startswith("#"):
            # A comment may not interrupt a continued requirement.
            raise RuntimeRefusal("REQUIREMENTS_INVALID")
        if stripped.endswith("\\"):
            pending += stripped[:-1].strip() + " "
            continue
        logical.append((pending + stripped).strip())
        pending = ""
    if pending:
        raise RuntimeRefusal("REQUIREMENTS_INVALID")
    result: dict[str, tuple[str, frozenset[str]]] = {}
    for entry in logical:
        match = _REQUIREMENT.fullmatch(entry)
        if match is None:
            raise RuntimeRefusal("REQUIREMENTS_INVALID")
        name = re.sub(r"[-_.]+", "-", match["name"]).lower()
        hashes = frozenset(re.findall(r"--hash=sha256:([0-9a-f]{64})", match["hashes"]))
        if name in result or not hashes:
            raise RuntimeRefusal("REQUIREMENTS_INVALID")
        result[name] = (match["version"], hashes)
    if result.get("metatrader5") != (binding.PACKAGE_VERSION, frozenset({binding.WHEEL_HASH})):
        raise RuntimeRefusal("REQUIREMENTS_INVALID")
    if result.get("numpy", ("", frozenset()))[0] != binding.NUMPY_VERSION:
        raise RuntimeRefusal("REQUIREMENTS_INVALID")
    return result


def verify_wheel(wheelhouse: Path) -> str:
    """The exact accepted SDK wheel bytes, by hash; the archive is never opened."""
    if not wheelhouse.is_absolute() or _linked(wheelhouse) or not wheelhouse.is_dir():
        raise RuntimeRefusal("WHEEL_MISMATCH")
    candidates = [
        path
        for path in wheelhouse.iterdir()
        if path.name.casefold().startswith("metatrader5-") and path.name.casefold().endswith(".whl")
    ]
    if len(candidates) != 1 or candidates[0].name != WHEEL_NAME:
        raise RuntimeRefusal("WHEEL_MISMATCH")
    _plain_file(candidates[0], "WHEEL_MISMATCH")
    if _sha256(candidates[0]) != binding.WHEEL_HASH:
        raise RuntimeRefusal("WHEEL_MISMATCH")
    return binding.WHEEL_HASH


def _paths(root: Path) -> tuple[Path, Path, Path]:
    venv = root / ".venv"
    return venv / "Scripts" / "python.exe", root / ".local" / "python" / "python.exe", venv


def _child_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR"}
    }


def _run(command: list[str], environment: dict[str, str], cwd: Path) -> int:
    """Fixed argument vector, no shell, minimal environment, bounded time."""
    completed = subprocess.run(
        command,
        env=environment,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        shell=False,
        check=False,
        timeout=900,
    )
    return completed.returncode


def _probe(python: Path, cwd: Path) -> object:
    completed = subprocess.run(
        # -S: no site, so no installed distribution (MetaTrader5 included) is importable.
        [str(python), "-I", "-S", "-B", "-c", _PROBE],
        env=_child_environment(),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        shell=False,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0 or len(completed.stdout) > 4096:
        raise RuntimeRefusal("INTERPRETER_MISMATCH")
    try:
        return json.loads(completed.stdout)
    except ValueError:
        raise RuntimeRefusal("INTERPRETER_MISMATCH") from None


def verify_interpreter(
    root: Path, *, expected_base_sha256: str, probe: Callable[[Path, Path], object] = _probe
) -> str:
    """Exact copied venv over the owned base CPython 3.13 x64 under ``root``."""
    python, base, venv = _paths(root)
    if re.fullmatch(r"[0-9a-f]{64}", expected_base_sha256 or "") is None:
        raise RuntimeRefusal("ARGUMENTS_INVALID")
    for path in (python, base, base.parent / "python313.dll", venv / "pyvenv.cfg"):
        _plain_file(path, "INTERPRETER_MISMATCH")
    if _sha256(base) != expected_base_sha256:
        raise RuntimeRefusal("INTERPRETER_MISMATCH")
    settings: dict[str, str] = {}
    for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            settings[key.strip().lower()] = value.strip()
    if os.path.normcase(settings.get("home", "")) != os.path.normcase(str(base.parent)) or (
        settings.get("include-system-site-packages", "").lower() != "false"
    ):
        raise RuntimeRefusal("INTERPRETER_MISMATCH")
    facts = probe(python, root)
    if (
        not isinstance(facts, list)
        or len(facts) != 7
        or not isinstance(facts[0], list)
        or facts[0][:2] != [3, 13]
        or facts[1:4] != [8, "win32", "cpython"]
        or not isinstance(facts[4], str)
        or os.path.normcase(os.path.abspath(facts[4])) != os.path.normcase(str(base))
        or facts[5:] != [1, 1]
    ):
        raise RuntimeRefusal("INTERPRETER_MISMATCH")
    return ".".join(str(part) for part in facts[0])


def _single(name: str, site: Path) -> importlib.metadata.Distribution:
    found = list(importlib.metadata.distributions(name=name, path=[str(site)]))
    if len(found) != 1:
        raise RuntimeRefusal("PACKAGE_MISMATCH")
    return found[0]


def verify_tree(site: Path) -> int:
    """No byte-compiled cache, hard link, symlink, junction or reparse point anywhere."""
    count = 0
    for directory, folders, files in os.walk(site, followlinks=False):
        current = Path(directory)
        if _linked(current):
            raise RuntimeRefusal("LINK_PRESENT")
        if "__pycache__" in folders:
            raise RuntimeRefusal("BYTECODE_PRESENT")
        for folder in folders:
            if _linked(current / folder):
                raise RuntimeRefusal("LINK_PRESENT")
        for name in files:
            path = current / name
            count += 1
            if count > _MAX_FILES:
                raise RuntimeRefusal("PACKAGE_MISMATCH")
            if _linked(path):
                raise RuntimeRefusal("LINK_PRESENT")
            if name.casefold().endswith((".pyc", ".pyo")):
                raise RuntimeRefusal("BYTECODE_PRESENT")
            if path.lstat().st_nlink != 1:
                raise RuntimeRefusal("HARDLINK_PRESENT")
    return count


def verify_runtime(
    root: Path,
    *,
    expected_base_sha256: str,
    future_onboarding: bool,
    wheelhouse: Path | None = None,
    probe: Callable[[Path, Path], object] = _probe,
) -> dict[str, object]:
    """Read-only verification; repeats every install postcondition."""
    root = require_root(root, future_onboarding=future_onboarding)
    if wheelhouse is not None:
        verify_wheel(wheelhouse)
    version = verify_interpreter(root, expected_base_sha256=expected_base_sha256, probe=probe)
    site = _paths(root)[2] / "Lib" / "site-packages"
    if _linked(site) or not site.is_dir():
        raise RuntimeRefusal("PACKAGE_MISMATCH")
    files = verify_tree(site)
    try:
        manifest = binding.verify_package_payload(
            _single("metatrader5", site), _single("numpy", site).version
        )
    except Ds03Error:
        raise RuntimeRefusal("PACKAGE_MISMATCH") from None
    return {
        "status": "VERIFIED",
        "python": version,
        "wheel_hash": binding.WHEEL_HASH,
        "package_manifest_hash": manifest,
        "files": files,
    }


def install_command(python: Path, requirements: Path, wheelhouse: Path) -> list[str]:
    return [
        str(python),
        "-I",
        "-B",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "install",
        "--no-compile",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--no-cache-dir",
        "--no-warn-script-location",
        "--requirement",
        str(requirements),
    ]


def install_runtime(
    root: Path,
    *,
    requirements: Path,
    wheelhouse: Path,
    expected_base_sha256: str,
    future_onboarding: bool,
    runner: Runner = _run,
    probe: Callable[[Path, Path], object] = _probe,
) -> dict[str, object]:
    root = require_root(root, future_onboarding=future_onboarding)
    if not requirements.is_absolute():
        raise RuntimeRefusal("REQUIREMENTS_INVALID")
    _plain_file(requirements, "REQUIREMENTS_INVALID")
    parse_requirements(requirements.read_bytes())
    verify_wheel(wheelhouse)
    verify_interpreter(root, expected_base_sha256=expected_base_sha256, probe=probe)
    site = _paths(root)[2] / "Lib" / "site-packages"
    if not site.is_dir() or (site / "MetaTrader5").exists():
        # Fresh install only: never upgrade, repair or overwrite an existing payload.
        raise RuntimeRefusal("ALREADY_INSTALLED")
    python = _paths(root)[0]
    if runner(install_command(python, requirements, wheelhouse), _child_environment(), root) != 0:
        raise RuntimeRefusal("INSTALL_FAILED")
    return verify_runtime(
        root,
        expected_base_sha256=expected_base_sha256,
        future_onboarding=future_onboarding,
        wheelhouse=wheelhouse,
        probe=probe,
    )


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise RuntimeRefusal("ARGUMENTS_INVALID")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description=__doc__, exit_on_error=False)
    parser.add_argument("operation", choices=("install", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--future-onboarding", action="store_true")
    try:
        arguments = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
        if arguments.operation == "install":
            if arguments.wheelhouse is None or arguments.requirements is None:
                raise RuntimeRefusal("ARGUMENTS_INVALID")
            report = install_runtime(
                arguments.root,
                requirements=arguments.requirements,
                wheelhouse=arguments.wheelhouse,
                expected_base_sha256=arguments.python_sha256,
                future_onboarding=arguments.future_onboarding,
            )
        else:
            if arguments.requirements is not None:
                raise RuntimeRefusal("ARGUMENTS_INVALID")
            report = verify_runtime(
                arguments.root,
                expected_base_sha256=arguments.python_sha256,
                future_onboarding=arguments.future_onboarding,
                wheelhouse=arguments.wheelhouse,
            )
    except RuntimeRefusal as refusal:
        print(json.dumps({"status": "REFUSED", "reason": refusal.code}))
        return 2
    except (OSError, subprocess.SubprocessError, argparse.ArgumentError):
        # Class only: tool, path and package text never reach the output.
        print(json.dumps({"status": "REFUSED", "reason": "INSTALL_FAILED"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
