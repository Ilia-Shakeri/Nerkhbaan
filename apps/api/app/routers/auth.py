from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import PasswordReset, SecurityEvent, User, UserSession
from ..schemas import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SessionResponse,
    UserCreate,
    UserResponse,
    UserSignin,
)
from ..security import (
    create_access_token,
    decode_access_claims,
    generate_refresh_token,
    get_client_ip,
    hash_client_value,
    hash_password,
    hash_refresh_token,
    rate_limit_clear,
    rate_limit_hit,
    rate_limit_status,
    send_email,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_CODE_TTL_MINUTES = 15
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
ACCOUNT_LOCK_MINUTES = 15
_DUMMY_PASSWORD_HASH = "$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW"


def _raise_rate_limit(retry_after: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please retry later.",
        headers={"Retry-After": str(retry_after)},
    )


def _enforce_request_limit(
    request: Request,
    bucket: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    state = rate_limit_hit(
        bucket,
        f"{get_client_ip(request)}:{identity}",
        limit,
        window_seconds,
    )
    if state.blocked:
        _raise_rate_limit(state.retry_after)


def _record_security_event(
    db: Session,
    request: Request,
    event_type: str,
    result: str,
    user_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        SecurityEvent(
            user_id=user_id,
            event_type=event_type,
            result=result,
            ip_hash=hash_client_value(get_client_ip(request)),
            user_agent_hash=hash_client_value(request.headers.get("user-agent")),
            detail=detail or {},
        )
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    if not settings.auth_cookie_enabled:
        return
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=access_token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        domain=settings.auth_cookie_domain,
    )
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=refresh_token,
        max_age=settings.auth_refresh_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_refresh_path,
        domain=settings.auth_cookie_domain,
    )


def _clear_auth_cookies(response: Response) -> None:
    for name, path in (
        (settings.auth_cookie_name, "/"),
        (settings.auth_refresh_cookie_name, settings.auth_refresh_path),
    ):
        response.delete_cookie(
            key=name,
            path=path,
            domain=settings.auth_cookie_domain,
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite=settings.auth_cookie_samesite,
        )


def _issue_session(
    db: Session,
    user: User,
    request: Request,
    *,
    token_family: str | None = None,
) -> tuple[str, str, UserSession]:
    now = datetime.now(UTC)
    refresh_token = generate_refresh_token()
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_family=token_family or str(uuid.uuid4()),
        refresh_token_hash=hash_refresh_token(refresh_token),
        ip_hash=hash_client_value(get_client_ip(request)),
        user_agent_hash=hash_client_value(request.headers.get("user-agent")),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=settings.auth_refresh_days),
    )
    db.add(session)
    db.flush()
    access_token = create_access_token(
        str(user.id),
        session_id=session.id,
        security_version=user.security_version,
    )
    return access_token, refresh_token, session


def _revoke_user_sessions(db: Session, user_id: int, reason: str) -> None:
    now = datetime.now(UTC)
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user = db.get(User, user_id)
    if user:
        user.security_version += 1


def _refresh_value(request: Request, payload: RefreshRequest | None) -> str | None:
    if payload and payload.refresh_token:
        return payload.refresh_token
    return request.cookies.get(settings.auth_refresh_cookie_name)


