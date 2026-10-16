"""Generate contracts from their single Pydantic definitions; check drift in tests."""

import json
from pathlib import Path

from auvexo_alpha.domain.contracts import (
    ExecutionReport,
    FeatureSnapshot,
    InstrumentSpec,
    MarketState,
    RiskAuthorization,
    TradeCandidate,
    TradeIntent,
)

MODELS = (
    InstrumentSpec,
    MarketState,
    FeatureSnapshot,
    TradeCandidate,
    TradeIntent,
    RiskAuthorization,
    ExecutionReport,
)


def snapshot() -> str:
    return (
        json.dumps(
            {model.__name__: model.model_json_schema() for model in MODELS},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    target = Path("contracts/schema-v1.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(snapshot(), encoding="utf-8")
