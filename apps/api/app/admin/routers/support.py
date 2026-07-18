from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import SupportMessage, SupportTicket, User
from ..audit import add_audit_event
from ..deps import AdminPrincipal, require_permission
from ..models import AdminSupportInternalNote, AdminSupportTicketState
from ..permissions import AdminPermissionKey
from ..schemas import SupportTextRequest, SupportTicketUpdate

router = APIRouter(prefix="/support", tags=["admin-support"])


def _ticket_state(db: Session, ticket: SupportTicket) -> AdminSupportTicketState:
    state_row = db.get(AdminSupportTicketState, ticket.id)
    if state_row is None:
        state_row = AdminSupportTicketState(
            ticket_id=ticket.id,
            status=ticket.status if ticket.status in {
                "open",
                "in_progress",
                "waiting_for_user",
                "resolved",
                "closed",
            } else "open",
            priority="normal",
            last_user_response_at=ticket.updated_at,
        )
        db.add(state_row)
        db.flush()
    return state_row


def _ticket_payload(
    ticket: SupportTicket,
    user: User,
    state_row: AdminSupportTicketState | None,
) -> dict:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": state_row.status if state_row else ticket.status,
        "priority": state_row.priority if state_row else "normal",
        "assigned_admin_id": state_row.assigned_admin_id if state_row else None,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
        },
        "last_message": ticket.last_message,
        "last_admin_response_at": (
            state_row.last_admin_response_at.isoformat()
            if state_row and state_row.last_admin_response_at
            else None
        ),
        "last_user_response_at": (
            state_row.last_user_response_at.isoformat()
            if state_row and state_row.last_user_response_at
            else None
        ),
        "resolved_at": (
            state_row.resolved_at.isoformat() if state_row and state_row.resolved_at else None
        ),
        "closed_at": state_row.closed_at.isoformat() if state_row and state_row.closed_at else None,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }


