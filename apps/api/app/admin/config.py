from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from ..config import settings


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class AdminRuntimeConfig:
    frontend_origin: str
    cookie_name: str
    cookie_secure: bool
    cookie_samesite: Literal["lax", "strict", "none"]
    cookie_domain: str | None
    session_duration_minutes: int
    reauthentication_minutes: int
    ip_allowlist: str
    trusted_proxy_ips: str
    bind_ip: bool
    bind_user_agent: bool
    frontend_enabled: bool
    private_network_only: bool
    login_failure_limit: int
    lockout_minutes: int


@lru_cache(maxsize=1)
def get_admin_config() -> AdminRuntimeConfig:
    """Admin runtime settings.

    Values come from the shared Settings object so that a `.env` file and the
    process environment cannot disagree. Reading os.environ directly here meant
    the admin layer silently used its own defaults whenever the application was
    started outside Docker, including a frontend origin that did not match the
    one CORS allowed.
    """
    same_site_raw = os.getenv(
        "ADMIN_COOKIE_SAMESITE", settings.auth_cookie_samesite
    ).strip().lower()
    same_site: Literal["lax", "strict", "none"] = (
        same_site_raw if same_site_raw in {"lax", "strict", "none"} else "strict"
    )
    cookie_secure = _env_bool("ADMIN_COOKIE_SECURE", settings.auth_cookie_secure)
    if same_site == "none" and not cookie_secure:
        same_site = "strict"
    domain = (settings.admin_cookie_domain or "").strip() or None
    return AdminRuntimeConfig(
        frontend_origin=settings.admin_frontend_origin.rstrip("/"),
        cookie_name=settings.admin_cookie_name.strip() or "nerkhbaan_admin_session",
        cookie_secure=cookie_secure,
        cookie_samesite=same_site,
        cookie_domain=domain,
        session_duration_minutes=_env_int(
            "ADMIN_SESSION_DURATION_MINUTES",
            settings.admin_session_minutes,
            5,
            240,
        ),
        reauthentication_minutes=_env_int(
            "ADMIN_REAUTH_DURATION_MINUTES",
            settings.admin_reauth_minutes,
            1,
            15,
        ),
        ip_allowlist=settings.admin_ip_allowlist.strip(),
        trusted_proxy_ips=os.getenv(
            "ADMIN_TRUSTED_PROXY_IPS", settings.trusted_proxy_ips
        ).strip(),
        bind_ip=_env_bool("ADMIN_SESSION_BIND_IP", False),
        bind_user_agent=_env_bool("ADMIN_SESSION_BIND_USER_AGENT", True),
        frontend_enabled=settings.admin_frontend_enabled,
        private_network_only=settings.admin_private_network_only,
        login_failure_limit=_env_int(
            "ADMIN_LOGIN_FAILURE_LIMIT", settings.admin_login_failure_limit, 3, 10
        ),
        lockout_minutes=_env_int(
            "ADMIN_LOCKOUT_MINUTES", settings.admin_lockout_minutes, 5, 1440
        ),
    )
