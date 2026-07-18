from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal


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
    same_site_raw = os.getenv("ADMIN_COOKIE_SAMESITE", "strict").strip().lower()
    same_site: Literal["lax", "strict", "none"] = (
        same_site_raw if same_site_raw in {"lax", "strict", "none"} else "strict"
    )
    cookie_secure = _env_bool("ADMIN_COOKIE_SECURE", True)
    if same_site == "none" and not cookie_secure:
        same_site = "strict"
    domain = os.getenv("ADMIN_COOKIE_DOMAIN", "").strip() or None
    return AdminRuntimeConfig(
        frontend_origin=os.getenv("ADMIN_FRONTEND_ORIGIN", "http://localhost:4174").rstrip("/"),
        cookie_name=os.getenv("ADMIN_COOKIE_NAME", "nerkhbaan_admin_session").strip()
        or "nerkhbaan_admin_session",
        cookie_secure=cookie_secure,
        cookie_samesite=same_site,
        cookie_domain=domain,
        session_duration_minutes=_env_int(
            "ADMIN_SESSION_DURATION_MINUTES",
            _env_int("ADMIN_SESSION_MINUTES", 30, 5, 480),
            5,
            480,
        ),
        reauthentication_minutes=_env_int(
            "ADMIN_REAUTH_DURATION_MINUTES",
            _env_int("ADMIN_REAUTH_MINUTES", 5, 1, 15),
            1,
            15,
        ),
        ip_allowlist=os.getenv("ADMIN_IP_ALLOWLIST", "").strip(),
        trusted_proxy_ips=os.getenv(
            "ADMIN_TRUSTED_PROXY_IPS",
            os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1"),
        ).strip(),
        bind_ip=_env_bool("ADMIN_SESSION_BIND_IP", False),
        bind_user_agent=_env_bool("ADMIN_SESSION_BIND_USER_AGENT", True),
        frontend_enabled=_env_bool("ADMIN_FRONTEND_ENABLED", True),
        private_network_only=_env_bool("ADMIN_PRIVATE_NETWORK_ONLY", False),
        login_failure_limit=_env_int("ADMIN_LOGIN_FAILURE_LIMIT", 5, 3, 10),
        lockout_minutes=_env_int("ADMIN_LOCKOUT_MINUTES", 30, 5, 1440),
    )
