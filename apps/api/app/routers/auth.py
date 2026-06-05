from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from ..db import get_db
from ..models import User
from ..schemas import AuthResponse, UserCreate, UserResponse, UserSignin
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

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

class ForgotPasswordPayload(BaseModel):
    email: EmailStr

@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordPayload):
    # Stub for the password recovery flow to be integrated with SMTP/SES
    return {"message": f"Password reset instructions sent to {payload.email}"}