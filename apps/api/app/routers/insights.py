from __future__ import annotations

import time
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import get_current_user
from ..models import User
from ..services.insights import InsightUnavailableError, insight_engine
from ..services.pricing import pricing_service
from ..services.pricing_registry import ASSET_LABELS

router = APIRouter(prefix="/api/insights", tags=["insights"])

# Lightweight per-user rate limit. The reasoning provider is metered, so this
# caps how often a single account can spend tokens. Scope is per process; for a
# multi-worker deployment a shared store would tighten this further.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 15
_request_log: dict[int, list[float]] = defaultdict(list)


def _enforce_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    recent = [stamp for stamp in _request_log[user_id] if stamp > window_start]
    if len(recent) >= _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a moment and try again.",
        )
    recent.append(now)
    _request_log[user_id] = recent


class AnalyzeRequest(BaseModel):
    asset: str = Field(min_length=1, max_length=20)
    language: Literal["fa", "en"] = "fa"


class AnalyzeResponse(BaseModel):
    asset: str
    analysis: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    language: Literal["fa", "en"] = "fa"


class ChatResponse(BaseModel):
    reply: str


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_chart(
    payload: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> AnalyzeResponse:
    _enforce_rate_limit(current_user.id)

    if payload.asset not in ASSET_LABELS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown asset"
        )

    try:
        prices = await pricing_service.get_prices()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to load market data for analysis",
        ) from exc

    snapshot = next(
        (item for item in prices.get("assets", []) if item.get("asset") == payload.asset),
        None,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No data for this asset"
        )

    try:
        analysis = await insight_engine.analyze_chart(
            payload.asset, snapshot, payload.language
        )
    except InsightUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return AnalyzeResponse(asset=payload.asset, analysis=analysis)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    _enforce_rate_limit(current_user.id)

    messages = [{"role": message.role, "content": message.content} for message in payload.messages]
    try:
        reply = await insight_engine.chat(messages, payload.language)
    except InsightUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return ChatResponse(reply=reply)
