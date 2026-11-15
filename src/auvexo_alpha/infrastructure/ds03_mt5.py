"""Fixed MT5 read-only provider; importing this module never imports SDK or opens a session."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from numbers import Integral, Real
from pathlib import Path
from time import sleep
from typing import Protocol, cast

from auvexo_alpha.domain.ds03 import Ds03Gap
from auvexo_alpha.domain.ds03_actual import (
    PROTOCOL_FAMILY,
    TIME_BASIS_MAX_SAMPLES,
    TIME_BASIS_MIN_SAMPLES,
    ActualAttestation,
    ActualAttestationPayload,
    ActualAttestRequest,
    ActualBar,
    ActualBarsPayload,
    ActualBarsRequest,
    ActualDealFact,
    ActualDealsPayload,
    ActualDealsRequest,
    ActualDisconnectedPayload,
    ActualDisconnectRequest,
    ActualEnvelope,
    ActualIdentity,
    ActualOrderFact,
    ActualOrderHistoryPayload,
    ActualOrderHistoryRequest,
    ActualOrdersPayload,
    ActualOrdersRequest,
    ActualPayload,
    ActualPositionFact,
    ActualPositionsPayload,
    ActualPositionsRequest,
    ActualReply,
    ActualRequest,
    ActualRights,
    ActualServerTimePayload,
    ActualServerTimeRequest,
    ActualSpecPayload,
    ActualSpecRequest,
    ActualSymbolsPayload,
    ActualSymbolSpec,
    ActualSymbolsRequest,
    ActualTick,
    ActualTickPayload,
    ActualTickRequest,
    ActualTicksPayload,
    ActualTicksRequest,
    Ds03ReasonCode,
    Ds03Refusal,
    ServerTimeBasis,
    ServerTimeEvidence,
    ServerTimeSample,
    catalog_digest,
    classify_server_time,
    decode_actual_request,
    refusal,
    server_time,
)
from auvexo_alpha.domain.ds03_authority import Ds03OnboardingAdmission, Ds03RuntimeBinding
from auvexo_alpha.infrastructure import ds03_mt5_binding as binding_tools
from auvexo_alpha.infrastructure.ds03_ipc import canonical
from auvexo_alpha.infrastructure.ds03_metadata import (
    ReferenceKind,
    keyed_reference,
    load_ds03_reference_key,
    require_metadata_references,
)
from auvexo_alpha.infrastructure.ds03_secrets import _valid_secret

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Mt5ReadApi(Protocol):
    def initialize(
        self, path: str, *, login: int, password: str, server: str, timeout: int, portable: bool
    ) -> bool: ...
    def shutdown(self) -> None: ...
    def version(self) -> object: ...
    def terminal_info(self) -> object: ...
    def account_info(self) -> object: ...
    def symbols_get(self) -> object: ...
    def symbol_info(self, symbol: str) -> object: ...
    def symbol_info_tick(self, symbol: str) -> object: ...
    def copy_rates_range(
        self, symbol: str, timeframe: int, start: datetime, end: datetime
    ) -> object: ...
    def copy_ticks_from(self, symbol: str, start: datetime, count: int, flags: int) -> object: ...
    def orders_get(self) -> object: ...
    def positions_get(self) -> object: ...
    def history_orders_get(self, start: datetime, end: datetime) -> object: ...
    def history_deals_get(self, start: datetime, end: datetime) -> object: ...


class _NamedTuple(Protocol):
    def _asdict(self) -> Mapping[str, object]: ...


class _DType(Protocol):
    names: tuple[str, ...] | None


class _Array(Protocol):
    dtype: _DType

    def __len__(self) -> int: ...
    def tolist(self) -> list[object]: ...


class _Observer(Protocol):
    def preflight(self, binding: Ds03RuntimeBinding) -> None: ...
    def initial(self, binding: Ds03RuntimeBinding) -> binding_tools.TerminalProcessEvidence: ...
    def verify(
        self, evidence: binding_tools.TerminalProcessEvidence, binding: Ds03RuntimeBinding
    ) -> binding_tools.TerminalProcessEvidence: ...


class _NativeObserver:
    def __init__(self, job_name: str) -> None:
        self._job_name = binding_tools._validate_job_name(job_name)

    def preflight(self, binding: Ds03RuntimeBinding) -> None:
        measured = binding_tools.measure_binding(
            accepted_release_sha=binding.release_sha,
            accepted_release_tree=binding.release_tree,
            terminal_build=binding.terminal_build,
            terminal_version=binding.terminal_version,
        )
        if measured != binding:
            raise Ds03Refusal("BINDING_MISMATCH")
        binding_tools._current_job_pids(self._job_name)

    def initial(self, binding: Ds03RuntimeBinding) -> binding_tools.TerminalProcessEvidence:
        evidence = binding_tools.probe_terminal_process(binding)
        binding_tools.require_terminal_in_current_job(binding, evidence, job_name=self._job_name)
        return evidence

    def verify(
        self, evidence: binding_tools.TerminalProcessEvidence, binding: Ds03RuntimeBinding
    ) -> binding_tools.TerminalProcessEvidence:
        actual = binding_tools.verify_terminal_process(evidence, binding)
        binding_tools.require_terminal_in_current_job(binding, actual, job_name=self._job_name)
        return actual


_INVALID: Ds03ReasonCode = "PROVIDER_DATA_INVALID"


def _named(value: object) -> dict[str, object]:
    if not isinstance(value, tuple):
        raise Ds03Refusal(_INVALID)
    projected = cast(_NamedTuple, value)._asdict()
    if not isinstance(projected, Mapping) or any(type(k) is not str for k in projected):
        raise Ds03Refusal(_INVALID)
    return dict(projected)


def _int(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise Ds03Refusal(_INVALID)
    result = int(value)
    if result < minimum or result > 253402300799999:
        raise Ds03Refusal(_INVALID)
    return result


def _text(value: object, *, empty: bool = False) -> str:
    if type(value) is not str or len(value) > 512 or (not value and not empty):
        raise Ds03Refusal(_INVALID)
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise Ds03Refusal(_INVALID)
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise Ds03Refusal(_INVALID)
    return value


def _dec(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise Ds03Refusal(_INVALID)
    if isinstance(value, Integral):
        return Decimal(str(int(value)))
    number = float(value)
    if not math.isfinite(number):
        raise Ds03Refusal(_INVALID)
    return Decimal(str(number))


def _projection(row: dict[str, object], fields: tuple[str, ...]) -> str:
    """Hash exact provider float bits separately from normalized financial Decimals."""
    result: dict[str, object] = {}
    for key in fields:
        value = row[key]
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, Integral):
            result[key] = int(value)
        elif isinstance(value, Real):
            number = float(value)
            if not math.isfinite(number):
                raise Ds03Refusal(_INVALID)
            result[key] = {"float_hex": number.hex()}
        elif type(value) is str:
            result[key] = _text(value, empty=True)
        elif value is None:
            result[key] = None
        else:
            raise Ds03Refusal(_INVALID)
    return hashlib.sha256(canonical(result)).hexdigest()


def _raw_ms(value: object, seconds: object) -> int:
    """Raw trade-server milliseconds, consistent with the provider's own seconds field."""
    milliseconds = _int(value)
    if milliseconds // 1000 != _int(seconds):
        raise Ds03Refusal(_INVALID)
    return milliseconds


