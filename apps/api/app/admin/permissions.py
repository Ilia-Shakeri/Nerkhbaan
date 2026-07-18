from __future__ import annotations

from enum import StrEnum


class AdminPermissionKey(StrEnum):
    USERS_READ = "admin.users.read"
    USERS_MANAGE = "admin.users.manage"
    SESSIONS_MANAGE = "admin.sessions.manage"
    ROLES_READ = "admin.roles.read"
    ROLES_MANAGE = "admin.roles.manage"
    SUPPORT_READ = "admin.support.read"
    SUPPORT_REPLY = "admin.support.reply"
    SUPPORT_MANAGE = "admin.support.manage"
    PRICING_READ = "admin.pricing.read"
    PRICING_MANAGE = "admin.pricing.manage"
    PROVIDERS_READ = "admin.providers.read"
    PROVIDERS_MANAGE = "admin.providers.manage"
    TELEGRAM_READ = "admin.telegram.read"
    TELEGRAM_MANAGE = "admin.telegram.manage"
    ALERTS_READ = "admin.alerts.read"
    ALERTS_MANAGE = "admin.alerts.manage"
    DLQ_READ = "admin.dlq.read"
    DLQ_MANAGE = "admin.dlq.manage"
    AUDIT_READ = "admin.audit.read"
    SETTINGS_READ = "admin.settings.read"
    SETTINGS_MANAGE = "admin.settings.manage"
    HEALTH_READ = "admin.health.read"
    JOBS_READ = "admin.jobs.read"
    JOBS_MANAGE = "admin.jobs.manage"


PERMISSION_DESCRIPTIONS: dict[AdminPermissionKey, str] = {
    permission: permission.value.replace("admin.", "").replace(".", " ").title()
    for permission in AdminPermissionKey
}

ROLE_DESCRIPTIONS = {
    "super_admin": "Full administrative control with role management.",
    "operator": "Pricing, provider, alert, job, and health operations.",
    "support_agent": "User lookup and support ticket handling.",
    "viewer": "Read-only access to operational information.",
}

ALL_PERMISSIONS = frozenset(AdminPermissionKey)

ROLE_PERMISSIONS: dict[str, frozenset[AdminPermissionKey]] = {
    "super_admin": ALL_PERMISSIONS,
    "operator": frozenset(
        {
            AdminPermissionKey.USERS_READ,
            AdminPermissionKey.SUPPORT_READ,
            AdminPermissionKey.SUPPORT_REPLY,
            AdminPermissionKey.SUPPORT_MANAGE,
            AdminPermissionKey.PRICING_READ,
            AdminPermissionKey.PRICING_MANAGE,
            AdminPermissionKey.PROVIDERS_READ,
            AdminPermissionKey.PROVIDERS_MANAGE,
            AdminPermissionKey.TELEGRAM_READ,
            AdminPermissionKey.TELEGRAM_MANAGE,
            AdminPermissionKey.ALERTS_READ,
            AdminPermissionKey.ALERTS_MANAGE,
            AdminPermissionKey.DLQ_READ,
            AdminPermissionKey.DLQ_MANAGE,
            AdminPermissionKey.AUDIT_READ,
            AdminPermissionKey.SETTINGS_READ,
            AdminPermissionKey.HEALTH_READ,
            AdminPermissionKey.JOBS_READ,
            AdminPermissionKey.JOBS_MANAGE,
        }
    ),
    "support_agent": frozenset(
        {
            AdminPermissionKey.USERS_READ,
            AdminPermissionKey.SUPPORT_READ,
            AdminPermissionKey.SUPPORT_REPLY,
            AdminPermissionKey.SUPPORT_MANAGE,
        }
    ),
    "viewer": frozenset(
        {
            AdminPermissionKey.USERS_READ,
            AdminPermissionKey.ROLES_READ,
            AdminPermissionKey.SUPPORT_READ,
            AdminPermissionKey.PRICING_READ,
            AdminPermissionKey.PROVIDERS_READ,
            AdminPermissionKey.TELEGRAM_READ,
            AdminPermissionKey.ALERTS_READ,
            AdminPermissionKey.DLQ_READ,
            AdminPermissionKey.AUDIT_READ,
            AdminPermissionKey.SETTINGS_READ,
            AdminPermissionKey.HEALTH_READ,
            AdminPermissionKey.JOBS_READ,
        }
    ),
}
