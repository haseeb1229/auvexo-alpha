"""Synthetic MT5 provider fixtures. Never imports or invokes the official SDK."""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from test_ds03_authority import authority_fixture

from auvexo_alpha.domain.ds03_actual import actual_request_adapter
from auvexo_alpha.domain.ds03_authority import admit_authority
from auvexo_alpha.infrastructure import ds03_mt5_binding as binding
from auvexo_alpha.infrastructure.ds03_mt5 import _Mt5ReadPort, terminal_version_reference

SYNTHETIC_PASSWORD = "DemoOnly1!"


def nt(values):
    return namedtuple("SyntheticProviderTuple", tuple(values))(**values)


class Array:
    def __init__(self, rows, fields):
        self.dtype = SimpleNamespace(names=tuple(fields))
        self.rows = [tuple(row[field] for field in fields) for row in rows]

    def __len__(self):
        return len(self.rows)

    def tolist(self):
        return list(self.rows)


class FakeSdk:
    def __init__(self, metadata, build):
        self.calls = []
        self.shutdown_count = 0
        self.initialize_result = True
        self.version_value = (500, build, "synthetic-date")
        self.account = {
            "login": metadata.login,
            "trade_mode": 0,
            "leverage": metadata.leverage,
            "currency": metadata.currency,
            "server": metadata.assigned_server,
            "trade_allowed": False,
            "name": "SYNTHETIC_PERSON_NEVER_LOG",
            "trade_expert": False,
        }
        fixed = str(binding.terminal_path().parent)
        self.terminal = {
            "build": build,
            "connected": True,
            "trade_allowed": False,
            "tradeapi_disabled": True,
            "path": fixed,
            "data_path": fixed,
        }
        self.symbols = ["BTCUSD.demo", "ETHUSD.demo"]
        now = datetime.now(UTC)
        self.msc = int(now.timestamp()) * 1000 - 1000
        self.tick = {
            "time": self.msc // 1000,
            "time_msc": self.msc,
            "bid": 100.0,
            "ask": 100.1,
            "last": 0.0,
            "volume": 0,
            "flags": 6,
            "volume_real": 0.0,
        }
        self.specs = {name: self.spec_row(name) for name in self.symbols}
        self.tick_rows = [dict(self.tick)]
        self.rate_rows = []
        self.orders = ()
        self.positions = ()
        self.deals = ()
        self.order_history = ()
        self.on_tick = None
        self.returned_at = None

    def spec_row(self, name):
        return {
            "name": name,
            "description": "Synthetic broker symbol",
            "category": "",
            "path": "Synthetic\\Crypto",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_tick_value": 0.01,
            "trade_tick_value_profit": 0.01,
            "trade_tick_value_loss": 0.01,
            "trade_contract_size": 1.0,
            "volume_min": 0.01,
            "volume_max": 10.0,
            "volume_step": 0.01,
            "volume_limit": 10.0,
            "trade_stops_level": 0,
            "trade_freeze_level": 0,
            "trade_mode": 4,
            "order_mode": 127,
            "filling_mode": 3,
            "trade_calc_mode": 0,
            "trade_exemode": 2,
            "currency_base": "BTC",
            "currency_profit": "USD",
            "currency_margin": "USD",
            "swap_mode": 0,
            "swap_long": 0.0,
            "swap_short": 0.0,
            "time": self.msc // 1000,
            "spread": 10,
        }

    def initialize(self, path, *, login, password, server, timeout, portable):
        self.calls.append(("initialize", path, login, password, server, timeout, portable))
        return self.initialize_result

    def shutdown(self):
        self.calls.append(("shutdown",))
        self.shutdown_count += 1

    def version(self):
        return self.version_value

    def account_info(self):
        return nt(self.account)

    def terminal_info(self):
        return nt(self.terminal)

    def symbols_get(self):
        self.calls.append(("symbols_get",))
        return tuple(nt({"name": name}) for name in self.symbols)

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        return nt(self.specs[symbol]) if symbol in self.specs else None

    def symbol_info_tick(self, symbol):
        self.calls.append(("symbol_info_tick", symbol))
        if self.on_tick is not None:
            self.on_tick(self)
        result = nt(self.tick)
        self.returned_at = datetime.now(UTC)
        return result

    def copy_rates_range(self, symbol, timeframe, start, end):
        self.calls.append(("copy_rates_range", symbol, timeframe, start, end))
        return Array(
            self.rate_rows,
            ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"),
        )

    def copy_ticks_from(self, symbol, start, count, flags):
        self.calls.append(("copy_ticks_from", symbol, start, count, flags))
        return Array(
            self.tick_rows,
            ("time", "time_msc", "bid", "ask", "last", "volume", "flags", "volume_real"),
        )

    def orders_get(self):
        return self.orders

    def positions_get(self):
        return self.positions

    def history_orders_get(self, start, end):
        return self.order_history

    def history_deals_get(self, start, end):
        return self.deals

    def order_send(self, *args):
        raise AssertionError("forbidden synthetic sentinel")

    def order_check(self, *args):
        raise AssertionError("forbidden synthetic sentinel")

    def symbol_select(self, *args):
        raise AssertionError("forbidden synthetic sentinel")

    def market_book_add(self, *args):
        raise AssertionError("forbidden synthetic sentinel")


