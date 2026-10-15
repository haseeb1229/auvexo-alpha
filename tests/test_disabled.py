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
