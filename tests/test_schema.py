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


def test_contract_schema_drift() -> None:
    models = (
        InstrumentSpec,
        MarketState,
        FeatureSnapshot,
        TradeCandidate,
        TradeIntent,
        RiskAuthorization,
        ExecutionReport,
    )
    actual = {model.__name__: model.model_json_schema() for model in models}
    assert actual == json.loads(Path("contracts/schema-v1.json").read_text())
    assert actual["TradeIntent"]["properties"]["quantity"]["type"] == "string"
