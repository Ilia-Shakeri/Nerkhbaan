from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..models import Currency, WeightUnit
from .base import (
    ParsedProviderValue,
    ParserContext,
    ParserError,
    exact_path,
    optional_timestamp,
    require_list,
    require_object,
    strict_decimal,
    validate_parsed_value,
)


@dataclass(frozen=True, slots=True)
class GtaSilver925Parser:
    """Read the producer's published 925 gram rate without purity conversion."""

    parser_version: str = "gta-silver-925/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        instrument = context.instrument
        if (
            instrument.instrument_id != "SILVER_925_TOMAN_GRAM"
            or instrument.quote_currency is not Currency.TOMAN
            or instrument.weight_unit is not WeightUnit.GRAM
            or instrument.purity != Decimal("0.925")
        ):
            raise ParserError("instrument_mismatch", "GTA gram rate supports only silver 925 in Toman")
        root = require_object(payload, "GTA silver response")
        if root.get("ok") is not True:
            raise ParserError("provider_error", "GTA silver request failed")
        if root.get("currency") != "IRT":
            raise ParserError("currency_mismatch", "GTA silver rate must explicitly use IRT")
        price = strict_decimal(exact_path(root, "prices", "gram_925"), "prices.gram_925")
        raw_timestamp = exact_path(root, "updated_at")
        if not isinstance(raw_timestamp, str):
            raise ParserError("invalid_timestamp", "GTA updated_at must be an aware ISO timestamp")
        try:
            source_time = datetime.fromisoformat(raw_timestamp.strip().replace("Z", "+00:00"))
            if source_time.tzinfo is None or source_time.utcoffset() is None:
                raise ValueError
        except (ValueError, OverflowError) as exc:
            raise ParserError("invalid_timestamp", "GTA updated_at must be an aware ISO timestamp") from exc
        observed_at = optional_timestamp(raw_timestamp, context, "GTA updated_at")
        bid, ask = self._gram_sides(root, price, context)
        parsed = ParsedProviderValue(
            price=price,
            currency=Currency.TOMAN,
            weight_unit=WeightUnit.GRAM,
            purity=Decimal("0.925"),
            observed_at=observed_at,
            bid=bid,
            ask=ask,
            metadata={
                "source_currency": "TOMAN",
                "source_weight_unit": "gram",
                "source_purity": "0.925",
                "original_value": str(price),
                "conversion_factor": "1",
                "normalization": "none",
                "selected_price_field": "prices.gram_925",
                "timestamp_basis": "updated_at",
                "provider_timestamp_available": True,
                "price_basis": "producer_posted_gram_rate",
                "bid_ask_available": bid is not None,
            },
        )
        return validate_parsed_value(parsed, context)

    @staticmethod
    def _gram_sides(
        root: dict[str, object], price: Decimal, context: ParserContext,
    ) -> tuple[Decimal | None, Decimal | None]:
        if "items" not in root:
            return None, None
        rows = require_list(root["items"], "GTA silver items")
        matches: list[dict[str, object]] = []
        for node in rows:
            row = require_object(node, "GTA silver item")
            title = row.get("title")
            if isinstance(title, str) and title in {"نقره عیار 925", "نقره عیار ۹۲۵"}:
                matches.append(row)
        if not matches:
            return None, None
        if len(matches) != 1:
            raise ParserError("ambiguous_quote", "GTA silver has duplicate 925 gram items")
        row = matches[0]
        if isinstance(row.get("purity"), bool) or str(row.get("purity")) != "925":
            raise ParserError("purity_mismatch", "GTA silver gram item is not purity 925")
        bid = strict_decimal(exact_path(row, "buy_toman"), "GTA gram buy_toman")
        ask = strict_decimal(exact_path(row, "sell_toman"), "GTA gram sell_toman")
        if ask != price:
            raise ParserError("inconsistent_quote", "GTA 925 gram sell differs from posted gram rate")
        if not context.instrument.accepts(bid) or not context.instrument.accepts(ask):
            raise ParserError("outside_sanity_bounds", "GTA silver sides exceed instrument bounds")
        if bid > ask:
            raise ParserError("crossed_orderbook", "GTA gram buy exceeds sell")
        return bid, ask
