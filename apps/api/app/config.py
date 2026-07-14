from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    database_url: str = Field(
        default="postgresql+psycopg://nerkhbaan:nerkhbaan@localhost:5432/nerkhbaan"
    )

    jwt_secret_key: str = Field(default="change-me-in-production")

    @field_validator("jwt_secret_key")
    @classmethod
    def jwt_key_must_be_strong(cls, v: str) -> str:
        if v == "change-me-in-production" or len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be set to a random string of at least 32 characters")
        return v

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    jwt_issuer: str = "nerkhbaan-api"
    jwt_audience: str = "nerkhbaan-clients"

    auth_cookie_enabled: bool = False
    auth_cookie_name: str = "nerkhbaan_session"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "strict"

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

    # Pricing provider configuration
    gold_api_base_url: str = "https://api.gold-api.com"
    alanchand_api_base_url: str = "https://api.alanchand.com"
    alanchand_api_token: str | None = None
    tgju_api_base_url: str = "https://api.tgju.org/v1"
    nobitex_api_base_url: str = "https://api.nobitex.ir"
    tetherland_api_base_url: str = "https://api.tetherland.com"
    bonbast_api_base_url: str = "https://www.bonbast.com"
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"
    coincap_api_base_url: str = "https://api.coincap.io/v2"
    metals_dev_api_base_url: str = "https://api.metals.dev/v1"
    metals_dev_api_key: str | None = None
    goldapi_api_key: str | None = None
    exchangerate_api_base_url: str = "https://v6.exchangerate-api.com/v6"
    exchangerate_api_key: str | None = None
    frankfurter_api_base_url: str = "https://api.frankfurter.app"
    price_cache_file: str = "price_cache.json"
    pricing_require_provider_keys: bool = False

    # Fallback exchange rate provider (USD -> IRR)
    exchange_rate_api_base_url: str = "https://open.er-api.com/v6/latest"
    
    # Redis configuration
    redis_url: str | None = None
    trusted_proxy_ips: str = "127.0.0.1,::1"

    # Remote reasoning providers use the standard chat-completions protocol.
    insight_api_base_url: str = "https://api.deepseek.com"
    insight_api_key: str | None = None
    insight_model: str = "deepseek-chat"
    deepseek_api_key: str | None = None
    groq_api_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    ai_model: str | None = None
    ai_max_tokens: int = 600

    @field_validator("ai_max_tokens")
    @classmethod
    def reasoning_output_must_be_bounded(cls, value: int) -> int:
        if not 64 <= value <= 2048:
            raise ValueError("AI_MAX_TOKENS must be between 64 and 2048")
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

settings = Settings()
