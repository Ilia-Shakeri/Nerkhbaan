from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Alert, User
from ..schemas import AlertCreate, AlertResponse
from ..services.alert_engine import FormulaValidationError, validate_formula, validate_webhook_url

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AlertCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    if payload.notify_sms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SMS alert delivery is not configured.",
        )
    if payload.notify_telegram and not settings.telegram_alert_delivery_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telegram alert delivery is not configured.",
        )
    if payload.alert_type == "formula" and payload.formula:
        try:
            validate_formula(payload.formula)
        except FormulaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if payload.notify_webhook and payload.webhook_url:
        try:
            validate_webhook_url(payload.webhook_url)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    alert = Alert(user_id=current_user.id, **payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("", response_model=list[AlertResponse])
def list_alerts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AlertResponse]:
    return list(
        db.scalars(
            select(Alert).where(Alert.user_id == current_user.id, Alert.is_active == True)
        ).all()
    )


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def delete_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    alert = db.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id)
    )
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
