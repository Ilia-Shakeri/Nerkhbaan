from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..db import get_db
from ..config import settings
from ..deps import bearer_scheme, get_current_user
from ..models import User
from ..pricing.health import pricing_health_service
from ..pricing.instruments import UnknownInstrumentError
from ..pricing.service import instrument_pricing_service

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if credentials is None and not cookie_token:
        return None
    return get_current_user(request, credentials, db)


@router.get("")
async def list_instruments(
    user: User | None = Depends(optional_current_user),
) -> dict:
    return {
        "instruments": await instrument_pricing_service.list_instruments(
            authenticated=user is not None
        )
    }


@router.get("/{instrument_id}/history")
async def instrument_history(
    instrument_id: str,
    timeframe: Annotated[str, Query(pattern="^(1h|24h|7d|30d|1y)$")] = "24h",
) -> dict:
    try:
        result = await instrument_pricing_service.canonical_history(
            instrument_id, timeframe
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Instrument history is unavailable") from exc
    return result.to_dict()


@router.get("/{instrument_id}/sources/history")
async def instrument_source_history(
    instrument_id: str,
    timeframe: Annotated[str, Query(pattern="^(1h|24h|7d|30d|1y)$")] = "24h",
    provider_id: str | None = Query(default=None, max_length=100),
    user: User | None = Depends(optional_current_user),
) -> dict:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required for source history",
        )
    try:
        return await instrument_pricing_service.source_history(
            instrument_id, timeframe, provider_id
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Source history is unavailable") from exc


@router.get("/{instrument_id}/sources")
async def instrument_sources(
    instrument_id: str,
    user: User | None = Depends(optional_current_user),
) -> dict:
    try:
        return await instrument_pricing_service.sources(
            instrument_id, authenticated=user is not None
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc


@router.get("/{instrument_id}/verification")
async def instrument_verification(
    instrument_id: str,
    user: User | None = Depends(optional_current_user),
) -> dict:
    try:
        return await instrument_pricing_service.verification(
            instrument_id, authenticated=user is not None
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Verification data is unavailable") from exc


@router.get("/{instrument_id}/health")
async def instrument_health(
    instrument_id: str,
    user: User | None = Depends(optional_current_user),
) -> dict:
    try:
        return await pricing_health_service.instrument_health(
            instrument_id, authenticated=user is not None
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc


@router.get("/{instrument_id}")
async def get_instrument(
    instrument_id: str,
    user: User | None = Depends(optional_current_user),
) -> dict:
    try:
        return await instrument_pricing_service.instrument(
            instrument_id, authenticated=user is not None
        )
    except UnknownInstrumentError as exc:
        raise HTTPException(status_code=404, detail="Unknown instrument") from exc
