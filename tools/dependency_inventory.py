"""Record the locked third-party set with licence metadata and a minimal CycloneDX SBOM.

The lock file is the source of truth for names and versions on every platform, so the
inventory cannot drift from what is installed anywhere. Licence text comes from installed
package metadata where the installed version equals the locked one; otherwise the
previously reviewed value for that exact version is kept, and anything else is marked
REVIEW_REQUIRED for a human to resolve. No network access and no dependency management.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "auvexo-alpha"


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked(lock: Path) -> list[tuple[str, str]]:
    """Every registry package in the lock: (normalized name, version)."""
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    found = sorted(
        (normalized(package["name"]), str(package["version"]))
        for package in packages
        if normalized(package["name"]) != PROJECT
    )
    if len({name for name, _ in found}) != len(found):
        raise ValueError("LOCK_HAS_MULTIPLE_VERSIONS_OF_ONE_PACKAGE")
    return found


def installed_license(name: str, version: str) -> str | None:
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    if dist.version != version:
        return None
    value = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    if not value:
        value = "; ".join(
            c.removeprefix("License :: OSI Approved :: ")
            for c in dist.metadata.get_all("Classifier", [])
            if c.startswith("License :: OSI Approved ::")
        )
    return value.splitlines()[0] if value else None


def build(lock: Path, previous: list[dict[str, str]]) -> list[dict[str, str]]:
    reviewed = {(normalized(row["name"]), row["version"]): row for row in previous}
    rows: list[dict[str, str]] = []
    for name, version in locked(lock):
        prior = reviewed.get((name, version))
        license_value = installed_license(name, version) or (
            prior["license_metadata"] if prior else "REVIEW_REQUIRED"
        )
        rows.append(
            dict(
                name=name,
                version=version,
                license_metadata=license_value,
                source=f"https://pypi.org/project/{name}/{version}/",
            )
        )
    return rows


def sbom(rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": [
            {
                "type": "library",
                "name": row["name"],
                "version": row["version"],
                "purl": f"pkg:pypi/{row['name']}@{row['version']}",
            }
            for row in rows
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/phase2/DEPENDENCIES.json")
    parser.add_argument("--sbom", type=Path, default=ROOT / "docs/phase2/SBOM.json")
    args = parser.parse_args()
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else []
    rows = build(ROOT / "uv.lock", previous)
    args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8", newline="\n")
    args.sbom.write_text(json.dumps(sbom(rows), indent=2) + "\n", encoding="utf-8", newline="\n")
    pending = [row["name"] for row in rows if row["license_metadata"] == "REVIEW_REQUIRED"]
    print(f"Recorded {len(rows)} locked third-party distributions; review required: {pending}")


if __name__ == "__main__":
    main()
