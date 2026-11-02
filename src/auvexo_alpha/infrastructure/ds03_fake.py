"""Fixed synthetic DS-03 terminal; never imports an SDK or opens a provider session."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from auvexo_alpha.domain.ds03 import (
    AttestationPayload,
    AttestRequest,
    BarsPayload,
    BarsRequest,
    DealsPayload,
    DealsRequest,
    DisconnectedPayload,
    DisconnectRequest,
    Ds03Attestation,
    Ds03Bar,
    Ds03Error,
    Ds03Gap,
    Ds03Identity,
    Ds03Payload,
    Ds03Reply,
    Ds03Request,
    Ds03Rights,
    Ds03SourceEnvelope,
    Ds03SymbolSpec,
    Ds03Tick,
    OrderHistoryPayload,
    OrderHistoryRequest,
    OrdersPayload,
    OrdersRequest,
    PositionsPayload,
    PositionsRequest,
    SpecPayload,
    SpecRequest,
    SymbolsPayload,
    SymbolsRequest,
    TickPayload,
    TickRequest,
    TicksPayload,
    TicksRequest,
    decode_request,
)


def _digest(label: str) -> str:
    return hashlib.sha256(("DS03_SYNTHETIC_ONLY:" + label).encode("ascii")).hexdigest()


def synthetic_identity() -> Ds03Identity:
    return Ds03Identity(
        account_ref="synthetic.ds03.demo",
        login_hash=_digest("login"),
        server="synthetic.assigned-demo",
        account_type="STANDARD_SYNTHETIC",
        currency="USD",
        leverage=100,
        mode="DEMO",
        terminal_build=5000,
        terminal_version="synthetic.mt5.v1",
        process_ref="synthetic.mt5.readonly.v1",
        profile_hash=_digest("profile"),
        release_hash=_digest("release"),
        config_hash=_digest("config"),
        rights_hash=_digest("rights"),
    )


def synthetic_rights() -> Ds03Rights:
    return Ds03Rights(
        review_hash=_digest("rights"), valid_until=datetime(2100, 1, 1, tzinfo=UTC), synthetic=True
    )


class SyntheticDs03Terminal:
    """Only a fixed fake backend. All facts and read-only evidence are synthetic."""

    def __init__(self) -> None:
        self.identity = synthetic_identity()
        self.connected = True
        self._opened_at = datetime.now(UTC)
        self._first_seen: dict[str, datetime] = {}
        self._specs = {
            name: Ds03SymbolSpec(
                symbol=name,
                description="Synthetic instrument; no source qualification",
                category="SYNTHETIC_CFD",
                digits=2,
                point=Decimal("0.01"),
                tick_size=Decimal("0.01"),
                contract_size=Decimal("1"),
                volume_min=Decimal("0.01"),
                volume_max=Decimal("10"),
                volume_step=Decimal("0.01"),
                tick_value=Decimal("0.01"),
                tick_value_profit=Decimal("0.01"),
                tick_value_loss=Decimal("0.01"),
                volume_limit=Decimal("10"),
                stops_level=0,
                freeze_level=0,
                trade_mode="DISABLED",
                order_modes=None,
                fill_modes=None,
                margin_mode=None,
                execution_mode=None,
                base_currency=base,
                profit_currency="USD",
                margin_currency="USD",
                sessions=None,
                spread=Decimal("0.10"),
                swap_mode=None,
                swap_long=None,
                swap_short=None,
                quote_at=self._opened_at,
                history_start=None,
                history_end=None,
            )
            for name, base in (("synthetic.BTCUSDm", "BTC"), ("synthetic.ETHUSDm", "ETH"))
        }

    def attest(self) -> Ds03Attestation:
        if not self.connected:
            raise Ds03Error()
        return Ds03Attestation(
            identity=self.identity,
            observed_at=datetime.now(UTC),
            connected=True,
            credential_readonly=True,
            account_trade_allowed=False,
            terminal_trade_allowed=False,
        )

    def disconnect(self) -> None:
        self.connected = False

    def _spec(self, symbol: str) -> Ds03SymbolSpec:
        if symbol not in self._specs:
            raise Ds03Error()
        return self._specs[symbol]

    @staticmethod
    def _tick(symbol: str, at: datetime) -> Ds03Tick:
        return Ds03Tick(
            symbol=symbol,
            provider_at=at,
            bid=Decimal("100.00"),
            ask=Decimal("100.10"),
            last=None,
            volume=None,
        )

    def execute(self, request: Ds03Request) -> Ds03Reply:
        if not self.connected:
            raise Ds03Error()
        request = decode_request(request.canonical_bytes())
        symbol: str | None = None
        spec_hash: str | None = None
        provider_at = self._opened_at
        payload: Ds03Payload
        if isinstance(request, AttestRequest):
            observed = self.attest()
            payload = AttestationPayload(attestation=observed)
            provider_at = observed.observed_at
        elif isinstance(request, SymbolsRequest):
            payload = SymbolsPayload(symbols=tuple(self._specs))
        elif isinstance(request, (SpecRequest, TickRequest, BarsRequest, TicksRequest)):
            symbol = request.symbol
            spec = self._spec(symbol)
            spec_hash = spec.content_hash()
            if isinstance(request, SpecRequest):
                payload = SpecPayload(spec=spec)
            elif isinstance(request, TickRequest):
                payload = TickPayload(tick=self._tick(symbol, self._opened_at))
            elif isinstance(request, BarsRequest):
                interval = timedelta(seconds=request.timeframe_seconds)
                count = (
                    int((request.end - request.start).total_seconds()) // request.timeframe_seconds
                )
                epoch = datetime(1970, 1, 1, tzinfo=UTC)
                if count < 1 or any(
                    (t - epoch).total_seconds() % request.timeframe_seconds
                    for t in (request.start, request.end)
                ):
                    raise Ds03Error()
                take = min(count, request.limit)
                bars = tuple(
                    Ds03Bar(
                        symbol=symbol,
                        provider_at=request.start + interval * i,
                        open=Decimal("100"),
                        high=Decimal("101"),
                        low=Decimal("99"),
                        close=Decimal("100.5"),
                        tick_volume=10,
                        spread=None,
                        real_volume=None,
                    )
                    for i in range(take)
                )
                gaps = (
                    ()
                    if take == count
                    else (
                        Ds03Gap(
                            start=request.start + interval * take,
                            end=request.end,
                            reason="SYNTHETIC_BATCH_BOUND",
                        ),
                    )
                )
                payload = BarsPayload(
                    bars=bars, gaps=gaps, coverage="COMPLETE" if not gaps else "PARTIAL"
                )
                provider_at = request.end
            else:
                payload = TicksPayload(
                    ticks=(self._tick(symbol, request.start),), gaps=(), coverage="UNKNOWN"
                )
                provider_at = request.end
        elif isinstance(request, OrdersRequest):
            payload = OrdersPayload(orders=())
        elif isinstance(request, PositionsRequest):
            payload = PositionsPayload(positions=())
        elif isinstance(request, DealsRequest):
            payload = DealsPayload(deals=())
            provider_at = request.end
        elif isinstance(request, OrderHistoryRequest):
            payload = OrderHistoryPayload(orders=())
            provider_at = request.end
        elif isinstance(request, DisconnectRequest):
            # The application validates pre/post identity before calling disconnect().
            payload = DisconnectedPayload()
        else:
            raise Ds03Error()
        now = datetime.now(UTC)
        if provider_at > now:
            raise Ds03Error()
        raw_scope = request.model_dump(
            mode="json", exclude={"request_id", "created_at", "expires_at"}
        )
        raw_scope["provider_at"] = provider_at.isoformat()
        raw = json.dumps(raw_scope, sort_keys=True, separators=(",", ":")).encode("ascii")
        raw_hash = hashlib.sha256(
            b"DS03_SYNTHETIC_RAW\x00" + raw + payload.canonical_bytes()
        ).hexdigest()
        first_seen = self._first_seen.setdefault(raw_hash, now)
        return Ds03Reply(
            request_id=request.request_id,
            operation=request.operation,
            payload=payload,
            envelope=Ds03SourceEnvelope(
                identity=self.identity,
                provider_at=provider_at,
                first_seen_at=first_seen,
                received_at=now,
                processed_at=now,
                available_at=now,
                raw_hash=raw_hash,
                normalized_hash=payload.content_hash(),
                connector_hash=self.identity.release_hash,
                symbol=symbol,
                spec_hash=spec_hash,
                source_id="DS-03",
                provider="EXNESS",
                product="CFD",
                synthetic=True,
                clock_status="STRUCTURAL_ONLY_CLOCK_BLOCKED",
            ),
        )
