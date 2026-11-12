"""The recorded inventory and SBOM must equal the lock file on every platform."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import dependency_inventory as tool  # noqa: E402


def _locked() -> set[tuple[str, str]]:
    # Independent of the tool's own reader: parse the lock directly.
    packages = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    found = {(tool.normalized(p["name"]), str(p["version"])) for p in packages}
    return {item for item in found if item[0] != "auvexo-alpha"}


def test_inventory_matches_the_lock_and_every_licence_is_reviewed() -> None:
    rows = json.loads((ROOT / "docs/phase2/DEPENDENCIES.json").read_text(encoding="utf-8"))
    assert {(row["name"], row["version"]) for row in rows} == _locked()
    assert [row["name"] for row in rows] == sorted(row["name"] for row in rows)
    assert not [row["name"] for row in rows if row["license_metadata"] in ("", "REVIEW_REQUIRED")]
    assert all(
        row["source"] == f"https://pypi.org/project/{row['name']}/{row['version']}/" for row in rows
    )


def test_sbom_matches_the_lock() -> None:
    sbom = json.loads((ROOT / "docs/phase2/SBOM.json").read_text(encoding="utf-8"))
    assert (sbom["bomFormat"], sbom["specVersion"]) == ("CycloneDX", "1.5")
    components = sbom["components"]
    assert {(c["name"], c["version"]) for c in components} == _locked()
    assert all(c["purl"] == f"pkg:pypi/{c['name']}@{c['version']}" for c in components)


def test_windows_only_provider_pins_are_recorded_everywhere() -> None:
    # These are never installed on Linux CI; an installed-environment inventory lost them.
    locked = dict(_locked())
    assert locked["metatrader5"] == "5.0.6231" and locked["numpy"] == "2.4.6"


def test_unreviewed_version_is_flagged_not_guessed(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "auvexo-alpha"\nversion = "0.1.0"\n'
        '[[package]]\nname = "Not_Installed.Anywhere"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    stale = [{"name": "not-installed-anywhere", "version": "1.0.0", "license_metadata": "MIT"}]
    rows = tool.build(lock, stale)
    assert rows == [
        {
            "name": "not-installed-anywhere",
            "version": "9.9.9",
            "license_metadata": "REVIEW_REQUIRED",
            "source": "https://pypi.org/project/not-installed-anywhere/9.9.9/",
        }
    ]
    reviewed = [{"name": "Not-Installed_Anywhere", "version": "9.9.9", "license_metadata": "MIT"}]
    assert tool.build(lock, reviewed)[0]["license_metadata"] == "MIT"
