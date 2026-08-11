from __future__ import annotations

import os
from urllib.parse import urljoin
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from .instruments import INSTRUMENTS
from .models import PriceSemantic, ProviderRole, RequestPurpose, SourceSemantic


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
    source_semantic: SourceSemantic = SourceSemantic.REFERENCE_RATE
    source_family: str = "reference"
    venue: str = "reference"
    selected_price_semantic: PriceSemantic = PriceSemantic.REFERENCE
    route_id: str = "rest"
    requires_https: bool = False
    credential_placement: str = "none"
    unit_source: str | None = None
    symbol_or_pair: str | None = None
    selected_price_semantic_contract: str | None = None
    independence_group: str | None = None

    def configured(self, settings: object) -> bool:
        if self.provider_id.startswith("navasan_"):
            proxy = getattr(settings, "navasan_https_proxy_base_url", None)
            if not proxy:
                return False
        if self.provider_id.startswith("nerkh_io_"):
            category = self.unit_source or ""
            if category and not getattr(settings, category, None):
                return False
            if getattr(settings, "nerkh_io_bearer_token", None) or getattr(settings, "nerkh_io_api_key", None):
                return True
        return self.api_key_setting is None or bool(getattr(settings, self.api_key_setting, None))


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


def _setting_url(base_setting: str, path: str) -> str:
    defaults = {
        "alanchand_api_base_url": "https://api.alanchand.com",
        "goldapi_api_base_url": "https://www.goldapi.io/api",
        "gold_api_base_url": "https://api.gold-api.com",
        "metals_dev_api_base_url": "https://api.metals.dev/v1",
        "nobitex_api_base_url": "https://api.nobitex.ir",
        "tetherland_api_base_url": "https://api.tetherland.com",
        "coinbase_api_base_url": "https://api.exchange.coinbase.com",
        "coingecko_api_base_url": "https://api.coingecko.com/api/v3",
        "coincap_api_base_url": "https://api.coincap.io/v2",
        "wallex_api_base_url": "https://api.wallex.ir",
        "tala_api_base_url": "https://api.tala.ir",
        "navasan_api_base_url": "http://api.navasan.tech",
        "navasan_https_proxy_base_url": "",
        "nerkh_io_api_base_url": "https://api.nerkh.io",
        "servix_api_base_url": "https://servix.cc",
    }
    base = os.getenv(base_setting.upper(), defaults[base_setting])
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


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
    source_semantic: SourceSemantic = SourceSemantic.REFERENCE_RATE,
    source_family: str | None = None,
    venue: str | None = None,
    selected_price_semantic: PriceSemantic = PriceSemantic.REFERENCE,
    route_id: str | None = None,
    enabled_default: bool = True,
    requires_https: bool = False,
    credential_placement: str = "none",
    unit_source: str | None = None,
    symbol_or_pair: str | None = None,
    selected_price_semantic_contract: str | None = None,
    independence_group: str | None = None,
) -> ProviderDefinition:
    enabled = _bool_env(f"PRICING_PROVIDER_{provider_id.upper()}_ENABLED", enabled_default)
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
        source_semantic=source_semantic,
        source_family=source_family or provider_id,
        venue=venue or source_family or provider_id,
        selected_price_semantic=selected_price_semantic,
        route_id=route_id or f"{provider_id}_rest",
        requires_https=requires_https,
        credential_placement=credential_placement,
        unit_source=unit_source,
        symbol_or_pair=symbol_or_pair,
        selected_price_semantic_contract=selected_price_semantic_contract,
        independence_group=independence_group,
    )


_NOBITEX_HEADERS = (("User-Agent", "Nerkhbaan-Pricing/2"),)

