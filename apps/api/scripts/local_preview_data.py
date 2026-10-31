"""Synthetic data for the explicitly marked, loopback-only local preview."""
from datetime import UTC, datetime, timedelta
from math import sin

REVISION = "local-preview-synthetic-v1"
ASSETS = {
    "gold": ("طلا", "Gold", 2000, 1000000),
    "silver": ("نقره", "Silver", 25, 50000),
    "usdt": ("تتر", "Tether", 1, 50000),
    "btc": ("بیت‌کوین", "Bitcoin", 30000, 1500000000),
}
RANGES = {"1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000, "1y": 31536000}


def history(asset, timeframe="30d"):
    if asset not in ASSETS or timeframe not in RANGES:
        raise ValueError("Unknown preview asset or timeframe")
    now = datetime.now(UTC)
    _, _, usd, toman = ASSETS[asset]
    points = [{"timestamp": (now - timedelta(seconds=RANGES[timeframe] * (59-i) / 59)).isoformat(),
               "value_usd": round(usd*(1 + sin(i/6)*0.025), 4),
               "value_toman": round(toman*(1 + sin(i/6)*0.025), 2)} for i in range(60)]
    return {"asset": asset, "rights_revision": REVISION, "timeframe": timeframe, "points": points,
            "status": "synthetic_preview", "attributions": []}


def prices():
    from app.pricing.instruments import instrument_for_legacy_asset
    now = datetime.now(UTC).isoformat()
    assets = []
    for asset, (fa, en, usd, toman) in ASSETS.items():
        row = {"asset": asset, "label_fa": fa, "label_en": en, "price_usd": usd,
               "price_toman": toman, "change_percent": 0, "trend": "stable",
               "history": history(asset, "24h")["points"], "source_usd": "local_preview",
               "source_toman": "local_preview", "usd_status": "preview", "toman_status": "preview",
               "chart_error": False, "chart_error_message": {"fa": "", "en": ""}}
        for currency in ["usd", "toman"]:
            instrument = instrument_for_legacy_asset(asset, currency)
            row["instrument_id_"+currency] = instrument.instrument_id
            row["unit_"+currency] = {"instrument_id": instrument.instrument_id,
                "quote_currency": instrument.quote_currency.value, "weight_unit": instrument.weight_unit.value,
                "purity": float(instrument.purity) if instrument.purity is not None else None,
                "market": instrument.market.value, "display_decimals": instrument.display_decimals}
            row[currency+"_observed_at"] = now
            row[currency+"_source_summary"] = {"preview": True, "label": "نمونهٔ محلی؛ قیمت واقعی نیست"}
        assets.append(row)
    return {"refreshed_at": now, "rights_revision": REVISION,
            "source": {"usd": "synthetic local preview", "toman": "synthetic local preview"}, "assets": assets}


def references(timeframe="30d"):
    from app.pricing.reference_rates import reference_definitions
    if timeframe not in RANGES:
        raise ValueError("Unknown timeframe")
    rows = []
    for definition in reference_definitions():
        current = {**definition, "status": "unavailable_reference", "price": None,
                   "freshness_limit_seconds": 600, "maximum_reference_age_seconds": 86400,
                   "unavailable_reason": "local_preview_no_external_sources"}
        rows.append({**definition, "status": "unavailable_reference", "current": current,
                     "history": [], "history_status": "partial",
                     "history_time_info": {"timestamp_precision": "day", "source_timezone": "Asia/Tehran",
                                           "source_calendar": "jalali"}})
    return {"rights_revision": REVISION, "checked_at": datetime.now(UTC).isoformat(),
            "timeframe": timeframe, "references": rows, "attributions": [], "errors": []}
