from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    background_tasks_enabled: bool = True

    database_url: str = Field(
        default="postgresql+psycopg://nerkhbaan:nerkhbaan@localhost:5432/nerkhbaan"
    )
    # Peak connections per process is roughly
    # (pool + overflow) * 2 because a sync and an async engine both exist.
    database_pool_size: int = 5
    database_async_pool_size: int = 5
    database_max_overflow: int = 3
    database_pool_timeout_seconds: int = 10

    jwt_secret_key: str = Field(default="change-me-in-production")

    @field_validator("jwt_secret_key")
    @classmethod
    def jwt_key_must_be_strong(cls, v: str) -> str:
        if v == "change-me-in-production" or len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be set to a random string of at least 32 characters")
        return v

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    jwt_issuer: str = "nerkhbaan-api"
    jwt_audience: str = "nerkhbaan-clients"

    auth_cookie_enabled: bool = True
    auth_cookie_name: str = "nerkhbaan_session"
    auth_refresh_cookie_name: str = "nerkhbaan_refresh"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "strict"
    auth_cookie_domain: str | None = None
    auth_refresh_days: int = 30
    auth_refresh_path: str = "/api/auth"
    auth_return_bearer_token: bool = True

    @field_validator("jwt_expire_minutes")
    @classmethod
    def jwt_expiry_must_be_bounded(cls, value: int) -> int:
        if not 5 <= value <= 60 * 24 * 7:
            raise ValueError("JWT_EXPIRE_MINUTES must be between 5 minutes and 7 days")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def jwt_algorithm_must_be_safe(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be HS256, HS384, or HS512")
        return value

    @model_validator(mode="after")
    def cookie_policy_must_be_safe(self) -> "Settings":
        if self.auth_cookie_enabled and self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true when SameSite is none")
        return self

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    public_frontend_origin: str = "http://localhost:5173"
    admin_frontend_origin: str = "http://localhost:5174"
    trusted_hosts: str = "localhost,127.0.0.1"
    max_request_body_bytes: int = 1_048_576
    request_id_header: str = "X-Request-ID"

    # Pricing provider configuration
    gold_api_base_url: str = "https://api.gold-api.com"
    goldapi_api_base_url: str = "https://www.goldapi.io/api"
    alanchand_api_base_url: str = "https://api.alanchand.com"
    alanchand_api_token: str | None = None
    nobitex_api_base_url: str = "https://api.nobitex.ir"
    wallex_api_base_url: str = "https://api.wallex.ir"
    tetherland_api_base_url: str = "https://api.tetherland.com"
    coinbase_api_base_url: str = "https://api.exchange.coinbase.com"
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"
    coincap_api_base_url: str = "https://api.coincap.io/v2"
    metals_dev_api_base_url: str = "https://api.metals.dev/v1"
    metals_dev_api_key: str | None = None
    goldapi_api_key: str | None = None
    servix_api_base_url: str = "https://servix.cc"
    servix_api_key: str | None = None
    persian_toolbox_api_base_url: str = "https://persiantoolbox.ir"
    tala_api_base_url: str = "https://api.tala.ir"
    tala_api_key: str | None = None
    tala_xau_usd_key: str = "ons"
    tala_xag_usd_key: str = "silver"
    tala_usdt_toman_key: str = "usdt_irt"
    tala_gold18_toman_key: str = "geram18k"
    tala_gold24_toman_key: str = "geram24k"
    tala_silver999_toman_key: str | None = None
    navasan_api_base_url: str = "http://api.navasan.tech"
    navasan_https_proxy_base_url: str | None = None
    navasan_api_key: str | None = None
    # Tripwire, not a feature: a model validator rejects startup if this is
    # ever turned on. Kept so an old .env fails loudly instead of silently
    # sending an API key over plaintext HTTP.
    navasan_allow_insecure_http: bool = False
    navasan_usd_item: str = "usd_sell"
    navasan_usdt_item: str = "usdt"
    navasan_btc_item: str = "btc"
    navasan_gold18_item: str = "18ayar"
    navasan_xau_item: str = "usd_xau"
    nerkh_io_api_base_url: str = "https://api.nerkh.io"
    nerkh_io_bearer_token: str | None = None
    nerkh_io_api_key: str | None = None
    nerkh_io_currency_unit: Literal["", "RIAL", "TOMAN", "USD", "USDT"] = ""
    nerkh_io_gold_unit: Literal["", "RIAL", "TOMAN", "USD", "USDT"] = ""
    nerkh_io_crypto_unit: Literal["", "RIAL", "TOMAN", "USD", "USDT"] = ""
    nerkh_io_usd_symbol: str = "USD"
    nerkh_io_usdt_symbol: str = "USDT"
    nerkh_io_btc_symbol: str = "BTC"
    nerkh_io_gold18_symbol: str = "GOLD18K"
    nerkh_io_gold24_symbol: str = "GOLD24K"
    nerkh_io_xau_symbol: str = "OUNCE"
    nerkh_io_xag_symbol: str = "OUNCE_SILVER"
    usdt_usd_safe_min: Decimal = Decimal("0.97")
    usdt_usd_safe_max: Decimal = Decimal("1.03")
    troy_ounce_grams: Decimal = Decimal("31.1034768")
    pricing_provider_connect_timeout_seconds: int = 3
    pricing_provider_request_timeout_seconds: int = 10
    pricing_provider_max_retries: int = 2
    pricing_provider_backoff_base_seconds: Decimal = Decimal("0.5")
    pricing_provider_aggregate_cache_seconds: int = 5
    pricing_provider_max_response_bytes: int = 262_144
    pricing_relay_base_url: str | None = None
    pricing_relay_shared_token: str | None = None
    pricing_worker_shared_secret: str | None = None
    pricing_provider_allowed_hosts: str = (
        "api.alanchand.com,api.gold-api.com,www.goldapi.io,api.metals.dev,"
        "api.exchange.coinbase.com,api.coingecko.com,api.coincap.io,"
        "api.nobitex.ir,api.wallex.ir,api.tetherland.com,"
        "servix.cc,persiantoolbox.ir,api.tala.ir,api.navasan.tech,api.nerkh.io"
    )
    pricing_require_provider_keys: bool = False
    pricing_lock_ttl_seconds: int = 45
    pricing_refresh_interval_seconds: int = 20
    pricing_refresh_jitter_seconds: int = 8
    pricing_derived_fallback_enabled: bool = True
    pricing_backfill_enabled: bool = True
    pricing_backfill_batch_size: int = 500
    pricing_backfill_max_jobs_per_cycle: int = 2
    pricing_persistence_flush_batch_size: int = 200
    pricing_persistence_flush_interval_seconds: int = 5
    pricing_persistence_stream_maxlen: int = 50_000
    pricing_event_stream_maxlen: int = 20_000
    # Redis keeps only a short volatility window; TimescaleDB owns real history.
    pricing_short_history_retention_hours: int = 6
    pricing_short_history_max_entries: int = 240
    raw_provider_payload_max_bytes: int = 16_384
    raw_provider_payload_retention_days: int = 30
    websocket_heartbeat_seconds: int = 20
    websocket_client_timeout_seconds: int = 60
    websocket_poll_fallback_seconds: int = 30
    websocket_max_connections_per_worker: int = 1000

    # Fallback exchange rate provider (USD -> IRR)
    
    # Redis configuration
    redis_url: str | None = None
    trusted_proxy_ips: str = "127.0.0.1,::1"

    # Networks allowed to scrape /metrics in addition to loopback/private.
    metrics_allowed_networks: str = "127.0.0.1/32,::1/128"

    migration_advisory_lock_id: int = 7_265_172_091
    migration_connect_timeout_seconds: int = 10
    migration_statement_timeout_seconds: int = 300

    admin_frontend_enabled: bool = True
    admin_cookie_name: str = "nerkhbaan_admin_session"
    admin_cookie_domain: str | None = None
    admin_session_minutes: int = 30
    admin_ip_allowlist: str = ""
    admin_private_network_only: bool = False
    admin_reauth_minutes: int = 10
    admin_login_failure_limit: int = 5
    admin_lockout_minutes: int = 30
    admin_bootstrap_username: str | None = None
    admin_bootstrap_email: str | None = None
    admin_bootstrap_password: str | None = None
    admin_bootstrap_full_name: str | None = None

    alert_worker_poll_seconds: int = 5
    alert_delivery_max_attempts: int = 6
    alert_delivery_backoff_base_seconds: int = 30
    alert_delivery_backoff_max_seconds: int = 3600

    # Remote reasoning providers use the standard chat-completions protocol.
    insight_api_key: str | None = None
    deepseek_api_key: str | None = None
    groq_api_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    ai_max_tokens: int = 600
    ai_provider_order: str = "groq,gemini,openrouter,deepseek"
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    openrouter_model: str | None = "openrouter/free"
    ai_allow_openrouter_free: bool = False
    deepseek_api_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ai_request_timeout_seconds: int = 25
    ai_max_retries: int = 2
    ai_user_daily_request_limit: int = 20
    ai_global_daily_request_limit: int = 500
    ai_deduplication_window_seconds: int = 15

    @field_validator("ai_max_tokens")
    @classmethod
    def reasoning_output_must_be_bounded(cls, value: int) -> int:
        if not 64 <= value <= 2048:
            raise ValueError("AI_MAX_TOKENS must be between 64 and 2048")
        return value

    @field_validator(
        "pricing_provider_connect_timeout_seconds",
        "pricing_provider_request_timeout_seconds",
        "pricing_provider_aggregate_cache_seconds",
        "pricing_provider_max_response_bytes",
        "ai_request_timeout_seconds",
        "ai_user_daily_request_limit",
        "ai_global_daily_request_limit",
        "ai_deduplication_window_seconds",
    )
    @classmethod
    def positive_bounds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Numeric setting must be positive")
        return value

    @field_validator("pricing_provider_max_retries", "ai_max_retries")
    @classmethod
    def retry_bounds(cls, value: int) -> int:
        if not 0 <= value <= 5:
            raise ValueError("Retry count must be between 0 and 5")
        return value

    @model_validator(mode="after")
    def pricing_numeric_policy_must_be_safe(self) -> "Settings":
        for name in ("usdt_usd_safe_min", "usdt_usd_safe_max", "troy_ounce_grams", "pricing_provider_backoff_base_seconds"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                try:
                    value = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError(f"{name.upper()} must be decimal") from exc
                setattr(self, name, value)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name.upper()} must be finite and positive")
        if self.usdt_usd_safe_min >= self.usdt_usd_safe_max:
            raise ValueError("USDT_USD_SAFE_MIN must be lower than USDT_USD_SAFE_MAX")
        if self.navasan_allow_insecure_http:
            raise ValueError("NAVASAN_ALLOW_INSECURE_HTTP is no longer supported; use an HTTPS proxy")
        return self

    @model_validator(mode="after")
    def provider_allowlist_must_cover_configured_bases(self) -> "Settings":
        """Keep operator-configured provider base URLs reachable.

        A proxy or mirror set through configuration is useless when the egress
        allowlist still only names the upstream vendor host, so fold the hosts
        of every configured base URL into the allowlist instead of failing the
        call later with an opaque provider_host_not_allowed.
        """
        hosts = {
            item.strip().lower()
            for item in self.pricing_provider_allowed_hosts.split(",")
            if item.strip()
        }
        for name in (
            "pricing_relay_base_url",
            "navasan_https_proxy_base_url",
            "alanchand_api_base_url",
            "goldapi_api_base_url",
            "gold_api_base_url",
            "metals_dev_api_base_url",
            "nobitex_api_base_url",
            "tetherland_api_base_url",
            "coinbase_api_base_url",
            "coingecko_api_base_url",
            "coincap_api_base_url",
            "wallex_api_base_url",
            "tala_api_base_url",
            "nerkh_io_api_base_url",
            "servix_api_base_url",
            "persian_toolbox_api_base_url",
        ):
            value = getattr(self, name, None)
            if not value:
                continue
            hostname = urlsplit(str(value)).hostname
            if hostname:
                hosts.add(hostname.strip().lower())
        self.pricing_provider_allowed_hosts = ",".join(sorted(hosts))
        if self.pricing_relay_base_url:
            parsed = urlsplit(self.pricing_relay_base_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("PRICING_RELAY_BASE_URL must be an HTTPS origin")
            if not self.pricing_relay_shared_token or len(self.pricing_relay_shared_token) < 32:
                raise ValueError("PRICING_RELAY_SHARED_TOKEN must contain at least 32 characters")
        return self

    @field_validator(
        "pricing_short_history_retention_hours",
        "pricing_short_history_max_entries",
        "pricing_lock_ttl_seconds",
    )
    @classmethod
    def cache_windows_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Cache window settings must be positive")
        return value

    push_allowed_hosts: str = (
        "fcm.googleapis.com,updates.push.services.mozilla.com,"
        "web.push.apple.com,notify.windows.com"
    )

    # Web push (VAPID). Generate a key pair once and keep it stable; rotating it
    # invalidates every stored browser subscription.
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:alerts@nerkhbaan.ir"

    # SMTP email delivery for price alerts. Leave unset to disable email sends.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Nerkhbaan Alerts <alerts@nerkhbaan.ir>"
    smtp_use_tls: bool = True

    telegram_alert_delivery_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None
    telegram_deeplink_enabled: bool = False
    telegram_deeplink_ttl_seconds: int = 600
    telegram_deeplink_signing_secret: str | None = None
    telegram_webhook_secret: str | None = None

    @field_validator("telegram_deeplink_ttl_seconds")
    @classmethod
    def telegram_deeplink_ttl_must_be_short(cls, value: int) -> int:
        if not 60 <= value <= 3600:
            raise ValueError("TELEGRAM_DEEPLINK_TTL_SECONDS must be between 60 and 3600")
        return value

    @field_validator("auth_refresh_days")
    @classmethod
    def refresh_lifetime_must_be_bounded(cls, value: int) -> int:
        if not 1 <= value <= 90:
            raise ValueError("AUTH_REFRESH_DAYS must be between 1 and 90")
        return value

    @field_validator("admin_session_minutes")
    @classmethod
    def admin_session_must_be_short(cls, value: int) -> int:
        if not 5 <= value <= 240:
            raise ValueError("ADMIN_SESSION_MINUTES must be between 5 and 240")
        return value

settings = Settings()
