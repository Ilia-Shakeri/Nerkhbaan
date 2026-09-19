from .models import CanonicalQuote, CanonicalStatus


def allowed_current_quote(quote: CanonicalQuote) -> bool:
    if quote.instrument_id not in {"GOLD_18K_TOMAN_GRAM", "GOLD_24K_TOMAN_GRAM"}:
        return True
    summary = quote.source_summary
    return not (
        summary.get("derived")
        or quote.status is CanonicalStatus.DERIVED_FALLBACK
        or str(summary.get("primary_provider_id", "")).startswith("derived:")
        or summary.get("primary_provider_id") == "persian_toolbox_gold24"
        or "persian_toolbox_gold24" in (summary.get("provider_ids") or [])
    )
