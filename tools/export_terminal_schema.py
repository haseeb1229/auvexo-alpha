"""Export versioned presentation schema locally; no public HTTP docs endpoint."""

import json
from pathlib import Path

from auvexo_alpha.application.terminal_models import TerminalSnapshot


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "web/operator-terminal/contract.schema.json"
    # Explicit LF: the committed schema stays LF on every platform, including Windows.
    path.write_text(
        json.dumps(TerminalSnapshot.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
