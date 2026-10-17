from .models import CanonicalQuote, CanonicalStatus
from . import rights
from .registry import PROVIDERS, RETIRED_PROVIDERS


def _has_non_current_source(summary, depth=0) -> bool:
    if not isinstance(summary, dict) or depth > 6:
        return False
    if summary.get("timestamp_precision") == "day":
        return True
    provider_ids = summary.get("provider_ids", [])
    if isinstance(provider_ids, list) and any(
        isinstance(name, str) and name in RETIRED_PROVIDERS for name in provider_ids
    ):
        return True
    if any(isinstance(summary.get(field), str) and summary[field] in RETIRED_PROVIDERS
           for field in ("primary_provider_id", "candidate_provider_id", "previous_provider_id")):
        return True
    inputs = summary.get("inputs", [])
    return isinstance(inputs, list) and any(
        _has_non_current_source(item.get("source_summary"), depth + 1)
        for item in inputs if isinstance(item, dict)
    )


def allowed_current_quote(quote: CanonicalQuote) -> bool:
    if not rights.canonical_allowed(quote.source_summary, "display"):
        return False
    if _has_non_current_source(quote.source_summary):
        return False
    source_ids = rights._leaves(quote.source_summary) or set()
    if any(PROVIDERS.get(name) is not None and PROVIDERS[name].history_only for name in source_ids):
        return False
    candidate = quote.candidate_provider_id
    if candidate in RETIRED_PROVIDERS:
        return False
    if candidate in PROVIDERS and PROVIDERS[candidate].history_only:
        return False
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
