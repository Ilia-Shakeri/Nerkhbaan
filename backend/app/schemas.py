from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserSignin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(UserBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


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
