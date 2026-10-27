"""Strict bounded DS-04-A1 snapshot parser. No spot-candle coercion or unit inference."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast

from auvexo_alpha.domain.contracts import exact_decimal, utc_time
from auvexo_alpha.domain.open_interest import OIObservation, OISymbol

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("OI_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse_oi(
    body: bytes,
    *,
    symbol: OISymbol,
    slot_at: datetime,
    request_sent_at: datetime,
    first_seen_at: datetime,
    received_at: datetime,
    processed_at: datetime,
    code_revision: str,
    code_hash: str,
    review_receipt_hash: str | None = None,
) -> OIObservation:
    if type(body) is not bytes or not 0 < len(body) <= 4096:
        raise ValueError("OI_BODY_BUDGET")
    if symbol not in ("BTCUSDT", "ETHUSDT"):
        raise ValueError("OI_SYMBOL")
    try:
        parsed: object = json.loads(body, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise ValueError("OI_JSON_SCHEMA") from error
    if not isinstance(parsed, dict) or set(parsed) != {"openInterest", "symbol", "time"}:
        raise ValueError("OI_SCHEMA")
    data = cast(dict[str, object], parsed)
    if data["symbol"] != symbol:
        raise ValueError("OI_SYMBOL")
    raw_value = data["openInterest"]
    if not isinstance(raw_value, str) or len(raw_value) > 38:
        raise ValueError("OI_DECIMAL")
    try:
        value = exact_decimal(raw_value)
    except ValueError as error:
        raise ValueError("OI_DECIMAL") from error
    if value < 0:
        raise ValueError("OI_NEGATIVE")
    provider_ms = data["time"]
    if type(provider_ms) is not int or not 1_577_836_800_000 <= provider_ms <= 9_999_999_999_999:
        raise ValueError("OI_TIMESTAMP_UNIT")
    provider_at = EPOCH + timedelta(milliseconds=provider_ms)
    received = utc_time(received_at)
    if provider_at > received:
        raise ValueError("OI_PROVIDER_FUTURE")
    if received - provider_at > timedelta(seconds=120):
        raise ValueError("OI_PROVIDER_STALE")
    return OIObservation(
        symbol=symbol,
        slot_at=utc_time(slot_at),
        raw_open_interest=raw_value,
        value=value,
        provider_time_ms=provider_ms,
        provider_at=provider_at,
        request_sent_at=utc_time(request_sent_at),
        first_seen_at=utc_time(first_seen_at),
        received_at=received,
        processed_at=utc_time(processed_at),
        available_at=utc_time(processed_at),
        code_revision=code_revision,
        code_hash=code_hash,
        raw_hash=hashlib.sha256(body).hexdigest(),
        review_receipt_hash=review_receipt_hash,
    )
