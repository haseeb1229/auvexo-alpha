"""Export versioned presentation schema locally; no public HTTP docs endpoint."""

import json
from pathlib import Path

from auvexo_alpha.application.terminal_models import TerminalSnapshot


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "web/operator-terminal/contract.schema.json"
    path.write_text(
        json.dumps(TerminalSnapshot.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
