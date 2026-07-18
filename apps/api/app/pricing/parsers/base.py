from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from ..models import Currency, InstrumentDefinition, WeightUnit, ensure_utc

_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_REDACTED_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
    "x_access_token",
}
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class ParserError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ParserContext:
    instrument: InstrumentDefinition
    received_at: datetime
    maximum_timestamp_age_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))


@dataclass(frozen=True, slots=True)
class ParsedProviderValue:
    price: Decimal
    currency: Currency
    weight_unit: WeightUnit
    purity: Decimal | None
    observed_at: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExplicitParser(Protocol):
    parser_version: str

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        ...


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ParserError("invalid_shape", f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ParserError("invalid_shape", f"{label} must be an array")
    return value


def exact_path(payload: object, *tokens: str) -> object:
    current = payload
    for token in tokens:
        current_object = require_object(current, ".".join(tokens))
        if token not in current_object:
            raise ParserError("missing_field", f"Missing response field: {'.'.join(tokens)}")
        current = current_object[token]
    return current


def strict_decimal(value: object, label: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ParserError("invalid_number", f"{label} is not numeric")
    if isinstance(value, str):
        normalized = (
            value.translate(_DIGIT_TRANSLATION)
            .strip()
            .replace(",", "")
            .replace("_", "")
        )
        if not _NUMBER_PATTERN.fullmatch(normalized):
            raise ParserError("invalid_number", f"{label} has an invalid numeric format")
    elif isinstance(value, (int, float, Decimal)):
        normalized = str(value)
    else:
        raise ParserError("invalid_number", f"{label} is not numeric")
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ParserError("invalid_number", f"{label} is not numeric") from exc
    invalid_sign = result < 0 if allow_zero else result <= 0
    if not result.is_finite() or invalid_sign:
        raise ParserError("invalid_number", f"{label} must be finite and positive")
    return result


def optional_timestamp(
    value: object | None,
    context: ParserContext,
    label: str,
) -> datetime:
    if value is None:
        return context.received_at
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (int, float, Decimal)):
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000
            result = datetime.fromtimestamp(numeric, UTC)
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                numeric = float(stripped)
                if numeric > 10_000_000_000:
                    numeric /= 1000
                result = datetime.fromtimestamp(numeric, UTC)
            else:
                result = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
                result = ensure_utc(result)
        else:
            raise ValueError
    except (OSError, OverflowError, ValueError) as exc:
        raise ParserError("invalid_timestamp", f"{label} is invalid") from exc
    age = (context.received_at - result).total_seconds()
    if age < -30 or age > context.maximum_timestamp_age_seconds:
        raise ParserError("stale_timestamp", f"{label} is outside the allowed age")
    return context.received_at if age < 0 else result


def validate_parsed_value(
    value: ParsedProviderValue,
    context: ParserContext,
) -> ParsedProviderValue:
    instrument = context.instrument
    if value.currency is not instrument.quote_currency:
        raise ParserError("currency_mismatch", "Provider currency does not match instrument")
    if value.weight_unit is not instrument.weight_unit:
        raise ParserError("unit_mismatch", "Provider unit does not match instrument")
    if value.purity != instrument.purity:
        raise ParserError("purity_mismatch", "Provider purity does not match instrument")
    if not instrument.accepts(value.price):
        raise ParserError("outside_sanity_bounds", "Provider price is outside instrument bounds")
    if value.bid is not None and value.ask is not None and value.bid > value.ask:
        raise ParserError("crossed_orderbook", "Provider bid exceeds ask")
    return value


def sanitize_raw_payload(payload: object, maximum_bytes: int) -> str:
    bounded_limit = max(1024, min(maximum_bytes, 1_048_576))

    def sanitize(value: object, depth: int = 0) -> object:
        if depth >= 8:
            return "[depth-limited]"
        if isinstance(value, dict):
            clean: dict[str, object] = {}
            for key, nested in list(value.items())[:100]:
                normalized = str(key).lower().replace("-", "_")
                sensitive = (
                    normalized in _REDACTED_KEYS
                    or normalized.endswith(("_api_key", "_password", "_secret", "_token"))
                )
                clean[str(key)[:100]] = (
                    "[redacted]"
                    if sensitive
                    else sanitize(nested, depth + 1)
                )
            return clean
        if isinstance(value, list):
            return [sanitize(item, depth + 1) for item in value[:100]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1000]

    encoded = json.dumps(
        sanitize(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded) <= bounded_limit:
        return encoded.decode("utf-8")
    suffix = b'"[truncated]"}'
    clipped = encoded[: max(1, bounded_limit - len(suffix))]
    return clipped.decode("utf-8", errors="ignore") + suffix.decode("ascii")
