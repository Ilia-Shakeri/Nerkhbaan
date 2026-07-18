from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def validate_admin_password(value: str) -> str:
    if len(value) < 14 or len(value) > 128:
        raise ValueError("Admin password must contain 14 to 128 characters")
    checks = (
        re.search(r"[a-z]", value),
        re.search(r"[A-Z]", value),
        re.search(r"[0-9]", value),
        re.search(r"[^A-Za-z0-9]", value),
    )
    if not all(checks):
        raise ValueError("Admin password must include upper, lower, number, and symbol")
    return value


class AdminSigninRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class AdminReauthenticationRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class AdminPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=14, max_length=128)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_admin_password(value)


class DangerousConfirmation(BaseModel):
    confirmation: str = Field(min_length=3, max_length=200)


class AdminRoleAssignmentRequest(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=8)
    confirmation: str = Field(min_length=3, max_length=200)

    @field_validator("roles")
    @classmethod
    def normalize_roles(cls, values: list[str]) -> list[str]:
        roles = sorted({value.strip().lower() for value in values if value.strip()})
        if not roles:
            raise ValueError("At least one role is required")
        return roles


class UserStateUpdate(BaseModel):
    is_active: bool
    reason: str = Field(min_length=3, max_length=240)
    confirmation: str = Field(min_length=3, max_length=200)


class SupportTicketUpdate(BaseModel):
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    status: Literal["open", "in_progress", "waiting_for_user", "resolved", "closed"] | None = None
    assigned_admin_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def at_least_one_change(self) -> "SupportTicketUpdate":
        if self.priority is None and self.status is None and self.assigned_admin_id is None:
            raise ValueError("At least one support field is required")
        return self


class SupportTextRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("Content is invalid")
        return clean


class ProviderDraftRequest(BaseModel):
    enabled: bool | None = None
    role: Literal["primary", "verifier", "fallback", "compare"] | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    trust_score: float | None = Field(default=None, ge=0, le=1)
    minimum_interval_seconds: int | None = Field(default=None, ge=1, le=86400)
    operational_ttl_seconds: int | None = Field(default=None, ge=5, le=172800)
    requests_per_minute: int | None = Field(default=None, ge=0, le=10000)
    requests_per_hour: int | None = Field(default=None, ge=0, le=100000)
    requests_per_day: int | None = Field(default=None, ge=0, le=1000000)
    reserved_anomaly_requests: int | None = Field(default=None, ge=0, le=100000)
    reserved_fallback_requests: int | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ProviderDraftRequest":
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one provider setting is required")
        return self


class TelegramSourceUpdate(BaseModel):
    enabled: bool | None = None
    role: Literal["compare", "verifier", "fallback"] | None = None
    trust_score: float | None = Field(default=None, ge=0, le=1)
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    maximum_message_age_seconds: int | None = Field(default=None, ge=30, le=86400)
    maximum_deviation_percent: float | None = Field(default=None, ge=0.1, le=50)
    requires_multiple_sources: bool | None = None
    allowed_instruments: list[str] | None = Field(default=None, max_length=32)
    parser_type: str | None = Field(default=None, min_length=1, max_length=80)
    parser_version: str | None = Field(default=None, min_length=1, max_length=32)
    confirmation: str | None = Field(default=None, max_length=200)

    @field_validator("allowed_instruments")
    @classmethod
    def valid_instruments(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        clean = sorted({value.strip().upper() for value in values if value.strip()})
        if not clean or any(not re.fullmatch(r"[A-Z0-9_]{3,64}", value) for value in clean):
            raise ValueError("Allowed instruments are invalid")
        return clean


class TelegramSourceCreate(BaseModel):
    channel_id: str = Field(min_length=2, max_length=80)
    username: str | None = Field(default=None, max_length=80)
    display_name: str = Field(min_length=2, max_length=160)
    source_type: Literal["channel", "group"] = "channel"
    allowed_instruments: list[str] = Field(min_length=1, max_length=32)
    role: Literal["compare", "verifier", "fallback"] = "verifier"
    trust_score: float = Field(default=0.5, ge=0, le=1)
    minimum_confidence: float = Field(default=0.8, ge=0, le=1)
    maximum_message_age_seconds: int = Field(default=300, ge=30, le=86400)
    maximum_deviation_percent: float = Field(default=3, ge=0.1, le=50)
    requires_multiple_sources: bool = False
    parser_type: str = Field(min_length=1, max_length=80)
    parser_version: str = Field(min_length=1, max_length=32)
    enabled: bool = True
    confirmation: str = Field(min_length=3, max_length=200)

    @field_validator("channel_id")
    @classmethod
    def valid_channel_id(cls, value: str) -> str:
        clean = value.strip()
        if not re.fullmatch(r"[-A-Za-z0-9_]{2,80}", clean):
            raise ValueError("Telegram channel ID is invalid")
        return clean

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip().lstrip("@")
        if clean and not re.fullmatch(r"[A-Za-z0-9_]{3,80}", clean):
            raise ValueError("Telegram username is invalid")
        return clean or None

    @field_validator("allowed_instruments")
    @classmethod
    def valid_instruments(cls, values: list[str]) -> list[str]:
        clean = sorted({value.strip().upper() for value in values if value.strip()})
        if not clean or any(not re.fullmatch(r"[A-Z0-9_]{3,64}", value) for value in clean):
            raise ValueError("Allowed instruments are invalid")
        return clean


class AnomalyReviewRequest(BaseModel):
    status: Literal["reviewed", "confirmed", "dismissed"]
    note: str = Field(default="", max_length=1000)


class RefreshRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=240)


