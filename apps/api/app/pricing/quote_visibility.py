from .models import CanonicalQuote, CanonicalStatus
from . import rights


def allowed_current_quote(quote: CanonicalQuote) -> bool:
    if not rights.canonical_allowed(quote.source_summary, "display"):
        return False
    candidate = quote.candidate_provider_id
    if (candidate is not None and not rights.provider_allowed(candidate, "display")) or (rights.enforced() and quote.candidate_price is not None and candidate is None):
        return False
    if rights.enforced() and quote.status is CanonicalStatus.DERIVED_FALLBACK and not (
        quote.source_summary.get("derived") is True
        or str(quote.source_summary.get("primary_provider_id", "")).startswith("derived:")
    ):
        return False
    if quote.source_summary.get("historical_backfill"):
        return False
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
