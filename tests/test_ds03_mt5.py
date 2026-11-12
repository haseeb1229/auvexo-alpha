"""Synthetic fake-module adapter proofs; no official SDK initialization or account session."""

from __future__ import annotations

import ast
import math
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from mt5_fixtures import SYNTHETIC_PASSWORD, fixture, nt, prepared, request

from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.infrastructure import ds03_mt5 as module


def test_explicit_initialize_fixed_path_all_arguments_and_no_password_retained():
    f = fixture()
    args = f.sdk.calls[0]
    assert args == (
        "initialize",
        str(module.binding_tools.terminal_path()),
        f.admission.metadata.login,
        SYNTHETIC_PASSWORD,
        f.admission.metadata.assigned_server,
        5000,
        True,
    )
    assert not any(
        SYNTHETIC_PASSWORD in repr(value) for key, value in vars(f.port).items() if key != "_sdk"
    )
    observed = f.port.attest()
    assert observed.identity.mode == "DEMO"
    assert observed.identity.account_type_source == "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"
    assert observed.credential_authority_hash == f.static.accepted_digest
    f.port.disconnect()
    assert f.sdk.shutdown_count == 1


@pytest.mark.parametrize(
    "value", [None, "", "short", "MissingDigit!", "lowercase1!", "UPPERCASE1!", "Has Space1!"]
)
def test_missing_or_invalid_password_refuses_before_sdk(value):
    f = fixture(initialize=False)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        f.port._initialize(value)
    assert f.sdk.calls == []


def test_exactly_one_initialize_attempt_even_after_disconnect_or_failure():
    f = fixture()
    with pytest.raises(Ds03Error):
        f.port._initialize(SYNTHETIC_PASSWORD)
    assert len([c for c in f.sdk.calls if c[0] == "initialize"]) == 1
    assert f.sdk.shutdown_count == 1
    f.port.disconnect()
    with pytest.raises(Ds03Error):
        f.port._initialize(SYNTHETIC_PASSWORD)
    assert len([c for c in f.sdk.calls if c[0] == "initialize"]) == 1
    failed = fixture(initialize=False)
    failed.sdk.initialize_result = False
    with pytest.raises(Ds03Error):
        failed.port._initialize(SYNTHETIC_PASSWORD)
    with pytest.raises(Ds03Error):
        failed.port._initialize(SYNTHETIC_PASSWORD)
    assert len([c for c in failed.sdk.calls if c[0] == "initialize"]) == 1
    assert failed.sdk.shutdown_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("trade_mode", 1),
        ("trade_mode", 2),
        ("trade_mode", 99),
        ("trade_mode", False),
        ("login", 111),
        ("server", "synthetic-wrong.invalid"),
        ("currency", "EUR"),
        ("leverage", 200),
        ("trade_allowed", True),
        ("trade_allowed", 0),
    ],
)
def test_account_mode_identity_and_readonly_mismatches_close(field, value):
    f = fixture()
    f.sdk.account[field] = value
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        f.port.attest()
    assert f.sdk.shutdown_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("connected", False),
        ("connected", 1),
        ("trade_allowed", True),
        ("build", 4754),
        ("path", "synthetic-arbitrary-profile"),
        ("data_path", "synthetic-arbitrary-profile"),
    ],
)
def test_terminal_state_or_profile_mismatch_closes(field, value):
    f = fixture()
    f.sdk.terminal[field] = value
    with pytest.raises(Ds03Error):
        f.port.attest()
    assert f.sdk.shutdown_count == 1


@pytest.mark.parametrize(
    "field", ["trade_mode", "login", "server", "currency", "leverage", "trade_allowed"]
)
def test_absent_observed_account_field_fails_closed(field):
    f = fixture()
    del f.sdk.account[field]
    with pytest.raises(Ds03Error):
        f.port.attest()
    assert f.sdk.shutdown_count == 1


def test_native_process_swap_refuses_and_errors_never_leak_personal_fields(capsys):
    f = fixture()
    f.observer.bad = True
    with pytest.raises(Ds03Error) as error:
        f.port.attest()
    assert str(error.value) == "DS03_UNAVAILABLE"
    output = capsys.readouterr()
    assert output.out == output.err == ""
    assert "SYNTHETIC_PERSON_NEVER_LOG" not in str(error.value)
    assert SYNTHETIC_PASSWORD not in str(error.value)