class JobRetryRequest(BaseModel):
    confirmation: str | None = Field(default=None, max_length=200)


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    confirmation: str | None = Field(default=None, max_length=200)


class OperationalSettingKey(StrEnum):
    COMPARISON_VISIBLE = "comparison_visible"
    DERIVED_FALLBACK_ENABLED = "derived_fallback_enabled"
    BACKFILL_ENABLED = "backfill_enabled"
    TELEGRAM_SOURCE_ENABLED = "telegram_source_enabled"
    ANOMALY_THRESHOLD_PERCENT = "anomaly_threshold_percent"
    CANONICAL_EXPIRY_SECONDS = "canonical_expiry_seconds"
    PROVIDER_BUDGET_PER_HOUR = "provider_budget_requests_per_hour"


class OperationalSettingUpdate(BaseModel):
    key: OperationalSettingKey
    scope_id: str = Field(default="global", min_length=1, max_length=160)
    value: bool | int | float
    confirmation: str | None = Field(default=None, max_length=200)

    @field_validator("scope_id")
    @classmethod
    def safe_scope(cls, value: str) -> str:
        clean = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", clean):
            raise ValueError("Setting scope is invalid")
        return clean

    @model_validator(mode="after")
    def validate_value(self) -> "OperationalSettingUpdate":
        boolean_keys = {
            OperationalSettingKey.COMPARISON_VISIBLE,
            OperationalSettingKey.DERIVED_FALLBACK_ENABLED,
            OperationalSettingKey.BACKFILL_ENABLED,
            OperationalSettingKey.TELEGRAM_SOURCE_ENABLED,
        }
        if self.key in boolean_keys and type(self.value) is not bool:
            raise ValueError("This setting requires a boolean value")
        if self.key == OperationalSettingKey.ANOMALY_THRESHOLD_PERCENT:
            numeric = float(self.value)
            if not 0.1 <= numeric <= 25:
                raise ValueError("Anomaly threshold must be between 0.1 and 25")
        if self.key == OperationalSettingKey.CANONICAL_EXPIRY_SECONDS:
            if type(self.value) is bool or not 30 <= int(self.value) <= 172800:
                raise ValueError("Expiry must be between 30 and 172800 seconds")
        if self.key == OperationalSettingKey.PROVIDER_BUDGET_PER_HOUR:
            if type(self.value) is bool or not 0 <= int(self.value) <= 100000:
                raise ValueError("Provider budget must be between 0 and 100000")
        return self


class BootstrapIdentity(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: Annotated[str, Field(min_length=14, max_length=128)]
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        clean = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]+", clean):
            raise ValueError("Bootstrap username is invalid")
        return clean

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_admin_password(value)
