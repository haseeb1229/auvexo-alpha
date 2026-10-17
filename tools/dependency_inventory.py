"""Record installed package license metadata without duplicating dependency management."""

import argparse
import importlib.metadata
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("docs/phase2/DEPENDENCIES.json"))
args = parser.parse_args()
rows = []
for dist in importlib.metadata.distributions():
    name = str(dist.metadata["Name"])
    if name == "auvexo-alpha":
        continue
    license_value = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    if not license_value:
        license_value = "; ".join(
            c.removeprefix("License :: OSI Approved :: ")
            for c in dist.metadata.get_all("Classifier", [])
            if c.startswith("License :: OSI Approved ::")
        )
    rows.append(
        dict(
            name=name,
            version=dist.version,
            license_metadata=(license_value or "REVIEW_REQUIRED").splitlines()[0],
            source=f"https://pypi.org/project/{name}/{dist.version}/",
        )
    )
rows.sort(key=lambda row: row["name"].lower())
args.output.write_text(json.dumps(rows, indent=2) + "\n")
print(f"Recorded {len(rows)} installed third-party distributions; inspect license metadata")
