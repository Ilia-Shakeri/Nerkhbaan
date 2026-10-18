from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class UserBase(BaseModel):
    # Sign-in accepts either identifier against one column pair, so a username
    # shaped like an email address makes the lookup ambiguous between two
    # accounts. Restricting the charset removes the overlap entirely.
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class UserCreate(UserBase):
    full_name: str = Field(default="", max_length=120)
    accepted_terms: bool
    account_data_consent: bool
    policy_version: Literal["2026-09-19.2"]
    password: str = Field(min_length=10, max_length=128)

    @field_validator("full_name")
    @classmethod
    def optional_display_name(cls, value: str) -> str:
        value = value.strip()
        if value and len(value) < 2:
            raise ValueError("Display name must be empty or at least two characters")
        return value

    @field_validator("accepted_terms", "account_data_consent", mode="before")
    @classmethod
    def explicit_agreement(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Explicit agreement is required")
        return True

    @field_validator("password")
    @classmethod
    def password_must_be_mixed(cls, value: str) -> str:
        classes = (
            any(character.islower() for character in value),
            any(character.isupper() for character in value),
            any(character.isdigit() for character in value),
        )
        if not all(classes):
            raise ValueError(
                "Password must include lower case, upper case, and a digit"
            )
        return value


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
    access_token: str | None = None
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
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_must_be_mixed(cls, value: str) -> str:
        return UserCreate.password_must_be_mixed(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_must_be_mixed(cls, value: str) -> str:
        return UserCreate.password_must_be_mixed(value)


class HistoryTimeInfo(BaseModel):
    timestamp_precision: Literal["instant", "day"] | None = None
    timestamp_role: Literal["day_bucket_start"] | None = None
    source_observation_time_known: bool | None = None
    source_timezone: str | None = None
    source_calendar: Literal["jalali", "gregorian"] | None = None
    source_date: str | None = None


class PricePoint(HistoryTimeInfo):
    timestamp: str
    value_usd: float | None
    value_toman: float | None
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    time_info_usd: HistoryTimeInfo | None = None
    time_info_toman: HistoryTimeInfo | None = None


ReferenceInstrumentId = Literal[
    "GOLD_24K_REFERENCE_TOMAN_GRAM", "BTC_USD_IRAN_REFERENCE", "USDT_USD_IRAN_REFERENCE",
]
ReferenceStatus = Literal["fresh_reference", "delayed_reference", "unavailable_reference"]


class ReferenceInput(BaseModel):
    source_key: str
    instrument_id: str
    price: float | None = None
    price_decimal: str | None = None
    currency: Literal["TOMAN"]
    as_of: str | None = None
    source_date: str
    source_timezone: Literal["Asia/Tehran"]
    source_calendar: Literal["jalali"]
    timestamp_precision: Literal["minute", "day"]
    timestamp_role: Literal["source_rates_last_change", "day_bucket_start"]
    source_observation_time_known: Literal[False]


class ReferenceIdentity(BaseModel):
    instrument_id: ReferenceInstrumentId
    label_fa: str
    label_en: str
    currency: Literal["TOMAN", "USD"]
    market: Literal["reference"]
    region: Literal["iran"]
    method: Literal["published_reference", "iran_fx_ratio"]
    physical_purity_confirmed: Literal[False]
    purity: None = None
    weight_unit: Literal["gram", "unit"]
    nominal_karat: Literal[24] | None = None
    is_derived: bool
    source_provider_id: Literal["nerkhsanj_reference_snapshot", "nerkhsanj_reference_history"]
    source_keys: list[str] = Field(min_length=1, max_length=2)
    attribution: dict[str, str]
    disclaimer_fa: str

    @model_validator(mode="after")
    def validate_reference_identity(self) -> "ReferenceIdentity":
        from .pricing.reference_rates import reference_definitions

        definition = next(item for item in reference_definitions() if item["instrument_id"] == self.instrument_id)
        for name in ("currency", "market", "region", "method", "physical_purity_confirmed", "purity",
                     "weight_unit", "nominal_karat", "is_derived", "source_keys"):
            if getattr(self, name) != definition[name]:
                raise ValueError("Reference fields must match their named contract")
        return self


class ReferenceCurrent(ReferenceIdentity):
    status: ReferenceStatus
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    price_decimal: str | None = None
    observed_at: str | None = None
    received_at: str | None = None
    source_date: str | None = None
    source_time: str | None = None
    source_timestamp_scope: Literal["source_rates_last_change"] | None = None
    source_timestamp_precision: Literal["minute"] | None = None
    source_timezone: Literal["Asia/Tehran"] = "Asia/Tehran"
    source_calendar: Literal["jalali"] = "jalali"
    source_observation_time_known: Literal[False] = False
    source_trade_time_known: Literal[False] = False
    age_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    freshness_limit_seconds: int = Field(ge=1)
    maximum_reference_age_seconds: int = Field(ge=1, le=86400)
    inputs: list[ReferenceInput] = Field(default_factory=list, max_length=2)
    unavailable_reason: str | None = None
    persistence_status: Literal["persisted", "unpersisted", "unavailable"] = "unavailable"
    storage_fallback: bool = False

    @model_validator(mode="after")
    def validate_reference_value(self) -> "ReferenceCurrent":
        if self.price is not None:
            from .pricing.reference_rates import validate_reference_record
            validate_reference_record(self.model_dump(), "snapshot")
        return self


class ReferenceHistoryPoint(ReferenceIdentity, HistoryTimeInfo):
    timestamp: str
    price: float = Field(gt=0, allow_inf_nan=False)
    price_decimal: str
    source_date: str
    source_time: None = None
    source_timestamp_scope: Literal["source_reported_daily_close"]
    timestamp_precision: Literal["day"]
    timestamp_role: Literal["day_bucket_start"]
    source_timezone: Literal["Asia/Tehran"]
    source_calendar: Literal["jalali"]
    source_observation_time_known: Literal[False]
    history_point_kind: Literal["published_reference_daily_close", "same_day_iran_fx_ratio"]
    inputs: list[ReferenceInput] = Field(max_length=2)

    @model_validator(mode="after")
    def validate_reference_value(self) -> "ReferenceHistoryPoint":
        from .pricing.reference_rates import validate_reference_record
        validate_reference_record(self.model_dump(), "history")
        return self


class ReferenceRateItem(ReferenceIdentity):
    status: ReferenceStatus
    current: ReferenceCurrent
    history: list[ReferenceHistoryPoint] = Field(default_factory=list, max_length=366)
    history_status: Literal["complete", "partial"]
    history_time_info: HistoryTimeInfo


class ReferenceRatesResponse(BaseModel):
    rights_revision: str
    checked_at: str
    timeframe: Literal["1h", "24h", "7d", "30d", "1y"]
    references: list[ReferenceRateItem] = Field(min_length=3, max_length=3)
    attributions: list[dict[str, str]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list, max_length=16)


class PricingWorkerQuote(BaseModel):
    instrument_id: str = Field(pattern=r"^(BTC_USD|XAG_USD_OZ|XAU_USD_OZ)$")
    provider_id: str = Field(pattern=r"^gold_api_free_(xag|xau|btc)$")
    price: Decimal = Field(gt=0)
    observed_at: datetime
    historical: bool = False


class PricingWorkerIngestRequest(BaseModel):
    quotes: list[PricingWorkerQuote] = Field(min_length=1, max_length=800)


class PriceHistoryResponse(BaseModel):
    asset: str
    rights_revision: str = ""
    usd_attributions: list[dict[str, str]] = Field(default_factory=list)
    toman_attributions: list[dict[str, str]] = Field(default_factory=list)
    attributions: list[dict[str, str]] = Field(default_factory=list)
    points: list[PricePoint]
    timeframe: str | None = None
    status: str = "complete"


class InstrumentUnit(BaseModel):
    instrument_id: str
    quote_currency: str
    weight_unit: str
    purity: float | None = None
    market: str
    display_decimals: int


class AssetPrice(BaseModel):
    asset: str
    label_fa: str
    label_en: str
    price_usd: float | None
    price_toman: float | None
    # The USD and Toman legs are separate instruments with their own unit and
    # fineness; clients need both descriptors to label them honestly.
    instrument_id_usd: str | None = None
    instrument_id_toman: str | None = None
    unit_usd: InstrumentUnit | None = None
    unit_toman: InstrumentUnit | None = None
    change_percent_usd: float | None = None
    change_percent_toman: float | None = None
    change_percent: float | None
    trend: str
    history: list[PricePoint]
    source_usd: str
    source_toman: str
    usd_attributions: list[dict[str, str]] = Field(default_factory=list)
    toman_attributions: list[dict[str, str]] = Field(default_factory=list)
    usd_source_summary: dict = Field(default_factory=dict)
    toman_source_summary: dict = Field(default_factory=dict)
    usd_observed_at: str | None = None
    toman_observed_at: str | None = None
    usd_status: str
    toman_status: str
    stale_minutes: int | None = None
    chart_error: bool
    chart_error_message: dict[str, str]


class PricesResponse(BaseModel):
    refreshed_at: str
    rights_revision: str = ""
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
    instruments_without_direct_source: list[str] = []
    instruments_unservable: list[str] = []
    ok: bool


class PricingRefreshHealth(BaseModel):
    enabled: bool
    state: str
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_error_type: str | None = None
    result_counts: dict[str, int] = Field(default_factory=dict)


class PricesHealthResponse(BaseModel):
    checked_at: str
    last_refresh_at: str | None = None
    startup: PricingStartupChecks
    chains: dict[str, PriceAssetHealth]
    refresh: PricingRefreshHealth


class AlertCreate(BaseModel):
    asset: str = Field(default="formula", min_length=1, max_length=20)
    target_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    alert_type: Literal["price", "formula"] = "price"
    formula: str | None = Field(default=None, min_length=3, max_length=200)
    currency_mode: Literal["usd", "toman"] = "usd"
    price_source_mode: Literal["ordinary", "reference", "derived"] = "ordinary"
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


class AlertUpdate(BaseModel):
    """Partial update. Only supplied fields change."""

    asset: str | None = Field(default=None, min_length=1, max_length=20)
    instrument_id: str | None = Field(default=None, max_length=64)
    alert_type: Literal["price", "formula"] | None = None
    target_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    formula: str | None = Field(default=None, min_length=3, max_length=200)
    currency_mode: Literal["usd", "toman"] | None = None
    price_source_mode: Literal["ordinary", "reference", "derived"] | None = None
    condition: Literal["above", "below"] | None = None
    notify_app: bool | None = None
    notify_email: bool | None = None
    notify_webhook: bool | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    enable_dlq: bool | None = None
    mode: Literal["one_time", "recurring"] | None = None
    cooldown_seconds: int | None = Field(default=None, ge=60, le=604800)
    max_notifications_per_day: int | None = Field(default=None, ge=1, le=100)
    notify_sms: bool | None = None
    notify_telegram: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "AlertUpdate":
        nullable = {"target_price", "formula", "webhook_url", "instrument_id"}
        for name in self.model_fields_set - nullable:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class AlertResponse(BaseModel):
    id: int
    asset: str
    target_price: float | None
    alert_type: str
    formula: str | None
    currency_mode: str
    price_source_mode: str
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