@router.get("/tickets")
def list_tickets(
    search: str = Query(default="", max_length=160),
    ticket_status: str = Query(default="", alias="status", max_length=24),
    priority: str = Query(default="", max_length=16),
    assigned_admin_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SUPPORT_READ)),
    db: Session = Depends(get_db),
) -> dict:
    statement = (
        select(SupportTicket, User, AdminSupportTicketState)
        .join(User, User.id == SupportTicket.user_id)
        .outerjoin(AdminSupportTicketState, AdminSupportTicketState.ticket_id == SupportTicket.id)
    )
    count_statement = (
        select(func.count(SupportTicket.id))
        .join(User, User.id == SupportTicket.user_id)
        .outerjoin(AdminSupportTicketState, AdminSupportTicketState.ticket_id == SupportTicket.id)
    )
    clean_search = search.strip()
    conditions = []
    if clean_search:
        pattern = f"%{clean_search}%"
        conditions.append(
            or_(
                SupportTicket.subject.ilike(pattern),
                User.username.ilike(pattern),
                User.email.ilike(pattern),
                User.full_name.ilike(pattern),
            )
        )
    if ticket_status:
        conditions.append(
            func.coalesce(AdminSupportTicketState.status, SupportTicket.status) == ticket_status
        )
    if priority:
        conditions.append(func.coalesce(AdminSupportTicketState.priority, "normal") == priority)
    if assigned_admin_id is not None:
        conditions.append(AdminSupportTicketState.assigned_admin_id == assigned_admin_id)
    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    rows = db.execute(
        statement.order_by(SupportTicket.updated_at.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "items": [_ticket_payload(ticket, user, state_row) for ticket, user, state_row in rows],
        "total": int(db.scalar(count_statement) or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: int,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SUPPORT_READ)),
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        select(SupportTicket, User).join(User, User.id == SupportTicket.user_id).where(
            SupportTicket.id == ticket_id
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    ticket, user = row
    state_row = _ticket_state(db, ticket)
    messages = db.scalars(
        select(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.is_internal.is_(False),
        )
        .order_by(SupportMessage.created_at)
    ).all()
    notes = db.execute(
        select(AdminSupportInternalNote, User)
        .outerjoin(User, User.id == AdminSupportInternalNote.admin_id)
        .where(AdminSupportInternalNote.ticket_id == ticket.id)
        .order_by(AdminSupportInternalNote.created_at)
    ).all()
    db.commit()
    return {
        "ticket": _ticket_payload(ticket, user, state_row),
        "messages": [
            {
                "id": message.id,
                "from": message.from_user,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
        "internal_notes": [
            {
                "id": note.id,
                "content": note.content,
                "admin": (
                    {"id": admin.id, "full_name": admin.full_name, "username": admin.username}
                    if admin
                    else None
                ),
                "created_at": note.created_at.isoformat(),
            }
            for note, admin in notes
        ],
    }


@router.patch("/tickets/{ticket_id}")
def update_ticket(
    ticket_id: int,
    payload: SupportTicketUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SUPPORT_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    state_row = _ticket_state(db, ticket)
    if payload.assigned_admin_id is not None:
        assignee = db.get(User, payload.assigned_admin_id)
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Assignee not found")
    before = {
        "status": state_row.status,
        "priority": state_row.priority,
        "assigned_admin_id": state_row.assigned_admin_id,
    }
    now = datetime.now(UTC)
    if payload.priority is not None:
        state_row.priority = payload.priority
        ticket.priority = payload.priority
    if payload.assigned_admin_id is not None:
        state_row.assigned_admin_id = payload.assigned_admin_id
        ticket.assigned_admin_id = payload.assigned_admin_id
    if payload.status is not None:
        state_row.status = payload.status
        ticket.status = payload.status
        ticket.resolved_at = now if payload.status == "resolved" else None
        ticket.closed_at = now if payload.status == "closed" else None
        state_row.resolved_at = now if payload.status == "resolved" else None
        state_row.closed_at = now if payload.status == "closed" else None
    after = {
        "status": state_row.status,
        "priority": state_row.priority,
        "assigned_admin_id": state_row.assigned_admin_id,
    }
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.support.ticket_updated",
        resource_type="support_ticket",
        resource_id=ticket.id,
        before=before,
        after=after,
    )
    db.commit()
    user = db.get(User, ticket.user_id)
    return {"ticket": _ticket_payload(ticket, user, state_row)}


@router.post("/tickets/{ticket_id}/reply", status_code=status.HTTP_201_CREATED)
def reply_to_ticket(
    ticket_id: int,
    payload: SupportTextRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SUPPORT_REPLY)),
    db: Session = Depends(get_db),
) -> dict:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    state_row = _ticket_state(db, ticket)
    if state_row.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Closed ticket cannot receive replies")
    now = datetime.now(UTC)
    message = SupportMessage(
        ticket_id=ticket.id,
        from_user="admin",
        admin_id=principal.user.id,
        is_internal=False,
        content=payload.content,
    )
    db.add(message)
    ticket.last_message = payload.content
    ticket.status = "waiting_for_user"
    state_row.status = "waiting_for_user"
    state_row.last_admin_response_at = now
    ticket.last_admin_response_at = now
    if state_row.assigned_admin_id is None:
        state_row.assigned_admin_id = principal.user.id
        ticket.assigned_admin_id = principal.user.id
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.support.reply_sent",
        resource_type="support_ticket",
        resource_id=ticket.id,
        after={"status": state_row.status, "message_length": len(payload.content)},
    )
    db.commit()
    db.refresh(message)
    return {
        "message": {
            "id": message.id,
            "from": message.from_user,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
    }


@router.post("/tickets/{ticket_id}/internal-notes", status_code=status.HTTP_201_CREATED)
def add_internal_note(
    ticket_id: int,
    payload: SupportTextRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SUPPORT_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(SupportTicket, ticket_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    note = AdminSupportInternalNote(
        ticket_id=ticket_id,
        admin_id=principal.user.id,
        content=payload.content,
    )
    db.add(note)
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.support.internal_note_added",
        resource_type="support_ticket",
        resource_id=ticket_id,
        after={"note_length": len(payload.content)},
    )
    db.commit()
    db.refresh(note)
    return {
        "note": {
            "id": note.id,
            "content": note.content,
            "admin_id": note.admin_id,
            "created_at": note.created_at.isoformat(),
        }
    }
