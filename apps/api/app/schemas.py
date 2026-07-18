from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserSignin(BaseModel):
    username_or_email: str
    password: str = Field(min_length=8, max_length=128)


class UserResponse(UserBase):
    id: int
    is_active: bool
    must_change_password: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)


class SessionResponse(BaseModel):
    id: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool = False


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PricePoint(BaseModel):
    timestamp: str
    value_usd: float | None
    value_toman: float | None
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


class PriceHistoryResponse(BaseModel):
    asset: str
    points: list[PricePoint]
    timeframe: str | None = None
    status: str = "complete"


class AssetPrice(BaseModel):
    asset: str
    label_fa: str
    label_en: str
    price_usd: float | None
    price_toman: float | None
    change_percent: float | None
    trend: str
    history: list[PricePoint]
    source_usd: str
    source_toman: str
    usd_status: str
    toman_status: str
    stale_minutes: int | None = None
    chart_error: bool
    chart_error_message: dict[str, str]


class PricesResponse(BaseModel):
    refreshed_at: str
    source: dict[str, str]
    assets: list[AssetPrice]


class ProviderHealthStatus(BaseModel):
    provider_id: str
    provider_name: str
    status: str
    last_success_time: str | None = None
    has_api_key: bool


class PriceChainHealth(BaseModel):
    status: str
    source: str
    updated_at: str | None = None
    error: str | None = None
    providers: list[ProviderHealthStatus] = []


class PriceAssetHealth(BaseModel):
    iran: PriceChainHealth
    international: PriceChainHealth


class PricingStartupChecks(BaseModel):
    checked_at: str
    required_env_keys: list[str]
    missing_env_keys: list[str]
    optional_env_keys: list[str]
    missing_optional_env_keys: list[str]
    strict_mode: bool
    ok: bool


class PricesHealthResponse(BaseModel):
    checked_at: str
    last_refresh_at: str | None = None
    startup: PricingStartupChecks
    chains: dict[str, PriceAssetHealth]


class AlertCreate(BaseModel):
    asset: str = Field(default="formula", min_length=1, max_length=20)
    target_price: float | None = Field(default=None, gt=0)
    alert_type: Literal["price", "formula"] = "price"
    formula: str | None = Field(default=None, min_length=3, max_length=200)
    currency_mode: Literal["usd", "toman"] = "usd"
    condition: Literal["above", "below"] = "above"
    notify_app: bool = True
    notify_email: bool = False
    notify_webhook: bool = False
    webhook_url: str | None = Field(default=None, max_length=500)
    enable_dlq: bool = False
    instrument_id: str | None = Field(default=None, max_length=64)
    mode: Literal["one_time", "recurring"] = "one_time"
    cooldown_seconds: int = Field(default=900, ge=60, le=604800)
    max_notifications_per_day: int = Field(default=10, ge=1, le=100)
    notify_sms: bool = False
    notify_telegram: bool = False

    @model_validator(mode="after")
    def validate_alert(self) -> "AlertCreate":
        if self.alert_type == "price" and self.target_price is None:
            raise ValueError("target_price is required for price alerts")
        if self.alert_type == "formula" and not self.formula:
            raise ValueError("formula is required for formula alerts")
        if self.notify_webhook and not (self.webhook_url and self.webhook_url.strip()):
            raise ValueError("webhook_url is required when notify_webhook is enabled")
        return self


class AlertResponse(BaseModel):
    id: int
    asset: str
    target_price: float | None
    alert_type: str
    formula: str | None
    currency_mode: str
    condition: str
    notify_app: bool
    notify_email: bool
    notify_webhook: bool
    webhook_url: str | None
    enable_dlq: bool
    instrument_id: str | None
    mode: str
    cooldown_seconds: int
    max_notifications_per_day: int
    notify_sms: bool
    notify_telegram: bool
    next_eligible_trigger_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