def test_stable_catalog_pagination_and_contract_snapshot_quote_change():
    f = fixture()
    f.sdk.symbols = [f"DEMO{i:03d}" for i in range(129)]
    first = f.port.execute(request(f, "SYMBOLS")).payload
    assert len(first.symbols) == 128 and first.total == 129 and not first.complete
    second = f.port.execute(
        request(f, "SYMBOLS", offset=128, catalog_hash=first.catalog_hash)
    ).payload
    assert (
        len(second.symbols) == 1 and second.complete and second.catalog_hash == first.catalog_hash
    )
    f.port.disconnect()
    f = prepared(fixture())
    symbol = f.sdk.symbols[0]
    before = f.port.execute(request(f, "SPEC", symbol=symbol)).payload.spec
    f.sdk.specs[symbol]["time"] += 1
    f.sdk.specs[symbol]["spread"] += 1
    after = f.port.execute(request(f, "SPEC", symbol=symbol)).payload.spec
    assert after == before
    assert after.quote_at == before.quote_at  # Versioned initial spec, not a new publication.
    f.port.disconnect()


def test_catalog_change_unknown_symbol_and_contract_drift_refuse_without_trade():
    f = prepared(fixture())
    f.sdk.symbols.append("XAUUSD.demo")
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "SYMBOLS"))
    f = prepared(fixture())
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "SPEC", symbol="XAUUSD"))
    f = prepared(fixture())
    f.sdk.specs[f.sdk.symbols[0]]["volume_step"] = 0.02
    before_ticks = len([c for c in f.sdk.calls if c[0] == "symbol_info_tick"])
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "TICK", symbol=f.sdk.symbols[0]))
    assert len([c for c in f.sdk.calls if c[0] == "symbol_info_tick"]) == before_ticks


def test_first_seen_is_after_sdk_returns_even_for_new_tick():
    f = prepared(fixture())

    def fresh(sdk):
        now = datetime.now(UTC)
        msc = int(now.timestamp() * 1000)
        sdk.tick.update(time=msc // 1000, time_msc=msc)

    f.sdk.on_tick = fresh
    reply = f.port.execute(request(f, "TICK", symbol=f.sdk.symbols[0]))
    tick = reply.payload.tick
    assert tick.provider_at <= f.sdk.returned_at <= tick.first_seen_at <= reply.envelope.received_at
    assert reply.envelope.provider_time_kind == "SDK_EVENT_TIME"
    f.port.disconnect()


@pytest.mark.parametrize("flags", [1, 128, 255])
def test_unknown_tick_flags_refuse(flags):
    f = prepared(fixture())
    f.sdk.tick["flags"] = flags
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "TICK", symbol=f.sdk.symbols[0]))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "100.0"])
def test_nonfinite_or_wrong_type_financial_input_refuses(value):
    f = prepared(fixture())
    f.sdk.tick["bid"] = value
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "TICK", symbol=f.sdk.symbols[0]))


