from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True

    database_url: str = Field(
        default="postgresql+psycopg://nerkhban:nerkhban@localhost:5432/nerkhban"
    )

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

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


settings = Settings()
