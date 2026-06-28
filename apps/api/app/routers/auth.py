import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from ..security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Recovery codes are short-lived to limit the brute-force window.
RESET_CODE_TTL_MINUTES = 15

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)) -> AuthResponse:
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
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))

@router.post("/signin", response_model=AuthResponse)
def signin(payload: UserSignin, db: Session = Depends(get_db)) -> AuthResponse:
    identifier = payload.username_or_email.lower()
    
    # Retrieve user by either email or username
    user = db.scalar(
        select(User).where(
            (User.email == identifier) | (User.username == identifier)
        )
    )
    
    # Verify the provided password against the stored hash
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(str(user.id))
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))

@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
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
        # Delivery is handled out-of-band (SMTP/SES). Until that is wired up the
        # code is logged so the flow remains testable without leaking to clients.
        logger.info("Password reset code for %s: %s", user.email, code)

    return {"message": "If an account exists for that email, a recovery code has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
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