_PROVIDERS = (
    _provider(
        "alanchand_gold18", "Alanchand Gold 18K", "GOLD_18K_TOMAN_GRAM",
        ProviderRole.FALLBACK, 20, "0.80", _setting_url("alanchand_api_base_url", "/v1/markets/gold"),
        "alanchand_gold18_v1", "alanchand-gold18/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="alanchand_api_token", api_key_header="Authorization",
        source_semantic=SourceSemantic.PHYSICAL_MARKET_QUOTE,
        source_family="alanchand", venue="alanchand",
        selected_price_semantic=PriceSemantic.PROVIDER_SELECTED,
    ),
    _provider(
        "goldapi_xau", "GoldAPI XAU", "XAU_USD_OZ", ProviderRole.PRIMARY, 1,
        "0.94", _setting_url("goldapi_api_base_url", "/XAU/USD"), "goldapi_xau_v1",
        "goldapi/1.0.0", 7200, rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="goldapi_api_key", api_key_header="x-access-token",
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="goldapi", venue="goldapi",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "gold_api_free_xau", "Gold API Free XAU", "XAU_USD_OZ", ProviderRole.VERIFIER, 2,
        "0.80", _setting_url("gold_api_base_url", "/price/XAU"), "gold_api_free_xau_v1",
        "gold-api-free/1.0.0", 3600, rpm=2, rph=30, rpd=300, interval=3600,
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="gold_api_free", venue="gold_api_free",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "metals_dev_gold", "Metals.dev Gold", "XAU_USD_OZ", ProviderRole.FALLBACK, 3,
        "0.90", _setting_url("metals_dev_api_base_url", "/latest?currency=USD&unit=toz"),
        "metals_dev_gold_v1", "metals-dev/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="metals_dev_api_key", api_key_query_parameter="api_key",
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="metals_dev", venue="metals_dev",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "goldapi_xag", "GoldAPI XAG", "XAG_USD_OZ", ProviderRole.PRIMARY, 1,
        "0.94", _setting_url("goldapi_api_base_url", "/XAG/USD"), "goldapi_xag_v1",
        "goldapi/1.0.0", 7200, rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="goldapi_api_key", api_key_header="x-access-token",
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="goldapi", venue="goldapi",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "gold_api_free_xag", "Gold API Free XAG", "XAG_USD_OZ", ProviderRole.VERIFIER, 2,
        "0.80", _setting_url("gold_api_base_url", "/price/XAG"), "gold_api_free_xag_v1",
        "gold-api-free/1.0.0", 3600, rpm=2, rph=30, rpd=300, interval=3600,
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="gold_api_free", venue="gold_api_free",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "metals_dev_silver", "Metals.dev Silver", "XAG_USD_OZ", ProviderRole.FALLBACK, 3,
        "0.90", _setting_url("metals_dev_api_base_url", "/latest?currency=USD&unit=toz"),
        "metals_dev_silver_v1", "metals-dev/1.0.0", 7200,
        rpm=2, rph=20, rpd=200, interval=7200,
        api_key_setting="metals_dev_api_key", api_key_query_parameter="api_key",
        source_semantic=SourceSemantic.REFERENCE_RATE,
        source_family="metals_dev", venue="metals_dev",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "nobitex_stats_usdt", "Nobitex USDT Stats", "USDT_TOMAN", ProviderRole.PRIMARY, 1,
        "0.93", _setting_url("nobitex_api_base_url", "/market/stats"), "nobitex_stats_usdt_rls_v1",
        "nobitex-stats/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        headers=_NOBITEX_HEADERS,
        history_url="https://api.nobitex.ir/market/udf/history",
        history_parser_id="nobitex_udf_usdtirt_v1",
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="nobitex", venue="nobitex",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "nobitex_orderbook_usdt", "Nobitex USDT Order Book", "USDT_TOMAN",
        ProviderRole.VERIFIER, 2, "0.91", _setting_url("nobitex_api_base_url", "/v3/orderbook/all"),
        "nobitex_orderbook_usdtirt_v1", "nobitex-orderbook/1.0.0", 20,
        rpm=12, rph=360, rpd=5000, interval=20, headers=_NOBITEX_HEADERS,
        source_semantic=SourceSemantic.EXCHANGE_ORDERBOOK,
        source_family="nobitex", venue="nobitex",
        selected_price_semantic=PriceSemantic.MIDPOINT,
    ),
    _provider(
        "tetherland_usdt", "Tetherland USDT", "USDT_TOMAN", ProviderRole.FALLBACK, 3,
        "0.84", _setting_url("tetherland_api_base_url", "/currencies"), "tetherland_usdt_v1",
        "tetherland-currency/1.0.0", 60, rpm=6, rph=120, rpd=1500, interval=60,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="tetherland", venue="tetherland",
        selected_price_semantic=PriceSemantic.PROVIDER_SELECTED,
    ),
    _provider(
        "coinbase_usdt_usd", "Coinbase USDT-USD", "USDT_USD", ProviderRole.PRIMARY, 1,
        "0.93", _setting_url("coinbase_api_base_url", "/products/USDT-USD/ticker"), "coinbase_usdt_usd_v1",
        "coinbase-ticker/1.0.0", 30, rpm=12, rph=360, rpd=4000, interval=30,
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="coinbase", venue="coinbase",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "coingecko_usdt", "CoinGecko Tether", "USDT_USD", ProviderRole.FALLBACK, 2,
        "0.82", _setting_url("coingecko_api_base_url", "/simple/price?ids=tether&vs_currencies=usd&include_last_updated_at=true"), "coingecko_tether_usd_v1",
        "coingecko-simple-price/1.0.0", 120, rpm=10, rph=200, rpd=2000, interval=60,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="coingecko", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "coincap_usdt", "CoinCap Tether", "USDT_USD", ProviderRole.FALLBACK, 99,
        "0.50", _setting_url("coincap_api_base_url", "/assets/tether"), "coincap_tether_v1",
        "coincap/1.0.0", 60, rpm=10, rph=300, rpd=3000, interval=60,
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="coincap", venue="coincap",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "nobitex_stats_btc", "Nobitex BTC Stats", "BTC_TOMAN", ProviderRole.PRIMARY, 1,
        "0.93", _setting_url("nobitex_api_base_url", "/market/stats"), "nobitex_stats_btc_rls_v1",
        "nobitex-stats/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        headers=_NOBITEX_HEADERS,
        history_url="https://api.nobitex.ir/market/udf/history",
        history_parser_id="nobitex_udf_btcirt_v1",
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="nobitex", venue="nobitex",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "nobitex_orderbook_btc", "Nobitex BTC Order Book", "BTC_TOMAN",
        ProviderRole.VERIFIER, 2, "0.91", _setting_url("nobitex_api_base_url", "/v3/orderbook/all"),
        "nobitex_orderbook_btcirt_v1", "nobitex-orderbook/1.0.0", 20,
        rpm=12, rph=360, rpd=5000, interval=20, headers=_NOBITEX_HEADERS,
        source_semantic=SourceSemantic.EXCHANGE_ORDERBOOK,
        source_family="nobitex", venue="nobitex",
        selected_price_semantic=PriceSemantic.MIDPOINT,
    ),
    _provider(
        "tetherland_btc", "Tetherland BTC", "BTC_TOMAN", ProviderRole.FALLBACK, 3,
        "0.84", _setting_url("tetherland_api_base_url", "/currencies"), "tetherland_btc_v1",
        "tetherland-currency/1.0.0", 60, rpm=6, rph=120, rpd=1500, interval=60,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="tetherland", venue="tetherland",
        selected_price_semantic=PriceSemantic.PROVIDER_SELECTED,
    ),
    _provider(
        "coinbase_btc_usd", "Coinbase BTC-USD", "BTC_USD", ProviderRole.PRIMARY, 1,
        "0.94", _setting_url("coinbase_api_base_url", "/products/BTC-USD/ticker"), "coinbase_btc_usd_v1",
        "coinbase-ticker/1.0.0", 30, rpm=12, rph=360, rpd=4000, interval=30,
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="coinbase", venue="coinbase",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "coingecko_btc", "CoinGecko Bitcoin", "BTC_USD", ProviderRole.FALLBACK, 2,
        "0.82", _setting_url("coingecko_api_base_url", "/simple/price?ids=bitcoin&vs_currencies=usd&include_last_updated_at=true"), "coingecko_bitcoin_usd_v1",
        "coingecko-simple-price/1.0.0", 120, rpm=10, rph=200, rpd=2000, interval=60,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="coingecko", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
    ),
    _provider(
        "coincap_btc", "CoinCap Bitcoin", "BTC_USD", ProviderRole.FALLBACK, 99,
        "0.50", _setting_url("coincap_api_base_url", "/assets/bitcoin"), "coincap_bitcoin_v1",
        "coincap/1.0.0", 30, rpm=12, rph=360, rpd=4000, interval=30,
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="coincap", venue="coincap",
        selected_price_semantic=PriceSemantic.LAST,
    ),
    _provider(
        "wallex_usdt_toman", "Wallex USDT-Toman", "USDT_TOMAN", ProviderRole.FALLBACK, 4,
        "0.90", _setting_url("wallex_api_base_url", "/v1/markets"), "wallex_usdt_toman_v1",
        "wallex-market/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="wallex", venue="wallex",
        selected_price_semantic=PriceSemantic.LAST,
        symbol_or_pair="USDTTMN",
    ),
    _provider(
        "wallex_btc_toman", "Wallex BTC-Toman", "BTC_TOMAN", ProviderRole.FALLBACK, 4,
        "0.90", _setting_url("wallex_api_base_url", "/v1/markets"), "wallex_btc_toman_v1",
        "wallex-market/1.0.0", 20, rpm=12, rph=360, rpd=5000, interval=20,
        source_semantic=SourceSemantic.EXCHANGE_TRADE,
        source_family="wallex", venue="wallex",
        selected_price_semantic=PriceSemantic.LAST,
        symbol_or_pair="BTCTMN",
    ),
    _provider(
        "tala_gold24_toman", "TALA 24K Gold", "GOLD_24K_TOMAN_GRAM", ProviderRole.FALLBACK, 10,
        "0.78", _setting_url("tala_api_base_url", "/v1/rates"), "tala_gold24_toman_v1",
        "tala-rates/1.0.0", 60, rpm=4, rph=80, rpd=1000, interval=60,
        api_key_setting="tala_api_key", api_key_header="x-api-key",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="tala", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        credential_placement="header",
        symbol_or_pair=_env("TALA_GOLD24_TOMAN_KEY", "geram24k"),
    ),
    _provider(
        "tala_gold18_toman", "TALA 18K Gold", "GOLD_18K_TOMAN_GRAM", ProviderRole.FALLBACK, 10,
        "0.78", _setting_url("tala_api_base_url", "/v1/rates"), "tala_gold18_toman_v1",
        "tala-rates/1.0.0", 60, rpm=4, rph=80, rpd=1000, interval=60,
        api_key_setting="tala_api_key", api_key_header="x-api-key",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="tala", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        credential_placement="header",
        symbol_or_pair=_env("TALA_GOLD18_TOMAN_KEY", "geram18k"),
    ),
    _provider(
        "tala_usdt_toman", "TALA USDT-Toman", "USDT_TOMAN", ProviderRole.FALLBACK, 10,
        "0.78", _setting_url("tala_api_base_url", "/v1/rates"), "tala_usdt_toman_v1",
        "tala-rates/1.0.0", 60, rpm=4, rph=80, rpd=1000, interval=60,
        api_key_setting="tala_api_key", api_key_header="x-api-key",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="tala", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        credential_placement="header",
        symbol_or_pair=_env("TALA_USDT_TOMAN_KEY", "usdt_irt"),
    ),
    _provider(
        "navasan_usdt", "Navasan USDT", "USDT_TOMAN", ProviderRole.FALLBACK, 20,
        "0.72", _setting_url("navasan_https_proxy_base_url" if os.getenv("NAVASAN_HTTPS_PROXY_BASE_URL") else "navasan_api_base_url", "/latest/"), "navasan_usdt_v1",
        "navasan-latest/1.0.0", 120, rpm=2, rph=60, rpd=500, interval=120,
        api_key_setting="navasan_api_key", api_key_query_parameter="api_key",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="navasan", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        requires_https=True,
        credential_placement="query",
        symbol_or_pair=_env("NAVASAN_USDT_ITEM", "usdt"),
    ),
    _provider(
        "nerkh_io_gold24", "Nerkh.io Gold 24K", "GOLD_24K_TOMAN_GRAM", ProviderRole.FALLBACK, 30,
        "0.74", _setting_url("nerkh_io_api_base_url", "/v2/prices/json/lite/gold"), "nerkh_io_gold24_v1",
        "nerkh-io-lite/1.0.0", 120, rpm=4, rph=80, rpd=1000, interval=120,
        api_key_setting="nerkh_io_bearer_token", api_key_header="Authorization",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="nerkh_io", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        credential_placement="header",
        unit_source="nerkh_io_gold_unit",
        symbol_or_pair=_env("NERKH_IO_GOLD24_SYMBOL", "GOLD24K"),
    ),
    _provider(
        "servix_btc_usd", "Servix BTC-USD", "BTC_USD", ProviderRole.FALLBACK, 30,
        "0.74", _setting_url("servix_api_base_url", "/api/v1/assets"), "servix_btc_usd_v1",
        "servix-assets/1.0.0", 120, rpm=4, rph=80, rpd=1000, interval=120,
        api_key_setting="servix_api_key", api_key_header="X-API-Key",
        enabled_default=False,
        source_semantic=SourceSemantic.AGGREGATOR,
        source_family="servix", venue="opaque_aggregator",
        selected_price_semantic=PriceSemantic.REFERENCE,
        credential_placement="header",
        symbol_or_pair="BTC_USD",
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
