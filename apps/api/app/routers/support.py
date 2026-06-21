from __future__ import annotations

from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/support")


class TicketCreate(BaseModel):
    subject: str
    message: str


class MessageCreate(BaseModel):
    ticket_id: int
    content: str


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


@router.post("/ticket", response_model=TicketResponse)
# Remove the async keyword to prevent synchronous database queries from crashing concurrency
def create_ticket(
    ticket: TicketCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_ticket = {
        "id": 1,
        "subject": ticket.subject,
        "status": "open",
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "last_message": ticket.message
    }
    return new_ticket

@router.get("/tickets", response_model=List[TicketResponse])
# Remove the async keyword for synchronous session compatibility
def get_tickets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tickets = [
        {
            "id": 1,
            "subject": "Platform issue report",
            "status": "open",
            "date": "2025-06-20",
            "last_message": "Investigating..."
        }
    ]
    return tickets


@router.get("/ticket/{ticket_id}/messages", response_model=List[MessageResponse])
async def get_ticket_messages(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    messages = [
        {
            "id": 1,
            "ticket_id": ticket_id,
            "from_user": "user",
            "content": "Hello, gold price is not updating.",
            "timestamp": datetime.now(UTC).isoformat()
        },
        {
            "id": 2,
            "ticket_id": ticket_id,
            "from_user": "admin",
            "content": "We are investigating.",
            "timestamp": datetime.now(UTC).isoformat()
        }
    ]
    return messages


@router.post("/ticket/{ticket_id}/message", response_model=MessageResponse)
async def send_message(
    ticket_id: int,
    message: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_message = {
        "id": 3,
        "ticket_id": ticket_id,
        "from_user": "user",
        "content": message.content,
        "timestamp": datetime.now(UTC).isoformat()
    }
    return new_message
