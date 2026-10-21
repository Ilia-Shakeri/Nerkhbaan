from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChannelUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    provider_id: Literal["none", "kavenegar", "asterisk_ari"]
    enabled: bool
    config: Any = Field(default_factory=dict, repr=False)
    secret_action: Literal["keep", "replace", "clear"] = "keep"
    secret_value: Any = Field(default=None, repr=False, exclude=True)
    confirmation: str | None = None


class QuietHours(BaseModel):
    enabled: bool = True
    start: str = Field(default="22:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="08:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: Literal["Asia/Tehran"] = "Asia/Tehran"
    critical_bypass: bool = False

    @model_validator(mode="after")
    def nonempty_window(self):
        if self.enabled and self.start == self.end:
            raise ValueError("Quiet hours must have distinct start and end")
        return self


class CallPolicyUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    enabled: bool = False
    critical_only: bool = True
    persist_seconds: int = Field(default=60, ge=0, le=3600)
    max_attempts: int = Field(default=1, ge=1, le=1, strict=True)
    cooldown_seconds: int = Field(default=900, ge=30, le=86400)
    max_calls_per_day: int = Field(default=3, ge=1, le=100)
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    confirmation: str | None = None


class TestRecipientCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    phone: Any = Field(repr=False, exclude=True)
    consent_confirmed: bool = False


class TestEventCreate(BaseModel):
    channel: Literal["sms", "voip"]
    recipient_id: int = Field(ge=1)
    mode: Literal["dry_run", "send"] = "dry_run"
    client_request_id: UUID
    confirmation: str | None = None