def _desktop_refresh_token(request: Request, refresh_token: str) -> str | None:
    if not settings.auth_return_bearer_token:
        return None
    return refresh_token if request.headers.get("x-client-type", "").lower() == "desktop" else None


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    _enforce_request_limit(request, "signup", "account", 8, 60 * 60)
    existing_user = db.scalar(
        select(User).where(
            (User.email == payload.email.lower()) | (User.username == payload.username.lower())
        )
    )
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username is already registered")

    user = User(
        username=payload.username.lower(),
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    token, refresh_token, _ = _issue_session(db, user, request)
    _record_security_event(db, request, "signup", "success", user.id)
    db.commit()
    db.refresh(user)
    _set_auth_cookies(response, token, refresh_token)
    return AuthResponse(
        access_token=token,
        refresh_token=_desktop_refresh_token(request, refresh_token),
        user=UserResponse.model_validate(user),
    )


@router.post("/signin", response_model=AuthResponse)
def signin(
    payload: UserSignin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    identifier = payload.username_or_email.strip().lower()
    login_identity = f"{get_client_ip(request)}:{identifier}"
    failure_state = rate_limit_status(
        "signin-failure", login_identity, LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS
    )
    if failure_state.count >= LOGIN_FAILURE_LIMIT:
        _raise_rate_limit(failure_state.retry_after)

    user = db.scalar(select(User).where((User.email == identifier) | (User.username == identifier)))
    now = datetime.now(UTC)
    if user and user.locked_until and user.locked_until > now:
        _record_security_event(db, request, "signin", "locked", user.id)
        db.commit()
        _raise_rate_limit(max(1, int((user.locked_until - now).total_seconds())))

    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    if not user or not verify_password(payload.password, password_hash):
        attempt = rate_limit_hit(
            "signin-failure", login_identity, LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS
        )
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= LOGIN_FAILURE_LIMIT:
                user.locked_until = now + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
            _record_security_event(db, request, "signin", "failed", user.id)
            db.commit()
        if attempt.blocked:
            _raise_rate_limit(attempt.retry_after)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        _record_security_event(db, request, "signin", "disabled", user.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    rate_limit_clear("signin-failure", login_identity)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token, refresh_token, _ = _issue_session(db, user, request)
    _record_security_event(db, request, "signin", "success", user.id)
    db.commit()
    _set_auth_cookies(response, token, refresh_token)
    return AuthResponse(
        access_token=token,
        refresh_token=_desktop_refresh_token(request, refresh_token),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=AuthResponse)
def refresh_session(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> AuthResponse:
    raw_token = _refresh_value(request, payload)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    token_hash = hash_refresh_token(raw_token)
    session = db.scalar(
        select(UserSession)
        .where(UserSession.refresh_token_hash == token_hash)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if session.revoked_at is not None:
        if session.replaced_by_session_id:
            db.execute(
                update(UserSession)
                .where(UserSession.token_family == session.token_family, UserSession.revoked_at.is_(None))
                .values(revoked_at=now, compromised_at=now)
            )
            _record_security_event(db, request, "refresh_reuse", "blocked", session.user_id)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token was revoked")
    if session.expires_at <= now:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable")

    access_token, next_refresh_token, next_session = _issue_session(
        db, user, request, token_family=session.token_family
    )
    session.revoked_at = now
    session.last_used_at = now
    session.replaced_by_session_id = next_session.id
    _record_security_event(db, request, "refresh", "success", user.id)
    db.commit()
    _set_auth_cookies(response, access_token, next_refresh_token)
    return AuthResponse(
        access_token=access_token,
        refresh_token=_desktop_refresh_token(request, next_refresh_token),
        user=UserResponse.model_validate(user),
    )


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _enforce_request_limit(request, "password-recovery", payload.email.lower(), 5, 15 * 60)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user and user.is_active:
        code = f"{secrets.randbelow(1_000_000):06d}"
        reset = PasswordReset(
            user_id=user.id,
            code_hash=hash_password(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=RESET_CODE_TTL_MINUTES),
        )
        db.add(reset)
        db.flush()
        delivered = send_email(
            user.email,
            "Nerkhbaan password recovery",
            f"Your password recovery code is {code}. It expires in {RESET_CODE_TTL_MINUTES} minutes.",
        )
        if delivered:
            _record_security_event(db, request, "password_recovery", "sent", user.id)
            db.commit()
        else:
            db.rollback()
            logger.warning("Password recovery delivery is unavailable")
    return {"message": "If an account exists for that email, a recovery code has been sent."}


@router.post("/reset-password")
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    recovery_identity = f"{get_client_ip(request)}:{payload.email.lower()}"
    attempt = rate_limit_hit("password-reset", recovery_identity, 10, 15 * 60)
    if attempt.blocked:
        _raise_rate_limit(attempt.retry_after)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user:
        reset = db.scalar(
            select(PasswordReset)
            .where(PasswordReset.user_id == user.id, PasswordReset.used.is_(False))
            .order_by(PasswordReset.created_at.desc())
        )
        if reset and reset.expires_at > datetime.now(UTC) and verify_password(payload.code, reset.code_hash):
            user.password_hash = hash_password(payload.new_password)
            user.password_changed_at = datetime.now(UTC)
            reset.used = True
            _revoke_user_sessions(db, user.id, "password_reset")
            _record_security_event(db, request, "password_reset", "success", user.id)
            db.commit()
            rate_limit_clear("password-reset", recovery_identity)
            return {"message": "Password updated successfully."}
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired recovery code")


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        _record_security_event(db, request, "password_change", "failed", current_user.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.password_changed_at = datetime.now(UTC)
    current_user.must_change_password = False
    _revoke_user_sessions(db, current_user.id, "password_change")
    _record_security_event(db, request, "password_change", "success", current_user.id)
    db.commit()
    _clear_auth_cookies(response)
    return {"message": "Password changed successfully"}


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    current_id = getattr(request.state, "session_id", None)
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
        .order_by(UserSession.last_used_at.desc())
    ).all()
    return [
        SessionResponse(
            id=row.id,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            current=row.id == current_id,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def terminate_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    session = db.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
        )
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session.revoked_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/signout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def signout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    raw_refresh = request.cookies.get(settings.auth_refresh_cookie_name)
    session: UserSession | None = None
    if raw_refresh:
        session = db.scalar(
            select(UserSession).where(UserSession.refresh_token_hash == hash_refresh_token(raw_refresh))
        )
    if session is None:
        authorization = request.headers.get("authorization", "")
        raw_access = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        claims = decode_access_claims(raw_access) if raw_access else None
        session_id = claims.get("sid") if claims else None
        if session_id:
            candidate = db.get(UserSession, str(session_id))
            if candidate and str(candidate.user_id) == str(claims.get("sub")):
                session = candidate
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        _record_security_event(db, request, "signout", "success", session.user_id)
        db.commit()
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