class Observer:
    def __init__(self, bound):
        self.bound = bound
        self.evidence = binding.TerminalProcessEvidence(
            "ds03.process." + "a" * 64,
            bound.profile_identity_hash,
            bound.fixed_terminal_path_hash,
            bound.terminal_binary_hash,
        )
        self.bad = False
        self.preflight_calls = 0

    def preflight(self, bound):
        self.preflight_calls += 1
        assert bound == self.bound

    def initial(self, bound):
        assert bound == self.bound
        return self.evidence

    def verify(self, evidence, bound):
        assert bound == self.bound
        if self.bad or evidence != self.evidence:
            from auvexo_alpha.domain.ds03 import Ds03Error

            raise Ds03Error()
        return self.evidence


@dataclass
class Fixture:
    static: object
    admission: object
    sdk: FakeSdk
    observer: Observer
    port: _Mt5ReadPort


def fixture(*, initialize=True):
    authority, metadata, bound, _ = authority_fixture()
    now = datetime.now(UTC)
    version = terminal_version_reference((500, bound.terminal_build, "synthetic-date"))
    bound = type(bound).model_validate_json(
        bound.model_copy(update={"terminal_version": version}).canonical_bytes()
    )
    authority = type(authority).model_validate_json(
        authority.model_copy(
            update={
                "runtime": bound,
                "private_attested_at": now - timedelta(minutes=1),
                "authorized_at": now - timedelta(seconds=30),
                "expires_at": now + timedelta(hours=1),
                "rights_valid_until": now + timedelta(hours=2),
            }
        ).canonical_bytes()
    )
    static = admit_authority(
        authority, independently_accepted_digest=authority.content_hash(), binding=bound, now=now
    )
    admission = static.bind_metadata(metadata, now=now)
    sdk, observer = FakeSdk(metadata, bound.terminal_build), Observer(bound)
    port = _Mt5ReadPort(sdk, admission, observer)
    if initialize:
        port._initialize(SYNTHETIC_PASSWORD)
    return Fixture(static, admission, sdk, observer, port)


def request(f, operation, **fields):
    now = datetime.now(UTC)
    return actual_request_adapter.validate_python(
        {
            "operation": operation,
            "request_id": uuid4(),
            "created_at": now,
            "expires_at": now + timedelta(seconds=10),
            "release_hash": f.admission.binding.connector_source_hash,
            "config_hash": f.admission.metadata.content_hash(),
            **fields,
        }
    )


def prepared(f):
    f.port.execute(request(f, "SYMBOLS"))
    f.port.execute(request(f, "SPEC", symbol=f.sdk.symbols[0]))
    return f
