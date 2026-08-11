from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping

from ..config import settings
from .instruments import get_instrument
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    PriceSemantic,
    ProviderQuote,
    SourceSemantic,
    SourceType,
    ValidationStatus,
    ensure_utc,
    utc_now,
)

TROY_OUNCE_GRAMS = settings.troy_ounce_grams
USDT_USD_SAFE_MIN = settings.usdt_usd_safe_min
USDT_USD_SAFE_MAX = settings.usdt_usd_safe_max


class DerivedPriceUnavailable(RuntimeError):
    pass


class DerivedPriceEngine:
    def __init__(self) -> None:
        self._formulas: dict[
            str,
            tuple[tuple[str, ...], str, Callable[[Mapping[str, CanonicalQuote]], Decimal]],
        ] = {
            "GOLD_18K_TOMAN_GRAM": (
                ("GOLD_24K_TOMAN_GRAM",),
                "GOLD_24K_TOMAN_GRAM * 0.75",
                lambda values: values["GOLD_24K_TOMAN_GRAM"].price * Decimal("0.75"),
            ),
            "GOLD_24K_TOMAN_GRAM": (
                ("XAU_USD_OZ", "USDT_TOMAN", "USDT_USD"),
                "XAU_USD_OZ * (USDT_TOMAN / USDT_USD) / TROY_OUNCE_GRAMS",
                lambda values: values["XAU_USD_OZ"].price
                * (values["USDT_TOMAN"].price / values["USDT_USD"].price)
                / TROY_OUNCE_GRAMS,
            ),
            "SILVER_999_TOMAN_GRAM": (
                ("XAG_USD_OZ", "USDT_TOMAN", "USDT_USD"),
                "XAG_USD_OZ * (USDT_TOMAN / USDT_USD) / TROY_OUNCE_GRAMS * 0.999",
                lambda values: values["XAG_USD_OZ"].price
                * (values["USDT_TOMAN"].price / values["USDT_USD"].price)
                / TROY_OUNCE_GRAMS
                * Decimal("0.999"),
            ),
            "SILVER_925_TOMAN_GRAM": (
                ("SILVER_999_TOMAN_GRAM",),
                "SILVER_999_TOMAN_GRAM * 0.925 / 0.999",
                lambda values: values["SILVER_999_TOMAN_GRAM"].price
                * Decimal("0.925")
                / Decimal("0.999"),
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
        if normalized == "GOLD_18K_TOMAN_GRAM" and "GOLD_24K_TOMAN_GRAM" not in canonical_quotes:
            input_ids = ("XAU_USD_OZ", "USDT_TOMAN", "USDT_USD")
            formula = "XAU_USD_OZ * (USDT_TOMAN / USDT_USD) / TROY_OUNCE_GRAMS * 0.75"

            def calculate(values: Mapping[str, CanonicalQuote]) -> Decimal:
                return (
                    values["XAU_USD_OZ"].price
                    * (values["USDT_TOMAN"].price / values["USDT_USD"].price)
                    / TROY_OUNCE_GRAMS
                    * Decimal("0.75")
                )
        current = ensure_utc(now or utc_now())
        inputs: dict[str, CanonicalQuote] = {}
        input_depths: dict[str, int] = {}
        input_confidences: dict[str, Decimal] = {}
        provenance: list[str] = []
        for input_id in input_ids:
            quote = canonical_quotes.get(input_id)
            if quote is None or not self._is_operationally_fresh(quote, current):
                raise DerivedPriceUnavailable(f"Formula input is not fresh: {input_id}")
            depth = self._derivation_depth(quote)
            source_provenance = self._provenance(input_id, quote)
            if normalized in source_provenance:
                raise DerivedPriceUnavailable("Derived formula contains a cycle")
            inputs[input_id] = quote
            input_depths[input_id] = depth
            input_confidences[input_id] = self._confidence(quote)
            for source in source_provenance:
                if source not in provenance:
                    provenance.append(source)
        derivation_depth = max(input_depths.values(), default=0) + 1
        if derivation_depth > 3:
            raise DerivedPriceUnavailable("Derived formula exceeds maximum depth")
        confidence_score = min(input_confidences.values(), default=Decimal(1)) * Decimal(
            "0.90"
        )
        usdt_quote = inputs.get("USDT_USD")
        if usdt_quote is not None and not (
            USDT_USD_SAFE_MIN <= usdt_quote.price <= USDT_USD_SAFE_MAX
        ):
            raise DerivedPriceUnavailable("USDT/USD input is outside the safe range")
        price = calculate(inputs)
        instrument = get_instrument(normalized)
        if not instrument.accepts(price):
            raise DerivedPriceUnavailable("Derived value is outside instrument bounds")
        observed_at = min(quote.observed_at for quote in inputs.values())
        input_live_eligible_until = min(
            quote.valid_until for quote in inputs.values()
        )
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
            confidence_score=confidence_score,
            is_direct=False,
            is_derived=True,
            is_suspicious=False,
            source_semantic=SourceSemantic.DERIVED,
            source_family="internal_formula",
            venue="nerkhbaan",
            selected_price_semantic=PriceSemantic.FORMULA,
            original_currency=instrument.quote_currency.value,
            original_value=price,
            conversion_factor=Decimal(1),
            route_id=f"formula:{normalized.lower()}",
            derivation_depth=derivation_depth,
            provenance=tuple(provenance),
            metadata={
                "formula": formula,
                "inputs": [
                    {
                        "instrument_id": input_id,
                        "canonical_id": inputs[input_id].id,
                        "idempotency_key": inputs[input_id].idempotency_key,
                        "price": str(inputs[input_id].price),
                        "observed_at": inputs[input_id].observed_at.isoformat(),
                        "valid_until": inputs[input_id].valid_until.isoformat(),
                        "derivation_depth": input_depths[input_id],
                        "confidence_score": str(input_confidences[input_id]),
                        "provenance": self._provenance(input_id, inputs[input_id]),
                    }
                    for input_id in input_ids
                ],
                "derivation_depth": derivation_depth,
                "provenance": provenance,
                "input_live_eligible_until": input_live_eligible_until.isoformat(),
                "theoretical_value": normalized in {
                    "GOLD_18K_TOMAN_GRAM",
                    "GOLD_24K_TOMAN_GRAM",
                    "SILVER_999_TOMAN_GRAM",
                    "SILVER_925_TOMAN_GRAM",
                },
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
                CanonicalStatus.DERIVED_FALLBACK,
            }
            and quote.is_persisted
            and now <= quote.valid_until
            and now <= quote.expires_at
        )

    @staticmethod
    def _derivation_depth(quote: CanonicalQuote) -> int:
        raw = quote.source_summary.get("derivation_depth")
        if raw is None:
            return 1 if quote.source_summary.get("derived", False) else 0
        try:
            depth = int(raw)
        except (TypeError, ValueError) as exc:
            raise DerivedPriceUnavailable("Input derivation depth is invalid") from exc
        if depth < 0:
            raise DerivedPriceUnavailable("Input derivation depth is invalid")
        return depth

    @staticmethod
    def _confidence(quote: CanonicalQuote) -> Decimal:
        raw = quote.source_summary.get("confidence_score", 1)
        try:
            confidence = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DerivedPriceUnavailable("Input confidence is invalid") from exc
        if not confidence.is_finite() or not Decimal(0) <= confidence <= Decimal(1):
            raise DerivedPriceUnavailable("Input confidence is invalid")
        return confidence

    @staticmethod
    def _provenance(input_id: str, quote: CanonicalQuote) -> list[str]:
        raw = quote.source_summary.get("provenance", [])
        if not isinstance(raw, (list, tuple)):
            raise DerivedPriceUnavailable("Input provenance is invalid")
        result: list[str] = []
        for value in (*raw, input_id):
            normalized = str(value).strip().upper()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


derived_price_engine = DerivedPriceEngine()
