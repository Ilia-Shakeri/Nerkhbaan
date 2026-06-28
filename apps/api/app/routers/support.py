from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import SupportMessage, SupportTicket, User

router = APIRouter(prefix="/api/support")


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


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


@router.post("/ticket", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket: TicketCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_ticket = SupportTicket(
        user_id=current_user.id,
        subject=ticket.subject,
        status="open",
        last_message=ticket.message,
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
        .where(SupportMessage.ticket_id == ticket_id)
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
    ticket = _owned_ticket(ticket_id, current_user, db)
    new_message = SupportMessage(
        ticket_id=ticket.id,
        from_user="user",
        content=message.content,
    )
    db.add(new_message)
    ticket.last_message = message.content
    db.commit()
    db.refresh(new_message)
    return _serialize_message(new_message)