def terminal_version_reference(value: object) -> str:
    if not isinstance(value, tuple) or len(value) != 3:
        raise Ds03Refusal("TERMINAL_VERSION")
    version = (_int(value[0], minimum=1), _int(value[1], minimum=4755), _text(value[2]))
    return "mt5.version." + hashlib.sha256(canonical(version)).hexdigest()


def _array_rows(value: object, *, fields: tuple[str, ...], maximum: int) -> list[dict[str, object]]:
    array = cast(_Array, value)
    if value is None or not 0 <= len(array) <= maximum:
        raise Ds03Refusal(_INVALID)
    names = array.dtype.names
    if names is None or not set(fields) <= set(names) or len(set(names)) != len(names):
        raise Ds03Refusal(_INVALID)
    native = array.tolist()
    if type(native) is not list or len(native) != len(array):
        raise Ds03Refusal(_INVALID)
    result: list[dict[str, object]] = []
    for row in native:
        if not isinstance(row, tuple) or len(row) != len(names):
            raise Ds03Refusal(_INVALID)
        result.append(dict(zip(names, row, strict=True)))
    return result


def _tuple_rows(value: object, maximum: int) -> list[dict[str, object]]:
    if not isinstance(value, tuple) or len(value) > maximum:
        raise Ds03Refusal(_INVALID)
    return [_named(row) for row in value]


def _load_native_sdk() -> Mt5ReadApi:
    """Only this reviewed Windows loader imports the fixed provider module."""
    if sys.platform != "win32" or "MetaTrader5" in sys.modules:
        raise Ds03Refusal("PACKAGE_MISMATCH")
    before = binding_tools.verify_installed_package()
    import MetaTrader5 as mt5

    after = binding_tools.verify_installed_package()
    expected = Path(
        str(importlib.metadata.distribution("metatrader5").locate_file("MetaTrader5/__init__.py"))
    )
    if (
        before != after
        or mt5.__version__ != "5.0.6231"
        or os.path.normcase(os.path.abspath(mt5.__file__))
        != os.path.normcase(os.path.abspath(expected))
    ):
        raise Ds03Refusal("PACKAGE_MISMATCH")
    return cast(Mt5ReadApi, mt5)


def _epoch_ms(value: datetime) -> int:
    at = value.astimezone(UTC)
    if at.tzinfo is None or value.utcoffset() is None or at < _EPOCH:
        raise Ds03Refusal("REQUEST_INVALID")
    return (at - _EPOCH) // timedelta(milliseconds=1)


_TIMED_REQUESTS = (
    ActualSpecRequest,
    ActualTickRequest,
    ActualBarsRequest,
    ActualTicksRequest,
    ActualOrdersRequest,
    ActualPositionsRequest,
    ActualDealsRequest,
    ActualOrderHistoryRequest,
)


