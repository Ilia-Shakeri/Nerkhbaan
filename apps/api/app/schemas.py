from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


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
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


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


class AssetPrice(BaseModel):
    asset: str
    label_fa: str
    label_en: str
    price_usd: float | None
    price_toman: float | None
    change_percent: float
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
    asset: str
    target_price: float
    currency_mode: str = "usd"
    condition: str = "above"
    notify_app: bool = True
    notify_email: bool = False
    notify_webhook: bool = False
    webhook_url: str | None = None
    enable_dlq: bool = False


class AlertResponse(BaseModel):
    id: int
    asset: str
    target_price: float
    currency_mode: str
    condition: str
    notify_app: bool
    notify_email: bool
    notify_webhook: bool
    webhook_url: str | None
    enable_dlq: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}