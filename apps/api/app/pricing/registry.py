from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from .instruments import INSTRUMENTS
from .models import ProviderRole, RequestPurpose


@dataclass(frozen=True, slots=True)
class ProviderBudgetPolicy:
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    reserved_anomaly_requests: int
    reserved_fallback_requests: int
    minimum_interval_seconds: int
    cooldown_after_429_seconds: int
    estimated_request_cost: Decimal


@dataclass(frozen=True, slots=True)
class InstrumentBudgetPolicy:
    requests_per_minute: int
    requests_per_hour: int
    importance: int
    maximum_verification_depth: int


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    instrument_id: str
    role: ProviderRole
    priority: int
    trust_score: Decimal
    url: str
    parser_id: str
    parser_version: str
    operational_ttl_seconds: int
    budget: ProviderBudgetPolicy
    method: str = "GET"
    enabled: bool = True
    api_key_setting: str | None = None
    api_key_header: str | None = None
    api_key_query_parameter: str | None = None
    static_headers: tuple[tuple[str, str], ...] = ()
    maximum_payload_bytes: int = 262_144
    history_url: str | None = None
    history_parser_id: str | None = None

    def configured(self, settings: object) -> bool:
        return self.api_key_setting is None or bool(
            getattr(settings, self.api_key_setting, None)
        )


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


