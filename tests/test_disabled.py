import pytest
from hypothesis import given
from hypothesis import strategies as st

from auvexo_alpha.application.safety import deny_execution
from auvexo_alpha.domain.contracts import Mode, MoneyAction, Product, TradeIntent, Venue
from auvexo_alpha.domain.errors import ErrorCode


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("action", list(MoneyAction))
def test_r003_p1_all_modes_actions_disabled(
    intent_data: dict[str, object], mode: Mode, action: MoneyAction
) -> None:
    intent = TradeIntent.model_validate(intent_data | {"mode": mode, "action": action})
    first = deny_execution(intent)
    second = deny_execution(intent)
    assert first == second
    assert first.status == "DENIED" and first.code == ErrorCode.NOT_AVAILABLE
    assert first.retryable is False


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.LIVE_LIMITED])
def test_r004_p1_binance_derivatives_blocked(intent_data: dict[str, object], mode: Mode) -> None:
    result = deny_execution(
        intent_data | dict(mode=mode, venue=Venue.BINANCE, product=Product.PERPETUAL)
    )
    assert result.code == ErrorCode.BLOCKED_BY_POLICY


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"permit": "enable-live"},
        {"order_send": "arbitrary"},
        {"account_password": "synthetic-forbidden"},
        None,
        "BUY",
        1,
    ],
)
def test_r022_p1_malicious_or_incomplete_never_executes(payload: object) -> None:
    assert deny_execution(payload).code == ErrorCode.INVALID_INPUT


@given(
    st.dictionaries(
        st.text(max_size=50),
        st.one_of(
            st.none(),
            st.booleans(),
            st.floats(allow_nan=True, allow_infinity=True),
            st.text(max_size=100),
        ),
        max_size=20,
    )
)
def test_r022_p1_untrusted_json_fuzz_is_always_denied(payload: object) -> None:
    result = deny_execution(payload)
    assert result.status == "DENIED"
    assert result.retryable is False


def test_withdraw_verb_has_no_handler_anywhere_in_source() -> None:
    # Review G-6: WITHDRAW exists only as a typed verb so that it can be refused. Every
    # mode denies it above; this proves no module branches on it or on a transfer verb.
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src/auvexo_alpha"
    offenders = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "WITHDRAW":
                offenders.append(relative)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.upper() in {"WITHDRAW", "WITHDRAWAL", "TRANSFER"}:
                    if not (relative == "domain/contracts.py" and node.value == "WITHDRAW"):
                        offenders.append(relative)
    assert offenders == []
