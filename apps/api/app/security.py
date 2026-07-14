import hashlib
import ipaddress
import logging
import smtplib
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import bcrypt
from jose import JWTError, jwt

try:
    import redis
except ImportError:  # pragma: no cover - dependency is present in production images
    redis = None

from .config import settings

logger = logging.getLogger(__name__)


def _prehash_password(password: str) -> str:
    """Normalize any password length before bcrypt's 72-byte boundary."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    pre_hashed = _prehash_password(password)
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pre_hashed.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    pre_hashed = _prehash_password(plain_password)
    try:
        return bcrypt.checkpw(
            pre_hashed.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": expire,
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    if not token or len(token) > 4096:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require_aud": True,
                "require_exp": True,
                "require_iat": True,
                "require_iss": True,
                "require_jti": True,
                "require_nbf": True,
                "require_sub": True,
            },
        )
    except JWTError:
        return None
    subject = payload.get("sub")
    if payload.get("type") != "access" or not isinstance(subject, str):
        return None
    return subject


@dataclass(frozen=True)
class RateLimitState:
    count: int
    limit: int
    retry_after: int

    @property
    def blocked(self) -> bool:
        return self.count > self.limit


_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""
_redis_client: Any | None = None
_redis_retry_at = 0.0
_rate_lock = threading.Lock()
_memory_limits: dict[str, tuple[int, float]] = {}


def _rate_key(bucket: str, identity: str) -> str:
    safe_bucket = "".join(char for char in bucket.lower() if char.isalnum() or char in "-_")[:40]
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"security:rate:{safe_bucket}:{digest}"


def _shared_rate_store() -> Any | None:
    global _redis_client, _redis_retry_at
    if redis is None or not settings.redis_url:
        return None
    now = time.monotonic()
    with _rate_lock:
        if _redis_client is not None:
            return _redis_client
        if now < _redis_retry_at:
            return None
        try:
            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            client.ping()
            _redis_client = client
        except Exception:
            _redis_retry_at = now + 30
            logger.warning("Shared rate-limit store unavailable; using process-local guard")
            return None
        return _redis_client


def _memory_rate_status(key: str, limit: int, window_seconds: int, increment: bool) -> RateLimitState:
    now = time.monotonic()
    with _rate_lock:
        count, expires_at = _memory_limits.get(key, (0, now + window_seconds))
        if expires_at <= now:
            count, expires_at = 0, now + window_seconds
        if increment:
            count += 1
        _memory_limits[key] = (count, expires_at)
    return RateLimitState(count=count, limit=limit, retry_after=max(1, int(expires_at - now)))


def rate_limit_status(bucket: str, identity: str, limit: int, window_seconds: int) -> RateLimitState:
    key = _rate_key(bucket, identity)
    client = _shared_rate_store()
    if client is None:
        return _memory_rate_status(key, limit, window_seconds, increment=False)
    try:
        raw_count = client.get(key)
        ttl = client.ttl(key) if raw_count is not None else window_seconds
        return RateLimitState(
            count=int(raw_count or 0),
            limit=limit,
            retry_after=max(1, int(ttl if ttl and ttl > 0 else window_seconds)),
        )
    except Exception:
        return _memory_rate_status(key, limit, window_seconds, increment=False)


def rate_limit_hit(bucket: str, identity: str, limit: int, window_seconds: int) -> RateLimitState:
    key = _rate_key(bucket, identity)
    client = _shared_rate_store()
    if client is None:
        return _memory_rate_status(key, limit, window_seconds, increment=True)
    try:
        count, ttl = client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
        return RateLimitState(
            count=int(count),
            limit=limit,
            retry_after=max(1, int(ttl if ttl and ttl > 0 else window_seconds)),
        )
    except Exception:
        return _memory_rate_status(key, limit, window_seconds, increment=True)


def rate_limit_clear(bucket: str, identity: str) -> None:
    key = _rate_key(bucket, identity)
    client = _shared_rate_store()
    if client is not None:
        try:
            client.delete(key)
        except Exception:
            pass
    with _rate_lock:
        _memory_limits.pop(key, None)


def get_client_ip(request: Any) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = {item.strip() for item in settings.trusted_proxy_ips.split(",") if item.strip()}
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return peer


def validate_public_https_url(value: str, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must be a public HTTPS address without credentials")
    if parsed.fragment:
        raise ValueError("URL fragments are not allowed")

    host = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private or reserved addresses are not allowed")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local addresses are not allowed")

    if allowed_hosts:
        allowed = any(host == item or host.endswith(f".{item}") for item in allowed_hosts)
        if not allowed or parsed.port not in (None, 443):
            raise ValueError("URL host is not allowed")
    return value.strip()


def send_email(recipient: str, subject: str, body: str) -> bool:
    if not settings.smtp_host or "\n" in recipient or "\r" in recipient:
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as client:
            client.ehlo()
            if settings.smtp_use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.error("Email delivery failed", exc_info=settings.debug)
        return False
    return True
