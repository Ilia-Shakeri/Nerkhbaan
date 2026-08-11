from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AssistantChatMessage, AssistantChatSession, User
from ..pricing.compatibility import legacy_pricing_adapter
from ..pricing.instruments import LEGACY_ASSET_MAPPING
from ..security import rate_limit_hit
from ..services.insights import InsightUnavailableError, insight_engine

router = APIRouter(prefix="/api/insights", tags=["insights"])

_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 15
CHAT_RETENTION_DAYS = 31
_ASSET_IDS = {asset for asset, _currency in LEGACY_ASSET_MAPPING}


def _enforce_rate_limit(user_id: int) -> None:
    limit = rate_limit_hit(
        "insights-user",
        str(user_id),
        _RATE_LIMIT_MAX_REQUESTS,
        _RATE_LIMIT_WINDOW_SECONDS,
    )
    if limit.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a moment and try again.",
            headers={"Retry-After": str(limit.retry_after)},
        )


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
    session_id: int | None = None

    @model_validator(mode="after")
    def last_message_must_be_user(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("Last chat message must come from the user")
        return self


class ChatResponse(BaseModel):
    session_id: int
    reply: str


class ChatSessionSummary(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessage]


class ChatTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def purge_expired_chat_history(db: Session) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=CHAT_RETENTION_DAYS)
    expired_ids = db.scalars(
        select(AssistantChatSession.id).where(AssistantChatSession.updated_at < cutoff)
    ).all()
    if not expired_ids:
        return
    db.execute(delete(AssistantChatMessage).where(AssistantChatMessage.session_id.in_(expired_ids)))
    db.execute(delete(AssistantChatSession).where(AssistantChatSession.id.in_(expired_ids)))
    db.commit()


def _session_summary(session: AssistantChatSession) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def _owned_session(db: Session, user_id: int, session_id: int) -> AssistantChatSession:
    session = db.scalar(
        select(AssistantChatSession).where(
            AssistantChatSession.id == session_id,
            AssistantChatSession.user_id == user_id,
        )
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return session


def _make_title(text: str) -> str:
    clean = " ".join(text.strip().split())
    return clean[:80] or "New chat"


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_chart(
    payload: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> AnalyzeResponse:
    _enforce_rate_limit(current_user.id)

    if payload.asset not in _ASSET_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown asset"
        )

    try:
        prices = await legacy_pricing_adapter.get_prices()
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

    operational = {"live", "confirmed", "fresh_cache", "derived_fallback", "unpersisted"}
    if not (
        str(snapshot.get("usd_status", "")).lower() in operational
        or str(snapshot.get("toman_status", "")).lower() in operational
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified market data is not available for analysis",
        )

    try:
        history = await legacy_pricing_adapter.get_history(payload.asset, "30d")
        snapshot["history"] = history["points"]
        snapshot["history_status"] = history["status"]
    except Exception:
        snapshot["history"] = []
        snapshot["history_status"] = "unavailable"

    try:
        analysis = await insight_engine.analyze_chart(
            payload.asset, snapshot, payload.language, str(current_user.id)
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
    db: Session = Depends(get_db),
) -> ChatResponse:
    _enforce_rate_limit(current_user.id)
    purge_expired_chat_history(db)

    session = None
    if payload.session_id is not None:
        session = _owned_session(db, current_user.id, payload.session_id)

    messages = [{"role": message.role, "content": message.content} for message in payload.messages]
    try:
        reply = await insight_engine.chat(messages, payload.language, str(current_user.id))
    except InsightUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if session is None:
        first_user_message = next(message.content for message in payload.messages if message.role == "user")
        session = AssistantChatSession(user_id=current_user.id, title=_make_title(first_user_message))
        db.add(session)
        db.flush()
    last_user = payload.messages[-1]
    db.add(AssistantChatMessage(session_id=session.id, role="user", content=last_user.content))
    db.add(AssistantChatMessage(session_id=session.id, role="assistant", content=reply))
    session.updated_at = datetime.now(UTC)
    db.commit()

    return ChatResponse(session_id=session.id, reply=reply)


@router.get("/chat/sessions", response_model=list[ChatSessionSummary])
def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatSessionSummary]:
    purge_expired_chat_history(db)
    sessions = db.scalars(
        select(AssistantChatSession)
        .where(AssistantChatSession.user_id == current_user.id)
        .order_by(AssistantChatSession.updated_at.desc())
    ).all()
    return [_session_summary(session) for session in sessions]


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatSessionDetail:
    purge_expired_chat_history(db)
    session = _owned_session(db, current_user.id, session_id)
    rows = db.scalars(
        select(AssistantChatMessage)
        .where(AssistantChatMessage.session_id == session.id)
        .order_by(AssistantChatMessage.created_at.asc(), AssistantChatMessage.id.asc())
    ).all()
    summary = _session_summary(session)
    return ChatSessionDetail(
        **summary.model_dump(),
        messages=[ChatMessage(role=row.role, content=row.content) for row in rows],
    )


@router.patch("/chat/sessions/{session_id}", response_model=ChatSessionSummary)
def rename_chat_session(
    session_id: int,
    payload: ChatTitleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatSessionSummary:
    session = _owned_session(db, current_user.id, session_id)
    session.title = payload.title.strip()
    session.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(session)
    return _session_summary(session)


@router.delete(
    "/chat/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def delete_chat_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    session = _owned_session(db, current_user.id, session_id)
    db.execute(delete(AssistantChatMessage).where(AssistantChatMessage.session_id == session.id))
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
