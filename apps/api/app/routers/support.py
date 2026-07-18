from __future__ import annotations

from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import SupportMessage, SupportTicket, User
from ..security import rate_limit_hit
from ..admin.models import AdminSupportTicketState

router = APIRouter(prefix="/api/support")


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("subject", "message")
    @classmethod
    def clean_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("Text must not be empty or contain null bytes")
        return clean


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def clean_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("Text must not be empty or contain null bytes")
        return clean


class TicketResponse(BaseModel):
    id: int
    subject: str
    status: str
    date: str
    last_message: str


class MessageResponse(BaseModel):
    id: int
    ticket_id: int
    from_user: str
    content: str
    timestamp: str


def _serialize_ticket(ticket: SupportTicket) -> dict:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "date": ticket.created_at.strftime("%Y-%m-%d"),
        "last_message": ticket.last_message,
    }


def _serialize_message(message: SupportMessage) -> dict:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "from_user": message.from_user,
        "content": message.content,
        "timestamp": message.created_at.isoformat(),
    }


def _owned_ticket(ticket_id: int, user: User, db: Session) -> SupportTicket:
    ticket = db.scalar(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.user_id == user.id,
        )
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _enforce_write_limit(user_id: int) -> None:
    rate_state = rate_limit_hit("support-write", str(user_id), 30, 60)
    if rate_state.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many support messages. Please retry later.",
            headers={"Retry-After": str(rate_state.retry_after)},
        )


@router.post("/ticket", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket: TicketCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enforce_write_limit(current_user.id)
    new_ticket = SupportTicket(
        user_id=current_user.id,
        subject=ticket.subject,
        status="open",
        last_message=ticket.message,
        last_user_response_at=datetime.now(UTC),
    )
    db.add(new_ticket)
    db.flush()
    db.add(
        SupportMessage(ticket_id=new_ticket.id, from_user="user", content=ticket.message)
    )
    db.commit()
    db.refresh(new_ticket)
    return _serialize_ticket(new_ticket)


@router.get("/tickets", response_model=List[TicketResponse])
def get_tickets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tickets = db.scalars(
        select(SupportTicket)
        .where(SupportTicket.user_id == current_user.id)
        .order_by(SupportTicket.updated_at.desc())
    ).all()
    return [_serialize_ticket(ticket) for ticket in tickets]


@router.get("/ticket/{ticket_id}/messages", response_model=List[MessageResponse])
def get_ticket_messages(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_ticket(ticket_id, current_user, db)
    messages = db.scalars(
        select(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket_id,
            SupportMessage.is_internal.is_(False),
        )
        .order_by(SupportMessage.created_at.asc())
    ).all()
    return [_serialize_message(message) for message in messages]


@router.post("/ticket/{ticket_id}/message", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(
    ticket_id: int,
    message: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enforce_write_limit(current_user.id)
    ticket = _owned_ticket(ticket_id, current_user, db)
    if ticket.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ticket is closed")
    new_message = SupportMessage(
        ticket_id=ticket.id,
        from_user="user",
        content=message.content,
    )
    db.add(new_message)
    ticket.last_message = message.content
    ticket.last_user_response_at = datetime.now(UTC)
    if ticket.status in {"resolved", "waiting_for_user"}:
        ticket.status = "open"
    admin_state = db.get(AdminSupportTicketState, ticket.id)
    if admin_state:
        admin_state.last_user_response_at = ticket.last_user_response_at
        if admin_state.status in {"resolved", "waiting_for_user"}:
            admin_state.status = "open"
    db.commit()
    db.refresh(new_message)
    return _serialize_message(new_message)