def test_bounded_ticks_project_only_out_of_query_rows_and_preserve_overlap():
    f = prepared(fixture())
    symbol = f.sdk.symbols[0]
    base = datetime.fromtimestamp(f.sdk.msc / 1000, UTC)
    later = dict(f.sdk.tick)
    later.update(time=(f.sdk.msc + 1000) // 1000, time_msc=f.sdk.msc + 1000)
    f.sdk.tick_rows = [dict(f.sdk.tick), later]
    message = request(
        f,
        "TICKS",
        symbol=symbol,
        start=base - timedelta(seconds=1),
        end=base + timedelta(milliseconds=500),
        limit=1,
    )
    first = f.port.execute(message).payload
    assert len(first.ticks) == 1 and first.coverage == "UNKNOWN"
    assert [c for c in f.sdk.calls if c[0] == "copy_ticks_from"][-1][3] == 2
    again = f.port.execute(
        request(f, "TICKS", symbol=symbol, start=message.start, end=message.end, limit=1)
    ).payload
    assert again.ticks[0].first_seen_at == first.ticks[0].first_seen_at
    f.port.disconnect()


def test_in_range_tick_overflow_and_ambiguous_milliseconds_refuse_whole_batch():
    for duplicate in (False, True):
        f = prepared(fixture())
        base = datetime.fromtimestamp(f.sdk.msc / 1000, UTC)
        second = dict(f.sdk.tick)
        if not duplicate:
            second.update(time=(f.sdk.msc + 1) // 1000, time_msc=f.sdk.msc + 1)
        f.sdk.tick_rows = [dict(f.sdk.tick), second]
        with pytest.raises(Ds03Error):
            f.port.execute(
                request(
                    f,
                    "TICKS",
                    symbol=f.sdk.symbols[0],
                    start=base - timedelta(seconds=1),
                    end=base + timedelta(milliseconds=500),
                    limit=1,
                )
            )


def test_bars_are_closed_bounded_and_missing_intervals_explicit():
    f = prepared(fixture())
    end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)
    start = end - timedelta(minutes=2)
    f.sdk.rate_rows = [
        {
            "time": int(start.timestamp()),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "tick_volume": 10,
            "spread": 2,
            "real_volume": 0,
        }
    ]
    payload = f.port.execute(
        request(
            f, "BARS", symbol=f.sdk.symbols[0], start=start, end=end, limit=2, timeframe_seconds=60
        )
    ).payload
    assert len(payload.bars) == 1 and payload.bars[0].timeframe_seconds == 60
    assert payload.gaps[0].start == start + timedelta(minutes=1) and payload.gaps[0].end == end
    assert payload.coverage == "UNKNOWN"
    assert [c for c in f.sdk.calls if c[0] == "copy_rates_range"][-1][-1] == end - timedelta(
        seconds=1
    )
    f.port.disconnect()
    f = prepared(fixture())
    with pytest.raises(Ds03Error):
        f.port.execute(
            request(
                f,
                "BARS",
                symbol=f.sdk.symbols[0],
                start=start,
                end=end,
                limit=1,
                timeframe_seconds=60,
            )
        )
    assert not any(c[0] == "copy_rates_range" for c in f.sdk.calls)


def test_raw_float_source_identity_is_retained_separately_from_decimal():
    value = 0.1
    assert module._dec(value) == Decimal("0.1")
    assert module._projection({"price": value}, ("price",)) != module._projection(
        {"price": math.nextafter(value, math.inf)}, ("price",)
    )


def test_non_market_deals_preserve_enum_zero_volume_and_signed_amounts():
    f = prepared(fixture())
    at = f.sdk.msc
    f.sdk.deals = (
        nt(
            {
                "ticket": 7,
                "symbol": "",
                "type": 2,
                "entry": 0,
                "volume": 0.0,
                "price": 0.0,
                "profit": 100.0,
                "commission": -1.0,
                "swap": -0.5,
                "fee": 0.0,
                "time": at // 1000,
                "time_msc": at,
            }
        ),
    )
    start = datetime.fromtimestamp(at / 1000, UTC) - timedelta(seconds=1)
    payload = f.port.execute(
        request(f, "DEALS", start=start, end=datetime.now(UTC), limit=2)
    ).payload
    fact = payload.deals[0]
    assert fact.kind == "NON_MARKET" and fact.symbol is None and fact.spec_hash is None
    assert fact.provider_type == 2 and fact.quantity == fact.price == 0
    assert fact.commission == Decimal("-1.0") and fact.swap == Decimal("-0.5")
    assert fact.deal_ref.startswith("ds03.deal.")
    f.port.disconnect()


def test_contradictory_order_time_pair_is_refused():
    f = prepared(fixture())
    at = f.sdk.msc
    f.sdk.orders = (
        nt(
            {
                "ticket": 8,
                "symbol": f.sdk.symbols[0],
                "type": 0,
                "state": 1,
                "volume_initial": 1.0,
                "volume_current": 1.0,
                "price_open": 100.0,
                "time_setup": at // 1000,
                "time_setup_msc": at,
                "time_done": at // 1000 + 1,
                "time_done_msc": 0,
            }
        ),
    )
    with pytest.raises(Ds03Error):
        f.port.execute(request(f, "ORDERS"))


def test_linux_native_loader_refuses_before_package_import(monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "linux")

    def denied():
        raise AssertionError("Package verification/import must not run on Linux")

    monkeypatch.setattr(module.binding_tools, "verify_installed_package", denied)
    with pytest.raises(Ds03Error):
        module._load_native_sdk()
    assert "MetaTrader5" not in sys.modules


# ADR-029 "Provider allowlist": the complete permitted official SDK surface.
_ADR029_SDK_ALLOWLIST = frozenset(
    {
        "initialize",
        "shutdown",
        "version",
        "terminal_info",
        "account_info",
        "symbols_get",
        "symbol_info",
        "symbol_info_tick",
        "copy_rates_range",
        "copy_ticks_from",
        "orders_get",
        "positions_get",
        "history_orders_get",
        "history_deals_get",
    }
)
_FORBIDDEN_PROVIDER_CALLS = frozenset(
    {
        "order_send",
        "order_check",
        "order_calc_margin",
        "order_calc_profit",
        "symbol_select",
        "market_book_add",
        "market_book_get",
        "market_book_release",
        "login",
    }
)
_FORBIDDEN_DYNAMIC_CALLS = frozenset(
    {
        "getattr",
        "setattr",
        "delattr",
        "eval",
        "exec",
        "compile",
        "__import__",
        "import_module",
        "system",
        "popen",
    }
)


def _actual_adapter_trees():
    package = Path(module.__file__).resolve().parent
    names = ("ds03_mt5", "ds03_mt5_process", "ds03_mt5_binding", "ds03_metadata", "ds03_secrets")
    return {
        name: ast.parse((package / (name + ".py")).read_text(encoding="utf8")) for name in names
    }


def test_static_provider_surface_is_exactly_the_adr029_allowlist():
    # M5-08 static proof over the ACTUAL adapter source (the accepted capability
    # test covers synthetic files only). The SDK handle may be reached solely as
    # a fixed attribute call; it is never aliased, returned, passed or looked up.
    tree = _actual_adapter_trees()["ds03_mt5"]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    handles = [
        node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "_sdk"
    ]
    used: set[str] = set()
    stores = 0
    for handle in handles:
        assert isinstance(handle.value, ast.Name) and handle.value.id == "self"
        owner = parents[handle]
        if isinstance(handle.ctx, ast.Store):
            stores += 1
            continue
        assert isinstance(owner, ast.Attribute) and owner.value is handle, "SDK handle escaped"
        call = parents[owner]
        assert isinstance(call, ast.Call) and call.func is owner, "SDK member not called directly"
        used.add(owner.attr)
    assert stores == 1, "exactly one fixed assignment in the private port constructor"
    assert used == _ADR029_SDK_ALLOWLIST
    module_reads = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "mt5"
    }
    assert module_reads == {"__version__", "__file__"}
    protocol = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Mt5ReadApi"
    )
    declared = {node.name for node in protocol.body if isinstance(node, ast.FunctionDef)}
    assert declared == _ADR029_SDK_ALLOWLIST


def test_typed_provider_stub_exposes_only_the_allowlist_so_new_calls_fail_strict_typing():
    # Located from this test file: the package itself may be a normal installed wheel.
    stub = Path(__file__).resolve().parents[1] / "typings/MetaTrader5/__init__.pyi"
    tree = ast.parse(stub.read_text(encoding="utf8"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert functions == _ADR029_SDK_ALLOWLIST
    assert not _FORBIDDEN_PROVIDER_CALLS & functions


def test_actual_adapter_sources_have_no_trade_mutation_or_dynamic_dispatch_calls():
    for name, tree in _actual_adapter_trees().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert called not in _FORBIDDEN_PROVIDER_CALLS, (name, called)
            assert called not in _FORBIDDEN_DYNAMIC_CALLS, (name, called)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"socket", "requests", "httpx", "urllib", "http", "ssl", "asyncio"}
        assert ("MetaTrader5" in imported) == (name == "ds03_mt5")
