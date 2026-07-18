from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Callable, Mapping

from .instruments import get_instrument
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    ProviderQuote,
    SourceType,
    ValidationStatus,
    ensure_utc,
    utc_now,
)

TROY_OUNCE_GRAMS = Decimal("31.1034768")


class DerivedPriceUnavailable(RuntimeError):
    pass


class DerivedPriceEngine:
    def __init__(self) -> None:
        self._formulas: dict[
            str,
            tuple[tuple[str, ...], str, Callable[[Mapping[str, CanonicalQuote]], Decimal]],
        ] = {
            "GOLD_18K_TOMAN_GRAM": (
                ("XAU_USD_OZ", "USDT_TOMAN", "USDT_USD"),
                "XAU_USD_OZ * (USDT_TOMAN / USDT_USD) / 31.1034768 * 0.75",
                lambda values: values["XAU_USD_OZ"].price
                * (values["USDT_TOMAN"].price / values["USDT_USD"].price)
                / TROY_OUNCE_GRAMS
                * Decimal("0.75"),
            ),
            "SILVER_999_TOMAN_GRAM": (
                ("XAG_USD_OZ", "USDT_TOMAN", "USDT_USD"),
                "XAG_USD_OZ * (USDT_TOMAN / USDT_USD) / 31.1034768 * 0.999",
                lambda values: values["XAG_USD_OZ"].price
                * (values["USDT_TOMAN"].price / values["USDT_USD"].price)
                / TROY_OUNCE_GRAMS
                * Decimal("0.999"),
            ),
            "SILVER_925_TOMAN_GRAM": (
                ("SILVER_999_TOMAN_GRAM",),
                "SILVER_999_TOMAN_GRAM * 0.925",
                lambda values: values["SILVER_999_TOMAN_GRAM"].price * Decimal("0.925"),
            ),
            "BTC_TOMAN": (
                ("BTC_USD", "USDT_TOMAN", "USDT_USD"),
                "BTC_USD * (USDT_TOMAN / USDT_USD)",
                lambda values: values["BTC_USD"].price
                * (values["USDT_TOMAN"].price / values["USDT_USD"].price),
            ),
        }

    def derive(
        self,
        instrument_id: str,
        canonical_quotes: Mapping[str, CanonicalQuote],
        *,
        now: datetime | None = None,
    ) -> ProviderQuote:
        normalized = instrument_id.upper()
        try:
            input_ids, formula, calculate = self._formulas[normalized]
        except KeyError as exc:
            raise DerivedPriceUnavailable("No derived formula is registered") from exc
        current = ensure_utc(now or utc_now())
        inputs: dict[str, CanonicalQuote] = {}
        for input_id in input_ids:
            quote = canonical_quotes.get(input_id)
            if quote is None or not self._is_operationally_fresh(quote, current):
                raise DerivedPriceUnavailable(f"Formula input is not fresh: {input_id}")
            inputs[input_id] = quote
        price = calculate(inputs)
        instrument = get_instrument(normalized)
        if not instrument.accepts(price):
            raise DerivedPriceUnavailable("Derived value is outside instrument bounds")
        observed_at = min(quote.observed_at for quote in inputs.values())
        return ProviderQuote.create(
            instrument_id=normalized,
            provider_id=f"derived:{normalized.lower()}",
            source_type=SourceType.DERIVED,
            price=price,
            currency=instrument.quote_currency,
            weight_unit=instrument.weight_unit,
            purity=instrument.purity,
            observed_at=observed_at,
            received_at=current,
            parser_version="derived-formula/1.0.0",
            validation_status=ValidationStatus.ACCEPTED,
            confidence_score=Decimal("0.70"),
            is_direct=False,
            is_derived=True,
            is_suspicious=False,
            metadata={
                "formula": formula,
                "inputs": [
                    {
                        "instrument_id": input_id,
                        "canonical_id": inputs[input_id].id,
                        "idempotency_key": inputs[input_id].idempotency_key,
                        "price": float(inputs[input_id].price),
                        "observed_at": inputs[input_id].observed_at.isoformat(),
                    }
                    for input_id in input_ids
                ],
                "theoretical_value": normalized.startswith("SILVER_"),
            },
            persistence_status=PersistenceStatus.UNPERSISTED,
        )

    @staticmethod
    def _is_operationally_fresh(quote: CanonicalQuote, now: datetime) -> bool:
        return (
            quote.status
            in {
                CanonicalStatus.LIVE,
                CanonicalStatus.CONFIRMED,
                CanonicalStatus.FRESH_CACHE,
                CanonicalStatus.UNPERSISTED,
                CanonicalStatus.DERIVED_FALLBACK,
            }
            and now <= quote.valid_until
            and now <= quote.expires_at
        )


derived_price_engine = DerivedPriceEngine()
