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


def _purity_ratio(target_instrument_id: str, source_instrument_id: str) -> Decimal:
    """Fineness conversion between two instruments of the same metal.

    Converting 24K to 18K with a flat 0.75 ignores that the 24K reference is
    quoted at 0.9999 fine, not 1.0. Deriving the factor from the instrument
    definitions keeps every metal conversion consistent instead of relying on
    a constant that happens to be right for one pair and wrong for another.
    """
    target = get_instrument(target_instrument_id).purity or Decimal(1)
    source = get_instrument(source_instrument_id).purity or Decimal(1)
    return target / source


class DerivedPriceEngine:
    """Formula fallback for instruments with no live direct source.

    Every Toman metal needs a USD->Toman rate. ``USD_TOMAN`` is the correct
    bridge; ``USDT_TOMAN / USDT_USD`` is only a stand-in, and in this market it
    runs at a premium, so results carry the bridge they used in metadata.
    """

    #: Preferred FX bridge first, stand-in second.
    _FX_BRIDGES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("usd_toman", ("USD_TOMAN",)),
        ("usdt_proxy", ("USDT_TOMAN", "USDT_USD")),
    )

    def __init__(self) -> None:
        self._formulas: dict[
            str,
            tuple[tuple[str, ...], str, Callable[[Mapping[str, CanonicalQuote]], Decimal]],
        ] = {
            "GOLD_18K_TOMAN_GRAM": (
                ("GOLD_24K_TOMAN_GRAM",),
                "GOLD_24K_TOMAN_GRAM * purity(18K)/purity(24K)",
                lambda values: values["GOLD_24K_TOMAN_GRAM"].price
                * _purity_ratio("GOLD_18K_TOMAN_GRAM", "GOLD_24K_TOMAN_GRAM"),
            ),
            "SILVER_925_TOMAN_GRAM": (
                ("SILVER_999_TOMAN_GRAM",),
                "SILVER_999_TOMAN_GRAM * purity(925)/purity(999)",
                lambda values: values["SILVER_999_TOMAN_GRAM"].price
                * _purity_ratio("SILVER_925_TOMAN_GRAM", "SILVER_999_TOMAN_GRAM"),
            ),
            # Stand-in for a free-market USD rate. Approximating it once here
            # keeps a single, inspectable place where the USDT premium enters
            # the system rather than burying it in every metal formula.
            "USD_TOMAN": (
                ("USDT_TOMAN", "USDT_USD"),
                "USDT_TOMAN / USDT_USD",
                lambda values: values["USDT_TOMAN"].price / values["USDT_USD"].price,
            ),
        }
        #: Instruments derived from a USD reference through an FX bridge.
        self._fx_formulas: dict[str, tuple[str, Decimal]] = {
            "GOLD_24K_TOMAN_GRAM": (
                "XAU_USD_OZ",
                _purity_ratio("GOLD_24K_TOMAN_GRAM", "XAU_USD_OZ") / TROY_OUNCE_GRAMS,
            ),
            "SILVER_999_TOMAN_GRAM": (
                "XAG_USD_OZ",
                _purity_ratio("SILVER_999_TOMAN_GRAM", "XAG_USD_OZ") / TROY_OUNCE_GRAMS,
            ),
            "BTC_TOMAN": ("BTC_USD", Decimal(1)),
        }

    def _fx_plan(
        self,
        canonical_quotes: Mapping[str, CanonicalQuote],
        current: datetime,
    ) -> tuple[str, tuple[str, ...]] | None:
        """Pick the first FX bridge whose inputs are all operationally fresh."""
        for name, inputs in self._FX_BRIDGES:
            if all(
                self._is_operationally_fresh(quote, current)
                for quote in (canonical_quotes.get(item) for item in inputs)
                if quote is not None
            ) and all(item in canonical_quotes for item in inputs):
                return name, inputs
        return None

    @staticmethod
    def _fx_rate(bridge: str, values: Mapping[str, CanonicalQuote]) -> Decimal:
        if bridge == "usd_toman":
            return values["USD_TOMAN"].price
        return values["USDT_TOMAN"].price / values["USDT_USD"].price

    def derive(
        self,
        instrument_id: str,
        canonical_quotes: Mapping[str, CanonicalQuote],
        *,
        now: datetime | None = None,
    ) -> ProviderQuote:
        normalized = instrument_id.upper()
        current = ensure_utc(now or utc_now())
        plan = self._resolve_formula(normalized, canonical_quotes, current)
        if plan is None:
            raise DerivedPriceUnavailable("No derived formula is available")
        input_ids, formula, calculate, fx_bridge = plan
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
                "fx_bridge": fx_bridge,
                # A USDT-bridged Toman metal price is not the same quality as
                # one bridged through a free-market USD rate; consumers need to
                # be able to tell them apart. A USD_TOMAN input that was itself
                # derived is still the proxy, one level down.
                "fx_bridge_is_proxy": self._bridge_is_proxy(fx_bridge, inputs),
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

    def _resolve_formula(
        self,
        normalized: str,
        quotes: Mapping[str, CanonicalQuote],
        current: datetime,
    ):
        """Choose the cheapest formula whose inputs are all currently usable.

        Same-metal chains are preferred (18K from 24K keeps the local market's
        own premium); only when that chain is cold do we reconstruct the price
        from the international reference through an FX bridge.
        """
        direct = self._formulas.get(normalized)
        if direct is not None:
            input_ids, formula, calculate = direct
            if all(
                quotes.get(item) is not None
                and self._is_operationally_fresh(quotes[item], current)
                for item in input_ids
            ):
                return input_ids, formula, calculate, None

        fx = self._fx_formulas.get(normalized)
        if fx is None and normalized == "GOLD_18K_TOMAN_GRAM":
            # The 24K chain is cold, so go straight from the ounce reference.
            fx = (
                "XAU_USD_OZ",
                _purity_ratio("GOLD_18K_TOMAN_GRAM", "XAU_USD_OZ") / TROY_OUNCE_GRAMS,
            )
        if fx is None:
            return None
        reference_id, factor = fx
        bridge = self._fx_plan(quotes, current)
        if bridge is None:
            return None
        bridge_name, bridge_inputs = bridge

        def calculate(
            values: Mapping[str, CanonicalQuote],
            _reference: str = reference_id,
            _factor: Decimal = factor,
            _bridge: str = bridge_name,
        ) -> Decimal:
            return values[_reference].price * self._fx_rate(_bridge, values) * _factor

        formula = f"{reference_id} * fx[{bridge_name}] * {factor}"
        return (reference_id, *bridge_inputs), formula, calculate, bridge_name

    @staticmethod
    def _bridge_is_proxy(
        fx_bridge: str | None,
        inputs: Mapping[str, CanonicalQuote],
    ) -> bool:
        if fx_bridge is None:
            return False
        if fx_bridge != "usd_toman":
            return True
        bridge_quote = inputs.get("USD_TOMAN")
        if bridge_quote is None:
            return True
        return bool(bridge_quote.source_summary.get("derived", False))

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