def _decimal_env(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
    except InvalidOperation:
        return Decimal(default)
    return value if value.is_finite() and value >= 0 else Decimal(default)


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _budget(provider_id: str, *, rpm: int, rph: int, rpd: int, interval: int) -> ProviderBudgetPolicy:
    prefix = f"PRICING_PROVIDER_{provider_id.upper()}"
    day_limit = _int_env(f"{prefix}_REQUESTS_PER_DAY", rpd, 1)
    anomaly_reserved = _int_env(
        f"{prefix}_RESERVED_ANOMALY_REQUESTS", max(1, min(20, day_limit // 10)), 0
    )
    fallback_reserved = _int_env(
        f"{prefix}_RESERVED_FALLBACK_REQUESTS", max(1, min(20, day_limit // 10)), 0
    )
    if anomaly_reserved + fallback_reserved >= day_limit:
        anomaly_reserved = max(0, day_limit // 10)
        fallback_reserved = max(0, day_limit // 10)
    return ProviderBudgetPolicy(
        requests_per_minute=_int_env(f"{prefix}_REQUESTS_PER_MINUTE", rpm, 1),
        requests_per_hour=_int_env(f"{prefix}_REQUESTS_PER_HOUR", rph, 1),
        requests_per_day=day_limit,
        reserved_anomaly_requests=anomaly_reserved,
        reserved_fallback_requests=fallback_reserved,
        minimum_interval_seconds=_int_env(f"{prefix}_MINIMUM_INTERVAL_SECONDS", interval, 1),
        cooldown_after_429_seconds=_int_env(f"{prefix}_COOLDOWN_AFTER_429_SECONDS", 300, 1),
        estimated_request_cost=_decimal_env(f"{prefix}_ESTIMATED_REQUEST_COST", "1"),
    )


def _provider(
    provider_id: str,
    display_name: str,
    instrument_id: str,
    role: ProviderRole,
    priority: int,
    trust: str,
    url: str,
    parser_id: str,
    parser_version: str,
    ttl: int,
    *,
    rpm: int = 10,
    rph: int = 120,
    rpd: int = 1000,
    interval: int = 20,
    api_key_setting: str | None = None,
    api_key_header: str | None = None,
    api_key_query_parameter: str | None = None,
    headers: tuple[tuple[str, str], ...] = (),
    history_url: str | None = None,
    history_parser_id: str | None = None,
) -> ProviderDefinition:
    enabled = _bool_env(f"PRICING_PROVIDER_{provider_id.upper()}_ENABLED", True)
    return ProviderDefinition(
        provider_id=provider_id,
        display_name=display_name,
        instrument_id=instrument_id,
        role=role,
        priority=priority,
        trust_score=Decimal(trust),
        url=url,
        parser_id=parser_id,
        parser_version=parser_version,
        operational_ttl_seconds=ttl,
        budget=_budget(provider_id, rpm=rpm, rph=rph, rpd=rpd, interval=interval),
        enabled=enabled,
        api_key_setting=api_key_setting,
        api_key_header=api_key_header,
        api_key_query_parameter=api_key_query_parameter,
        static_headers=headers,
        history_url=history_url,
        history_parser_id=history_parser_id,
    )


_NOBITEX_HEADERS = (("User-Agent", "Nerkhbaan-Pricing/2"),)

_PROVIDERS = (
    _provider(
        "alanchand_gold18", "Alanchand Gold 18K", "GOLD_18K_TOMAN_GRAM",
        ProviderRole.PRIMARY, 1, "0.86", "https://api.alanchand.com/v1/markets/gold",
        "alanchand_gold18_v1", "alanchand-gold18/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="alanchand_api_token", api_key_header="Authorization",
    ),
    _provider(
        "goldapi_xau", "GoldAPI XAU", "XAU_USD_OZ", ProviderRole.PRIMARY, 1,
        "0.94", "https://www.goldapi.io/api/XAU/USD", "goldapi_xau_v1",
        "goldapi/1.0.0", 7200, rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="goldapi_api_key", api_key_header="x-access-token",
    ),
    _provider(
        "gold_api_free_xau", "Gold API Free XAU", "XAU_USD_OZ", ProviderRole.VERIFIER, 2,
        "0.80", "https://api.gold-api.com/price/XAU", "gold_api_free_xau_v1",
        "gold-api-free/1.0.0", 3600, rpm=2, rph=30, rpd=300, interval=3600,
    ),
    _provider(
        "metals_dev_gold", "Metals.dev Gold", "XAU_USD_OZ", ProviderRole.FALLBACK, 3,
        "0.90", "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
        "metals_dev_gold_v1", "metals-dev/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="metals_dev_api_key", api_key_query_parameter="api_key",
    ),
    _provider(
        "goldapi_xag", "GoldAPI XAG", "XAG_USD_OZ", ProviderRole.PRIMARY, 1,
        "0.94", "https://www.goldapi.io/api/XAG/USD", "goldapi_xag_v1",
        "goldapi/1.0.0", 7200, rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="goldapi_api_key", api_key_header="x-access-token",
    ),
    _provider(
        "gold_api_free_xag", "Gold API Free XAG", "XAG_USD_OZ", ProviderRole.VERIFIER, 2,
        "0.80", "https://api.gold-api.com/price/XAG", "gold_api_free_xag_v1",
        "gold-api-free/1.0.0", 3600, rpm=2, rph=30, rpd=300, interval=3600,
    ),
    _provider(
        "metals_dev_silver", "Metals.dev Silver", "XAG_USD_OZ", ProviderRole.FALLBACK, 3,
        "0.90", "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
        "metals_dev_silver_v1", "metals-dev/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="metals_dev_api_key", api_key_query_parameter="api_key",
    ),
    _provider(
        "nobitex_stats_usdt", "Nobitex USDT Stats", "USDT_TOMAN", ProviderRole.PRIMARY, 1,
        "0.93", "https://apiv2.nobitex.ir/market/stats", "nobitex_stats_usdt_rls_v1",
        "nobitex-stats/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        headers=_NOBITEX_HEADERS,
        history_url="https://api.nobitex.ir/market/udf/history",
        history_parser_id="nobitex_udf_usdtirt_v1",
    ),
    _provider(
        "nobitex_orderbook_usdt", "Nobitex USDT Order Book", "USDT_TOMAN",
        ProviderRole.VERIFIER, 2, "0.91", "https://apiv2.nobitex.ir/v3/orderbook/all",
        "nobitex_orderbook_usdtirt_v1", "nobitex-orderbook/1.0.0", 20,
        rpm=12, rph=360, rpd=5000, interval=20, headers=_NOBITEX_HEADERS,
    ),
    _provider(
        "tetherland_usdt", "Tetherland USDT", "USDT_TOMAN", ProviderRole.FALLBACK, 3,
        "0.84", "https://api.tetherland.com/currencies", "tetherland_usdt_v1",
        "tetherland-currency/1.0.0", 60, rpm=6, rph=120, rpd=1500, interval=60,
    ),
    _provider(
        "coincap_usdt", "CoinCap Tether", "USDT_USD", ProviderRole.PRIMARY, 1,
        "0.88", "https://api.coincap.io/v2/assets/tether", "coincap_tether_v1",
        "coincap/1.0.0", 60, rpm=10, rph=300, rpd=3000, interval=60,
    ),
    _provider(
        "nobitex_stats_btc", "Nobitex BTC Stats", "BTC_TOMAN", ProviderRole.PRIMARY, 1,
        "0.93", "https://apiv2.nobitex.ir/market/stats", "nobitex_stats_btc_rls_v1",
        "nobitex-stats/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        headers=_NOBITEX_HEADERS,
        history_url="https://api.nobitex.ir/market/udf/history",
        history_parser_id="nobitex_udf_btcirt_v1",
    ),
    _provider(
        "nobitex_orderbook_btc", "Nobitex BTC Order Book", "BTC_TOMAN",
        ProviderRole.VERIFIER, 2, "0.91", "https://apiv2.nobitex.ir/v3/orderbook/all",
        "nobitex_orderbook_btcirt_v1", "nobitex-orderbook/1.0.0", 20,
        rpm=12, rph=360, rpd=5000, interval=20, headers=_NOBITEX_HEADERS,
    ),
    _provider(
        "tetherland_btc", "Tetherland BTC", "BTC_TOMAN", ProviderRole.FALLBACK, 3,
        "0.84", "https://api.tetherland.com/currencies", "tetherland_btc_v1",
        "tetherland-currency/1.0.0", 60, rpm=6, rph=120, rpd=1500, interval=60,
    ),
    _provider(
        "coincap_btc", "CoinCap Bitcoin", "BTC_USD", ProviderRole.PRIMARY, 1,
        "0.90", "https://api.coincap.io/v2/assets/bitcoin", "coincap_bitcoin_v1",
        "coincap/1.0.0", 30, rpm=12, rph=360, rpd=4000, interval=30,
    ),
)

PROVIDERS = MappingProxyType({provider.provider_id: provider for provider in _PROVIDERS})
PROVIDERS_BY_INSTRUMENT = MappingProxyType(
    {
        instrument_id: tuple(
            sorted(
                (p for p in _PROVIDERS if p.instrument_id == instrument_id),
                key=lambda p: (p.priority, p.provider_id),
            )
        )
        for instrument_id in INSTRUMENTS
    }
)

INSTRUMENT_BUDGETS = MappingProxyType(
    {
        instrument_id: InstrumentBudgetPolicy(
            requests_per_minute=_int_env(
                f"PRICING_INSTRUMENT_{instrument_id}_REQUESTS_PER_MINUTE",
                20 if instrument.importance >= 9 else 8,
                1,
            ),
            requests_per_hour=_int_env(
                f"PRICING_INSTRUMENT_{instrument_id}_REQUESTS_PER_HOUR",
                500 if instrument.importance >= 9 else 120,
                1,
            ),
            importance=instrument.importance,
            maximum_verification_depth=instrument.maximum_verification_depth,
        )
        for instrument_id, instrument in INSTRUMENTS.items()
    }
)


def providers_for(
    instrument_id: str,
    *roles: ProviderRole,
) -> tuple[ProviderDefinition, ...]:
    providers = PROVIDERS_BY_INSTRUMENT.get(instrument_id.upper(), ())
    if not roles:
        return providers
    allowed = set(roles)
    return tuple(provider for provider in providers if provider.role in allowed)


def purpose_role(purpose: RequestPurpose) -> tuple[ProviderRole, ...]:
    if purpose is RequestPurpose.NORMAL:
        return (ProviderRole.PRIMARY,)
    if purpose is RequestPurpose.ANOMALY:
        return (ProviderRole.VERIFIER, ProviderRole.COMPARE)
    if purpose is RequestPurpose.FALLBACK:
        return (ProviderRole.FALLBACK, ProviderRole.VERIFIER)
    return (ProviderRole.FALLBACK,)
