import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
import bcrypt

from .config import settings

def _prehash_password(password: str) -> str:
    """
    Pre-hashes the password using SHA-256.
    Bcrypt has a hard limitation of 72 bytes. By pre-hashing with SHA-256,
    we convert any password (no matter how long) into a fixed 64-character hex string.
    This completely bypasses the 72-byte limit securely without losing entropy.
    """
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def hash_password(password: str) -> str:
    # Step 1: Pre-hash to ensure fixed length (max 64 chars)
    pre_hashed = _prehash_password(password)
    
    # Step 2: Hash with bcrypt for final secure storage
    # Bcrypt requires bytes, so we encode the hex string
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pre_hashed.encode('utf-8'), salt)
    
    # Return as a standard string for the database
    return hashed_bytes.decode('utf-8')

def verify_password(plain_password: str, password_hash: str) -> bool:
    # Step 1: Pre-hash the incoming attempt exactly like we did during signup
    pre_hashed = _prehash_password(plain_password)
    
    # Step 2: Verify against the stored bcrypt hash using bytes
    return bcrypt.checkpw(
        pre_hashed.encode('utf-8'), 
        password_hash.encode('utf-8')
    )

def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return payload.get("sub")
