from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Alert, User
from ..schemas import AlertCreate, AlertResponse, AlertUpdate
from ..services.alert_engine import FormulaValidationError, validate_formula, validate_webhook_url
from ..pricing.instruments import get_instrument

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

#: Bound on live alerts per account. Each one is re-evaluated every cycle.
MAX_ACTIVE_ALERTS_PER_USER = 50


def _validate_alert_payload(payload: AlertCreate) -> None:
    if payload.instrument_id:
        try:
            instrument = get_instrument(payload.instrument_id)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail="Unknown instrument") from exc
        if instrument.quote_currency.value.lower() != payload.currency_mode:
            raise HTTPException(status_code=422, detail="Alert currency must match the instrument")
        payload.instrument_id = instrument.instrument_id
    elif payload.alert_type == "price" and payload.asset not in {"gold", "silver", "usdt", "btc"}:
        raise HTTPException(status_code=422, detail="Price alerts require a supported asset or instrument")
    if payload.alert_type == "formula" and payload.formula:
        try:
            validate_formula(payload.formula)
        except FormulaValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.notify_webhook and payload.webhook_url:
        try:
            validate_webhook_url(payload.webhook_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AlertCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    _validate_alert_payload(payload)
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
    # Every active alert is re-evaluated on each cycle, so an unbounded count
    # is a cost the whole platform pays for one account.
    active_alerts = db.scalar(
        select(func.count(Alert.id)).where(
            Alert.user_id == current_user.id, Alert.is_active.is_(True)
        )
    )
    if int(active_alerts or 0) >= MAX_ACTIVE_ALERTS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account may hold at most {MAX_ACTIVE_ALERTS_PER_USER} active alerts.",
        )
    alert = Alert(user_id=current_user.id, **payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.patch("/{alert_id}", response_model=AlertResponse)
def update_alert(
    alert_id: int,
    payload: AlertUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    """Edit an existing alert.

    Without this the only way to move a target price was to delete and
    recreate, which loses the alert's trigger history and cooldown state.
    """
    alert = db.scalar(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.user_id == current_user.id,
            Alert.is_active.is_(True),
        )
    )
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    changes = payload.model_dump(exclude_unset=True)
    merged = {name: getattr(alert, name) for name in AlertCreate.model_fields}
    try:
        validated = AlertCreate.model_validate({**merged, **changes})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Alert update violates the alert contract") from exc
    _validate_alert_payload(validated)
    if changes.get("notify_sms"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SMS alert delivery is not configured.",
        )
    if changes.get("notify_telegram") and not settings.telegram_alert_delivery_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telegram alert delivery is not configured.",
        )
    for field in changes:
        setattr(alert, field, getattr(validated, field))
    # Editing an alert re-arms it: the old trigger no longer describes it.
    alert.triggered_at = None
    alert.last_condition_state = False
    alert.next_eligible_trigger_at = None
    db.commit()
    db.refresh(alert)
    return alert


@router.get("", response_model=list[AlertResponse])
def list_alerts(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AlertResponse]:
    return list(
        db.scalars(
            select(Alert)
            .where(Alert.user_id == current_user.id, Alert.is_active.is_(True))
            .order_by(Alert.created_at.desc(), Alert.id.desc())
            .limit(limit)
            .offset(offset)
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
