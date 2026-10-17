from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..models import Currency, WeightUnit
from .base import (
    ParsedProviderValue, ParserContext, ParserError, optional_timestamp,
    require_list, require_object, validate_parsed_value,
)
from .nerkhsanj_history import _price


_MARKETS = {
    "GLD_18C_750TMN": ("GOLD_18K_TOMAN_GRAM", "XAU_18K", Decimal("0.750")),
    "SLV_925TMN": ("SILVER_925_TOMAN_GRAM", "XAG", Decimal("0.925")),
}


def _clock(value: object, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 80:
        raise ParserError("invalid_timestamp", f"{label} needs a timezone-bearing timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ParserError("invalid_timestamp", f"{label} needs a timezone-bearing timestamp") from exc


@dataclass(frozen=True, slots=True)
class WallgoldPublicQuoteParser:
    symbol: str
    side: str = "buy"
    parser_version: str = "wallgold-public-quote/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        market = _MARKETS.get(self.symbol)
        instrument = context.instrument
        if market is None or instrument.instrument_id != market[0]:
            raise ParserError("unsupported_symbol", "Published Wallgold market differs from instrument")
        if self.side not in {"buy", "sell"}:
            raise ParserError("unsupported_side", "Published quote side must be buy or sell")
        if instrument.quote_currency is not Currency.TOMAN:
            raise ParserError("currency_mismatch", "Wallgold public prices quote Toman")
        if instrument.weight_unit is not WeightUnit.GRAM:
            raise ParserError("unit_mismatch", "Wallgold public prices quote each gram")
        if instrument.base_asset != market[1] or instrument.purity != market[2]:
            raise ParserError("purity_mismatch", "Wallgold source purity differs from instrument")
        root = require_object(payload, "Wallgold public prices response")
        if root.get("success") is not True:
            raise ParserError("provider_error", "Wallgold public prices request failed")
        rows = require_list(root.get("result"), "public prices.result")
        if len(rows) > 64:
            raise ParserError("payload_too_large", "Public prices has too many market sides")
        matches = [row for raw in rows
                   if (row := require_object(raw, "public market quote")).get("symbol") == self.symbol
                   and row.get("side") == self.side]
        if len(matches) != 1:
            raise ParserError("unsupported_symbol", "Expected one unique published market and side")
        row = matches[0]
        price = _price(row.get("price"))
        published = _clock(row.get("currentTime"), "public quote response clock")
        # currentTime is the publisher's response clock, never a claimed last
        # trade time. Its age remains bounded by this instrument's live policy.
        observed_at = optional_timestamp(published.isoformat(), context, "public quote response clock")
        expires = _clock(row.get("priceExpiresAt"), "public quote expiry")
        declared_ttl = _price(row.get("ttl"))
        validity_seconds = Decimal(str((expires - published).total_seconds()))
        # Public UI quotes currently allow one day; private order quotes use a
        # different endpoint and contract. A remote expiry never sets our TTL.
        if (declared_ttl > Decimal("86400") or validity_seconds <= 0
                or validity_seconds > Decimal("86460")
                or abs(declared_ttl - validity_seconds) > Decimal("1")
                or expires <= context.received_at):
            raise ParserError("invalid_quote_validity", "Public quote validity is expired, inconsistent or unbounded")
        return validate_parsed_value(ParsedProviderValue(
            price=price, currency=Currency.TOMAN, weight_unit=WeightUnit.GRAM,
            purity=market[2], observed_at=observed_at,
            metadata={
                "symbol": self.symbol, "source_selected_side": self.side,
                "source_currency": "TOMAN", "source_weight_unit": "gram",
                "source_purity": str(market[2]), "original_value": str(price),
                "conversion_factor": "1", "selected_price_field": "result[].price",
                "timestamp_basis": "provider_response_clock", "provider_timestamp_available": True,
                "source_timestamp_scope": "response_quote_snapshot",
                "source_observation_time_known": False, "source_trade_time_known": False,
                "source_price_expires_at": expires.isoformat(),
                "source_declared_ttl_seconds": str(declared_ttl),
                "source_price_semantic": "published_side_reference_quote",
            },
        ), context)