class _Mt5ReadPort:
    """Private fake seam; production uses the fixed open_native_readonly factory."""

    def __init__(
        self,
        sdk: Mt5ReadApi,
        admission: Ds03OnboardingAdmission,
        observer: _Observer,
        reference_key: bytes,
    ) -> None:
        try:
            admission.verify(datetime.now(UTC))
            # Keyed references are recomputed from the private key, never trusted as stored.
            require_metadata_references(admission.metadata, reference_key)
        except Exception as error:
            raise refusal(error, "AUTHORITY_INVALID") from None
        self._sdk, self._admission, self._observer = sdk, admission, observer
        self._reference_key = reference_key
        basis = admission.authority.server_time_basis
        self._basis: tuple[str, int] | None = None
        if basis is not None and basis.offset_seconds is not None:
            self._basis = (basis.content_hash(), basis.offset_seconds)
        self._connected = False
        self._attempted = False
        self._initialization_used = False
        self._native: binding_tools.TerminalProcessEvidence | None = None
        self._identity: ActualIdentity | None = None
        self._catalog: tuple[str, ...] | None = None
        self._specs: dict[str, ActualSymbolSpec] = {}
        self._seen: dict[tuple[str, ...], tuple[str, datetime]] = {}
        self._batches: dict[str, datetime] = {}

    def _initialize(self, password: object) -> ActualAttestation:
        try:
            if self._initialization_used:
                raise Ds03Refusal("SESSION_CLOSED")
            self._admission.verify(datetime.now(UTC))
            self._observer.preflight(self._admission.binding)
            secret = _valid_secret(password)
            metadata = self._admission.metadata
            self._initialization_used = True
            self._attempted = True
            success = self._sdk.initialize(
                str(binding_tools.terminal_path()),
                login=metadata.login,
                password=secret,
                server=metadata.assigned_server,
                timeout=5000,
                portable=True,
            )
            del secret
            if type(success) is not bool or not success:
                raise Ds03Refusal("INITIALIZE_FAILED")
            self._native = self._observer.initial(self._admission.binding)
            self._connected = True
            observed = self.attest()
            self._identity = observed.identity
            return observed
        except Exception as error:
            self.disconnect()
            raise refusal(error, "INITIALIZE_FAILED") from None

    def disconnect(self) -> None:
        attempted = self._attempted
        self._attempted, self._connected, self._identity, self._native = False, False, None, None
        self._specs.clear()
        self._catalog = None
        self._seen.clear()
        self._batches.clear()
        if attempted:
            try:
                self._sdk.shutdown()
            except Exception:
                raise Ds03Refusal("SHUTDOWN_FAILED") from None

    def attest(self) -> ActualAttestation:
        try:
            if not self._connected or self._native is None:
                raise Ds03Refusal("SESSION_CLOSED")
            self._admission.verify(datetime.now(UTC))
            bound, metadata, authority = (
                self._admission.binding,
                self._admission.metadata,
                self._admission.authority,
            )
            try:
                evidence = self._observer.verify(self._native, bound)
            except Exception as error:
                raise refusal(error, "TERMINAL_IDENTITY") from None
            account, terminal = _named(self._sdk.account_info()), _named(self._sdk.terminal_info())
            version = self._sdk.version()
            if (
                not isinstance(version, tuple)
                or len(version) != 3
                or _int(version[1]) != bound.terminal_build
                or terminal_version_reference(version) != bound.terminal_version
                or _int(terminal["build"]) != bound.terminal_build
            ):
                raise Ds03Refusal("TERMINAL_VERSION")
            if _int(account["trade_mode"]) != 0:
                raise Ds03Refusal("ACCOUNT_NOT_DEMO")
            if (
                _int(account["login"], minimum=1) != metadata.login
                or _text(account["server"]) != metadata.assigned_server
                or _text(account["currency"]) != metadata.currency
                or _int(account["leverage"], minimum=1) != metadata.leverage
            ):
                raise Ds03Refusal("ACCOUNT_IDENTITY")
            if _bool(account["trade_allowed"]) or _bool(terminal["trade_allowed"]):
                raise Ds03Refusal("TRADE_FLAG_TRUE")
            if not _bool(terminal["connected"]):
                raise Ds03Refusal("TERMINAL_DISCONNECTED")
            fixed = os.path.normcase(os.path.abspath(binding_tools.terminal_path().parent))
            if any(
                os.path.normcase(os.path.abspath(_text(terminal[key]))) != fixed
                for key in ("path", "data_path")
            ):
                raise Ds03Refusal("TERMINAL_PROFILE")
            identity = ActualIdentity.model_validate(
                {
                    "account_ref": metadata.account_ref,
                    "login_hash": metadata.account_digest,
                    "server": metadata.server_ref,
                    "account_type": metadata.account_type,
                    "account_type_source": "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5",
                    "currency": metadata.currency,
                    "leverage": metadata.leverage,
                    "mode": "DEMO",
                    "terminal_build": bound.terminal_build,
                    "terminal_version": bound.terminal_version,
                    "process_ref": evidence.process_ref,
                    "profile_hash": evidence.profile_hash,
                    "release_hash": bound.connector_source_hash,
                    "config_hash": metadata.content_hash(),
                    "rights_hash": authority.rights_hash,
                    "authority_hash": self._admission.accepted_digest,
                    "time_basis_hash": authority.time_basis_hash,
                    "server_offset_seconds": authority.server_offset_seconds,
                }
            )
            if self._identity is not None and identity != self._identity:
                raise Ds03Refusal("IDENTITY_DRIFT")
            return ActualAttestation(
                identity=identity,
                observed_at=datetime.now(UTC),
                connected=True,
                credential_readonly=True,
                account_trade_allowed=False,
                terminal_trade_allowed=False,
                credential_authority_hash=self._admission.accepted_digest,
            )
        except Exception as error:
            self.disconnect()
            raise refusal(error, _INVALID) from None

    def _time_basis(self) -> tuple[str, int]:
        """No provider time is labelled UTC unless the accepted authority bound its basis."""
        if self._basis is None:
            raise Ds03Refusal("TIME_BASIS_UNBOUND")
        return self._basis

    def _server_query(self, at: datetime) -> datetime:
        """A UTC query instant expressed in the bound trade-server basis."""
        return at + timedelta(seconds=self._time_basis()[1])

    def _first_seen(self, key: tuple[str, ...], source: str, at: datetime) -> datetime:
        prior = self._seen.get(key)
        if prior is not None:
            if prior[0] != source:
                raise Ds03Refusal("HISTORY_CONFLICT")
            return prior[1]
        self._seen[key] = (source, at)
        return at

    def _reference(self, kind: ReferenceKind, ticket: object) -> str:
        # Keyed, account-scoped ticket reference: never enumerable from a ticket number.
        value = self._admission.metadata.account_digest + ":" + str(_int(ticket, minimum=1))
        return "ds03." + kind + "." + keyed_reference(self._reference_key, kind, value)

    def measure_server_time(
        self,
        symbols: tuple[str, ...],
        *,
        samples: int,
        local_clock_evidence_hash: str,
        clock: Callable[[], datetime],
        pause: Callable[[float], None],
        interval_seconds: float,
    ) -> ServerTimeBasis:
        """Onboarding step: raw provider tick times against local UTC receipt.

        It labels nothing as UTC and needs no bound basis. Only the allowlisted
        symbol_info_tick is read, for symbols of the completed catalog, between two
        fresh attestations. The classification and its evidence hash are what a later
        accepted authority may bind; UNKNOWN can never be bound.
        """
        try:
            return classify_server_time(
                self._server_time_evidence(
                    symbols,
                    samples=samples,
                    local_clock_evidence_hash=local_clock_evidence_hash,
                    clock=clock,
                    pause=pause,
                    interval_seconds=interval_seconds,
                )
            )
        except Exception as error:
            self.disconnect()
            raise refusal(error, _INVALID) from None

    def _server_time_evidence(
        self,
        symbols: tuple[str, ...],
        *,
        samples: int,
        local_clock_evidence_hash: str,
        clock: Callable[[], datetime],
        pause: Callable[[float], None],
        interval_seconds: float,
    ) -> ServerTimeEvidence:
        if (
            not TIME_BASIS_MIN_SAMPLES <= samples <= TIME_BASIS_MAX_SAMPLES
            or not symbols
            or not 0 <= interval_seconds <= 60
        ):
            raise Ds03Refusal("REQUEST_INVALID")
        observed = self.attest()
        if self._catalog is None or any(symbol not in self._catalog for symbol in symbols):
            raise Ds03Refusal("SYMBOL_NOT_ADMITTED")
        collected: list[ServerTimeSample] = []
        for index in range(samples):
            if index:
                pause(interval_seconds)
            symbol = symbols[index % len(symbols)]
            before = _epoch_ms(clock())
            row = _named(self._sdk.symbol_info_tick(symbol))
            after = _epoch_ms(clock())
            collected.append(
                ServerTimeSample(
                    symbol=symbol,
                    provider_time=_int(row["time"]),
                    provider_time_msc=_int(row["time_msc"]),
                    local_before_ms=before,
                    local_after_ms=after,
                )
            )
        if self.attest().identity != observed.identity:
            raise Ds03Refusal("IDENTITY_DRIFT")
        return ServerTimeEvidence(
            local_clock_evidence_hash=local_clock_evidence_hash, samples=tuple(collected)
        )

    def _catalog_page(self, request: ActualSymbolsRequest) -> ActualSymbolsPayload:
        rows = _tuple_rows(self._sdk.symbols_get(), 4096)
        names = tuple(sorted(_text(row["name"]) for row in rows))
        if len(set(names)) != len(names):
            raise Ds03Refusal(_INVALID)
        digest = catalog_digest(names)
        if self._catalog is None:
            self._catalog = names
        if names != self._catalog or (
            request.catalog_hash is not None and request.catalog_hash != digest
        ):
            raise Ds03Refusal("CATALOG_DRIFT")
        page = names[request.offset : request.offset + 128]
        return ActualSymbolsPayload(
            symbols=page,
            catalog_hash=digest,
            total=len(names),
            offset=request.offset,
            complete=request.offset + len(page) == len(names),
        )

    def _spec(self, symbol: str) -> ActualSymbolSpec:
        if self._catalog is None or symbol not in self._catalog:
            raise Ds03Refusal("SYMBOL_NOT_ADMITTED")
        basis_hash, offset = self._time_basis()
        row = _named(self._sdk.symbol_info(symbol))
        if _text(row["name"]) != symbol:
            raise Ds03Refusal(_INVALID)
        fields = (
            "name",
            "description",
            "category",
            "path",
            "digits",
            "point",
            "trade_tick_size",
            "trade_tick_value",
            "trade_tick_value_profit",
            "trade_tick_value_loss",
            "trade_contract_size",
            "volume_min",
            "volume_max",
            "volume_step",
            "volume_limit",
            "trade_stops_level",
            "trade_freeze_level",
            "trade_mode",
            "order_mode",
            "filling_mode",
            "trade_calc_mode",
            "trade_exemode",
            "currency_base",
            "currency_profit",
            "currency_margin",
            "swap_mode",
            "swap_long",
            "swap_short",
        )
        source = _projection(row, fields)
        prior = self._specs.get(symbol)
        if prior is not None:
            if prior.source_ref != source:
                raise Ds03Refusal("SPEC_DRIFT")
            return prior
        quote_seconds = _int(row["time"])
        spec = ActualSymbolSpec.model_validate(
            {
                "symbol": symbol,
                "description": _text(row["description"]),
                "category": _text(row["category"], empty=True) or _text(row["path"]),
                "digits": _int(row["digits"]),
                "point": _dec(row["point"]),
                "tick_size": _dec(row["trade_tick_size"]),
                "contract_size": _dec(row["trade_contract_size"]),
                "volume_min": _dec(row["volume_min"]),
                "volume_max": _dec(row["volume_max"]),
                "volume_step": _dec(row["volume_step"]),
                "volume_limit": _dec(row["volume_limit"]),
                "tick_value": _dec(row["trade_tick_value"]),
                "tick_value_profit": _dec(row["trade_tick_value_profit"]),
                "tick_value_loss": _dec(row["trade_tick_value_loss"]),
                "stops_level": _int(row["trade_stops_level"]),
                "freeze_level": _int(row["trade_freeze_level"]),
                "trade_mode": "MT5_TRADE_MODE." + str(_int(row["trade_mode"])),
                "order_modes": None,
                "fill_modes": None,
                "margin_mode": "MT5_CALC_MODE." + str(_int(row["trade_calc_mode"])),
                "execution_mode": "MT5_EXECUTION_MODE." + str(_int(row["trade_exemode"])),
                "base_currency": _text(row["currency_base"], empty=True) or None,
                "profit_currency": _text(row["currency_profit"], empty=True) or None,
                "margin_currency": _text(row["currency_margin"], empty=True) or None,
                "sessions": None,
                "spread": _dec(row["spread"]),
                "spread_unit": "MT5_POINTS",
                "swap_mode": "MT5_SWAP_MODE." + str(_int(row["swap_mode"])),
                "swap_long": _dec(row["swap_long"]),
                "swap_short": _dec(row["swap_short"]),
                "quote_at": server_time(quote_seconds * 1000, offset) if quote_seconds else None,
                "provider_quote_time_raw": quote_seconds or None,
                "history_start": None,
                "history_end": None,
                "source_ref": source,
                "provider_trade_mode": _int(row["trade_mode"]),
                "provider_order_mode": _int(row["order_mode"]),
                "provider_filling_mode": _int(row["filling_mode"]),
                "provider_trade_calc_mode": _int(row["trade_calc_mode"]),
                "server_offset_seconds": offset,
                "time_basis_hash": basis_hash,
            }
        )
        self._specs[symbol] = spec
        return spec

    def _tick(self, row: dict[str, object], symbol: str, acquired: datetime) -> ActualTick:
        basis_hash, offset = self._time_basis()
        source = _projection(
            row, ("time", "time_msc", "bid", "ask", "last", "volume", "flags", "volume_real")
        )
        msc = _raw_ms(row["time_msc"], row["time"])
        if _int(row["flags"]) & ~126:
            raise Ds03Refusal(_INVALID)
        first = self._first_seen(("tick", symbol, str(msc)), source, acquired)
        return ActualTick.model_validate(
            {
                "symbol": symbol,
                "provider_at": server_time(msc, offset),
                "bid": _dec(row["bid"]),
                "ask": _dec(row["ask"]),
                "last": _dec(row["last"]),
                "volume": _dec(row["volume"]),
                "volume_real": _dec(row["volume_real"]),
                "time_msc": msc,
                "flags": _int(row["flags"]),
                "first_seen_at": first,
                "source_ref": source,
                "server_offset_seconds": offset,
                "time_basis_hash": basis_hash,
            }
        )

    def _bars(self, request: ActualBarsRequest) -> ActualBarsPayload:
        basis_hash, offset = self._time_basis()
        seconds = request.timeframe_seconds
        count = int((request.end - request.start).total_seconds()) // seconds
        # Bar boundaries are trade-server boundaries (a D1 bar opens at server midnight).
        server_epoch = _EPOCH - timedelta(seconds=offset)
        if (
            count < 1
            or count > request.limit
            or any(
                (t - server_epoch).total_seconds() % seconds for t in (request.start, request.end)
            )
        ):
            raise Ds03Refusal("REQUEST_INVALID")
        timeframe = {60: 1, 300: 5, 900: 15, 3600: 16385, 86400: 16408}[seconds]
        fields = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume")
        raw = self._sdk.copy_rates_range(
            request.symbol,
            timeframe,
            self._server_query(request.start),
            self._server_query(request.end - timedelta(seconds=1)),
        )
        acquired = datetime.now(UTC)
        rows = _array_rows(raw, fields=fields, maximum=request.limit)
        bars: list[ActualBar] = []
        for row in rows:
            raw_seconds = _int(row["time"])
            at = server_time(raw_seconds * 1000, offset)
            source = _projection(row, fields)
            first = self._first_seen(
                ("bar", request.symbol, str(seconds), at.isoformat()), source, acquired
            )
            bars.append(
                ActualBar.model_validate(
                    {
                        "symbol": request.symbol,
                        "timeframe_seconds": seconds,
                        "provider_at": at,
                        "provider_time_raw": raw_seconds,
                        "open": _dec(row["open"]),
                        "high": _dec(row["high"]),
                        "low": _dec(row["low"]),
                        "close": _dec(row["close"]),
                        "tick_volume": _int(row["tick_volume"]),
                        "spread": _int(row["spread"]),
                        "real_volume": _dec(row["real_volume"]),
                        "first_seen_at": first,
                        "source_ref": source,
                        "server_offset_seconds": offset,
                        "time_basis_hash": basis_hash,
                    }
                )
            )
        observed = {bar.provider_at for bar in bars}
        if len(observed) != len(bars):
            raise Ds03Refusal(_INVALID)
        gaps: list[Ds03Gap] = []
        cursor = request.start
        interval = timedelta(seconds=seconds)
        while cursor < request.end:
            if cursor in observed:
                cursor += interval
                continue
            start = cursor
            while cursor < request.end and cursor not in observed:
                cursor += interval
            gaps.append(Ds03Gap(start=start, end=cursor, reason="UNKNOWN_PROVIDER_HISTORY"))
        return ActualBarsPayload(bars=tuple(bars), gaps=tuple(gaps), coverage="UNKNOWN")

    def _ticks(self, request: ActualTicksRequest) -> ActualTicksPayload:
        fields = ("time", "time_msc", "bid", "ask", "last", "volume", "flags", "volume_real")
        raw = self._sdk.copy_ticks_from(
            request.symbol, self._server_query(request.start), request.limit + 1, -1
        )
        acquired = datetime.now(UTC)
        rows = _array_rows(raw, fields=fields, maximum=request.limit + 1)
        ticks = tuple(self._tick(row, request.symbol, acquired) for row in rows)
        if any(tick.provider_at > acquired for tick in ticks):
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if any(a.time_msc >= b.time_msc for a, b in zip(ticks[:-1], ticks[1:], strict=True)):
            raise Ds03Refusal(_INVALID)
        selected = tuple(tick for tick in ticks if request.start <= tick.provider_at < request.end)
        if len(selected) > request.limit:
            raise Ds03Refusal(_INVALID)
        # The counted native call has no end argument; project only out-of-query rows.
        return ActualTicksPayload(ticks=selected, gaps=(), coverage="UNKNOWN")

    def _order(self, row: dict[str, object], acquired: datetime) -> ActualOrderFact:
        basis_hash, offset = self._time_basis()
        symbol = _text(row["symbol"])
        spec = self._spec(symbol)
        fields = (
            "ticket",
            "symbol",
            "type",
            "state",
            "volume_initial",
            "volume_current",
            "price_open",
            "time_setup",
            "time_setup_msc",
            "time_done",
            "time_done_msc",
        )
        source = _projection(row, fields)
        setup_raw = _raw_ms(row["time_setup_msc"], row["time_setup"])
        done_raw = _int(row["time_done_msc"])
        if done_raw:
            _raw_ms(done_raw, row["time_done"])
        elif _int(row["time_done"]) != 0:
            raise Ds03Refusal(_INVALID)
        setup = server_time(setup_raw, offset)
        done = server_time(done_raw, offset) if done_raw else None
        at = done if done is not None else setup
        reference = self._reference("order", row["ticket"])
        first = self._first_seen(("order", reference, at.isoformat()), source, acquired)
        return ActualOrderFact.model_validate(
            {
                "order_ref": reference,
                "symbol": symbol,
                "spec_hash": spec.content_hash(),
                "provider_state": _int(row["state"]),
                "provider_type": _int(row["type"]),
                "volume_initial": _dec(row["volume_initial"]),
                "volume_current": _dec(row["volume_current"]),
                "price_open": _dec(row["price_open"]),
                "setup_at": setup,
                "done_at": done,
                "provider_at": at,
                "first_seen_at": first,
                "source_ref": source,
                "setup_time_msc_raw": setup_raw,
                "done_time_msc_raw": done_raw,
                "server_offset_seconds": offset,
                "time_basis_hash": basis_hash,
            }
        )

    def _position(self, row: dict[str, object], acquired: datetime) -> ActualPositionFact:
        basis_hash, offset = self._time_basis()
        symbol = _text(row["symbol"])
        spec = self._spec(symbol)
        fields = (
            "ticket",
            "symbol",
            "type",
            "volume",
            "price_open",
            "time",
            "time_msc",
            "time_update",
            "time_update_msc",
        )
        source = _projection(row, fields)
        opened_raw = _raw_ms(row["time_msc"], row["time"])
        updated_raw = _raw_ms(row["time_update_msc"], row["time_update"])
        at = server_time(updated_raw, offset)
        reference = self._reference("position", row["ticket"])
        first = self._first_seen(("position", reference, at.isoformat()), source, acquired)
        return ActualPositionFact.model_validate(
            {
                "position_ref": reference,
                "symbol": symbol,
                "spec_hash": spec.content_hash(),
                "provider_type": _int(row["type"]),
                "quantity": _dec(row["volume"]),
                "price": _dec(row["price_open"]),
                "opened_at": server_time(opened_raw, offset),
                "updated_at": at,
                "provider_at": at,
                "first_seen_at": first,
                "source_ref": source,
                "opened_time_msc_raw": opened_raw,
                "updated_time_msc_raw": updated_raw,
                "server_offset_seconds": offset,
                "time_basis_hash": basis_hash,
            }
        )

    def _deal(self, row: dict[str, object], acquired: datetime) -> ActualDealFact:
        basis_hash, offset = self._time_basis()
        kind = _int(row["type"])
        raw_symbol = _text(row["symbol"], empty=True)
        symbol: str | None = raw_symbol if kind in (0, 1) else None
        if (kind in (0, 1) and not raw_symbol) or (kind not in (0, 1) and raw_symbol):
            raise Ds03Refusal(_INVALID)
        spec_hash = self._spec(symbol).content_hash() if symbol is not None else None
        fields = (
            "ticket",
            "symbol",
            "type",
            "entry",
            "volume",
            "price",
            "profit",
            "commission",
            "swap",
            "fee",
            "time",
            "time_msc",
        )
        source = _projection(row, fields)
        raw_time = _raw_ms(row["time_msc"], row["time"])
        at = server_time(raw_time, offset)
        reference = self._reference("deal", row["ticket"])
        first = self._first_seen(("deal", reference, at.isoformat()), source, acquired)
        return ActualDealFact.model_validate(
            {
                "deal_ref": reference,
                "kind": "TRADE" if kind in (0, 1) else "NON_MARKET",
                "symbol": symbol,
                "spec_hash": spec_hash,
                "provider_type": kind,
                "entry": _int(row["entry"]),
                "quantity": _dec(row["volume"]),
                "price": _dec(row["price"]),
                "profit": _dec(row["profit"]),
                "commission": _dec(row["commission"]),
                "swap": _dec(row["swap"]),
                "fee": _dec(row["fee"]),
                "provider_at": at,
                "first_seen_at": first,
                "source_ref": source,
                "time_msc_raw": raw_time,
                "server_offset_seconds": offset,
                "time_basis_hash": basis_hash,
            }
        )

    def execute(self, request: ActualRequest) -> ActualReply:
        try:
            request = decode_actual_request(request.canonical_bytes())
            observed = self.attest()
            if isinstance(request, _TIMED_REQUESTS):
                # Refuse before any provider read: these replies label provider time.
                self._time_basis()
            symbol: str | None = None
            spec_hash: str | None = None
            event_at: datetime | None = None
            payload: ActualPayload
            if isinstance(request, ActualAttestRequest):
                payload = ActualAttestationPayload(attestation=observed)
            elif isinstance(request, ActualSymbolsRequest):
                payload = self._catalog_page(request)
            elif isinstance(
                request,
                (ActualSpecRequest, ActualTickRequest, ActualBarsRequest, ActualTicksRequest),
            ):
                symbol = request.symbol
                spec = self._spec(symbol)
                spec_hash = spec.content_hash()
                if isinstance(request, ActualSpecRequest):
                    payload = ActualSpecPayload(spec=spec)
                    event_at = spec.quote_at
                elif isinstance(request, ActualTickRequest):
                    row = _named(self._sdk.symbol_info_tick(symbol))
                    tick = self._tick(row, symbol, datetime.now(UTC))
                    payload = ActualTickPayload(tick=tick)
                    event_at = tick.provider_at
                elif isinstance(request, ActualBarsRequest):
                    payload = self._bars(request)
                    event_at = max((bar.provider_at for bar in payload.bars), default=None)
                else:
                    payload = self._ticks(request)
                    event_at = max((tick.provider_at for tick in payload.ticks), default=None)
                self._spec(symbol)
            elif isinstance(request, ActualOrdersRequest):
                rows = _tuple_rows(self._sdk.orders_get(), 256)
                acquired = datetime.now(UTC)
                orders = tuple(self._order(row, acquired) for row in rows)
                payload = ActualOrdersPayload(orders=orders)
                event_at = max((order.provider_at for order in orders), default=None)
            elif isinstance(request, ActualPositionsRequest):
                rows = _tuple_rows(self._sdk.positions_get(), 256)
                acquired = datetime.now(UTC)
                positions = tuple(self._position(row, acquired) for row in rows)
                payload = ActualPositionsPayload(positions=positions)
                event_at = max((position.provider_at for position in positions), default=None)
            elif isinstance(request, ActualDealsRequest):
                rows = _tuple_rows(
                    self._sdk.history_deals_get(
                        self._server_query(request.start), self._server_query(request.end)
                    ),
                    request.limit,
                )
                acquired = datetime.now(UTC)
                deals = tuple(self._deal(row, acquired) for row in rows)
                payload = ActualDealsPayload(deals=deals)
                event_at = max((deal.provider_at for deal in deals), default=None)
            elif isinstance(request, ActualOrderHistoryRequest):
                rows = _tuple_rows(
                    self._sdk.history_orders_get(
                        self._server_query(request.start), self._server_query(request.end)
                    ),
                    request.limit,
                )
                acquired = datetime.now(UTC)
                history = tuple(self._order(row, acquired) for row in rows)
                payload = ActualOrderHistoryPayload(orders=history)
                event_at = max((order.provider_at for order in history), default=None)
            elif isinstance(request, ActualServerTimeRequest):
                # Onboarding measurement: raw samples and their class, never a UTC label.
                evidence = self._server_time_evidence(
                    request.symbols,
                    samples=request.samples,
                    local_clock_evidence_hash=request.local_clock_evidence_hash,
                    clock=lambda: datetime.now(UTC),
                    pause=sleep,
                    interval_seconds=request.interval_ms / 1000,
                )
                payload = ActualServerTimePayload(
                    evidence=evidence, basis=classify_server_time(evidence)
                )
            elif isinstance(request, ActualDisconnectRequest):
                payload = ActualDisconnectedPayload()
            else:
                raise Ds03Refusal("REQUEST_INVALID")
            post = self.attest()
            if post.identity != observed.identity:
                raise Ds03Refusal("IDENTITY_DRIFT")
            now = datetime.now(UTC)
            provider_at = event_at if event_at is not None else now
            if provider_at > now:
                raise Ds03Refusal("PROVIDER_FUTURE_TIME")
            scope = request.model_dump(
                mode="json", exclude={"request_id", "created_at", "expires_at"}
            )
            raw_hash = hashlib.sha256(
                canonical(
                    {
                        "scope": scope,
                        "provider_at": provider_at.isoformat(),
                        "projection": payload.model_dump(mode="json"),
                    }
                )
            ).hexdigest()
            first_seen = self._batches.setdefault(raw_hash, now)
            envelope = ActualEnvelope.model_validate(
                {
                    "identity": post.identity,
                    "provider_at": provider_at,
                    "provider_time_kind": "SDK_EVENT_TIME"
                    if event_at is not None
                    else "LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP",
                    "first_seen_at": first_seen,
                    "received_at": now,
                    "processed_at": now,
                    "available_at": now,
                    "raw_hash": raw_hash,
                    "normalized_hash": payload.content_hash(),
                    "connector_hash": post.identity.release_hash,
                    "symbol": symbol,
                    "spec_hash": spec_hash,
                    "synthetic": False,
                    "protocol_family": PROTOCOL_FAMILY,
                    "clock_status": "STRUCTURAL_ONLY_CLOCK_BLOCKED",
                }
            )
            return ActualReply(
                request_id=request.request_id,
                operation=request.operation,
                payload=payload,
                envelope=envelope,
                protocol_family=PROTOCOL_FAMILY,
            )
        except Exception as error:
            self.disconnect()
            raise refusal(error, _INVALID) from None


def open_native_readonly(admission: Ds03OnboardingAdmission, *, job_name: str) -> _Mt5ReadPort:
    """Future PRIVATE fixed composition; never invoked during public verification."""
    port: _Mt5ReadPort | None = None
    try:
        admission.verify(datetime.now(UTC))
        observer = _NativeObserver(job_name)
        observer.preflight(admission.binding)
        reference_key = load_ds03_reference_key(admission, now=datetime.now(UTC))
        sdk = _load_native_sdk()
        port = _Mt5ReadPort(sdk, admission, observer, reference_key)
        from auvexo_alpha.infrastructure.ds03_secrets import load_ds03_readonly_password

        password = load_ds03_readonly_password(admission, now=datetime.now(UTC))
        try:
            port._initialize(password)
        finally:
            del password
        return port
    except Exception as error:
        if port is not None:
            port.disconnect()
        raise refusal(error, "UNCLASSIFIED") from None


def actual_rights(admission: Ds03OnboardingAdmission) -> ActualRights:
    return ActualRights(
        review_hash=admission.authority.rights_hash,
        valid_until=admission.authority.rights_valid_until,
        protocol_family=PROTOCOL_FAMILY,
        synthetic=False,
    )
