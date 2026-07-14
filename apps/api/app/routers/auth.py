import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import PasswordReset, User
from ..schemas import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserResponse,
    UserSignin,
)
from ..security import (
    create_access_token,
    get_client_ip,
    hash_password,
    rate_limit_clear,
    rate_limit_hit,
    rate_limit_status,
    send_email,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Recovery codes are short-lived to limit the brute-force window.
RESET_CODE_TTL_MINUTES = 15
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
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


def _set_auth_cookie(response: Response, token: str) -> None:
    if not settings.auth_cookie_enabled:
        return
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    _enforce_request_limit(request, "signup", "account", 8, 60 * 60)
    # Check if the email or username already exists in the database
    existing_user = db.scalar(
        select(User).where(
            (User.email == payload.email.lower()) | (User.username == payload.username.lower())
        )
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Email or username is already registered"
        )

    # Hash the password and persist the new user
    user = User(
        username=payload.username.lower(),
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Generate a JWT token for the new user session
    token = create_access_token(str(user.id))
    _set_auth_cookie(response, token)
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))

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
        "signin-failure",
        login_identity,
        LOGIN_FAILURE_LIMIT,
        LOGIN_FAILURE_WINDOW_SECONDS,
    )
    if failure_state.count >= LOGIN_FAILURE_LIMIT:
        _raise_rate_limit(failure_state.retry_after)
    
    # Retrieve user by either email or username
    user = db.scalar(
        select(User).where(
            (User.email == identifier) | (User.username == identifier)
        )
    )
    
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    if not user or not password_valid:
        rate_limit_hit(
            "signin-failure",
            login_identity,
            LOGIN_FAILURE_LIMIT,
            LOGIN_FAILURE_WINDOW_SECONDS,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    rate_limit_clear("signin-failure", login_identity)
    token = create_access_token(str(user.id))
    _set_auth_cookie(response, token)
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))

@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _enforce_request_limit(
        request,
        "password-recovery",
        payload.email.lower(),
        5,
        15 * 60,
    )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # Only provision a code for a real account, but always return the same
    # response so the endpoint cannot be used to enumerate registered emails.
    if user:
        code = f"{secrets.randbelow(1_000_000):06d}"
        reset = PasswordReset(
            user_id=user.id,
            code_hash=hash_password(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=RESET_CODE_TTL_MINUTES),
        )
        db.add(reset)
        db.commit()
        delivered = send_email(
            user.email,
            "Nerkhbaan password recovery",
            f"Your password recovery code is {code}. It expires in {RESET_CODE_TTL_MINUTES} minutes.",
        )
        if not delivered:
            db.delete(reset)
            db.commit()
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
            .where(
                PasswordReset.user_id == user.id,
                PasswordReset.used.is_(False),
            )
            .order_by(PasswordReset.created_at.desc())
        )
        if (
            reset
            and reset.expires_at > datetime.now(UTC)
            and verify_password(payload.code, reset.code_hash)
        ):
            user.password_hash = hash_password(payload.new_password)
            reset.used = True
            db.commit()
            rate_limit_clear("password-reset", recovery_identity)
            return {"message": "Password updated successfully."}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired recovery code",
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
def signout(response: Response) -> Response:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
