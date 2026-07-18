CREATE TABLE IF NOT EXISTS public.user_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_family VARCHAR(36) NOT NULL,
    refresh_token_hash VARCHAR(64) NOT NULL UNIQUE,
    replaced_by_session_id VARCHAR(36),
    ip_hash VARCHAR(64),
    user_agent_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    compromised_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_active ON public.user_sessions (user_id, expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_user_sessions_token_family ON public.user_sessions (token_family);

CREATE TABLE IF NOT EXISTS public.security_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    event_type VARCHAR(80) NOT NULL,
    result VARCHAR(24) NOT NULL,
    ip_hash VARCHAR(64),
    user_agent_hash VARCHAR(64),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_security_events_user_time ON public.security_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_security_events_type_time ON public.security_events (event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS public.user_notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    resource_type VARCHAR(40),
    resource_id VARCHAR(80),
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_user_notifications_user_time ON public.user_notifications (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_user_notifications_unread ON public.user_notifications (user_id, created_at DESC) WHERE read_at IS NULL;

CREATE TABLE IF NOT EXISTS public.alerts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    asset VARCHAR(20) NOT NULL,
    target_price DOUBLE PRECISION,
    alert_type VARCHAR(16) NOT NULL DEFAULT 'price',
    formula TEXT,
    currency_mode VARCHAR(10) NOT NULL DEFAULT 'usd',
    condition VARCHAR(10) NOT NULL DEFAULT 'above',
    notify_app BOOLEAN NOT NULL DEFAULT TRUE,
    notify_email BOOLEAN NOT NULL DEFAULT FALSE,
    notify_webhook BOOLEAN NOT NULL DEFAULT FALSE,
    webhook_url VARCHAR(500),
    enable_dlq BOOLEAN NOT NULL DEFAULT FALSE,
    instrument_id VARCHAR(64),
    mode VARCHAR(16) NOT NULL DEFAULT 'one_time',
    cooldown_seconds INTEGER NOT NULL DEFAULT 900,
    max_notifications_per_day INTEGER NOT NULL DEFAULT 10,
    notify_sms BOOLEAN NOT NULL DEFAULT FALSE,
    notify_telegram BOOLEAN NOT NULL DEFAULT FALSE,
    last_condition_state BOOLEAN NOT NULL DEFAULT FALSE,
    next_eligible_trigger_at TIMESTAMPTZ,
    notifications_today INTEGER NOT NULL DEFAULT 0,
    notification_day DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_alert_mode CHECK (mode IN ('one_time','recurring')),
    CONSTRAINT ck_alert_condition CHECK (condition IN ('above','below'))
);

ALTER TABLE public.alerts
    ADD COLUMN IF NOT EXISTS alert_type VARCHAR(16) NOT NULL DEFAULT 'price',
    ADD COLUMN IF NOT EXISTS formula TEXT,
    ADD COLUMN IF NOT EXISTS currency_mode VARCHAR(10) NOT NULL DEFAULT 'usd',
    ADD COLUMN IF NOT EXISTS notify_webhook BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS enable_dlq BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS mode VARCHAR(16) NOT NULL DEFAULT 'one_time',
    ADD COLUMN IF NOT EXISTS cooldown_seconds INTEGER NOT NULL DEFAULT 900,
    ADD COLUMN IF NOT EXISTS max_notifications_per_day INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS notify_sms BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notify_telegram BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_condition_state BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS next_eligible_trigger_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS notifications_today INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS notification_day DATE,
    ALTER COLUMN target_price DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_alerts_user_active ON public.alerts (user_id, is_active);
CREATE INDEX IF NOT EXISTS ix_alerts_instrument_active ON public.alerts (instrument_id, is_active);

CREATE TABLE IF NOT EXISTS public.alert_trigger_events (
    id BIGSERIAL PRIMARY KEY,
    alert_id BIGINT NOT NULL REFERENCES public.alerts(id) ON DELETE CASCADE,
    instrument_id VARCHAR(64),
    canonical_quote_id BIGINT,
    price NUMERIC(24,8),
    condition_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_alert_trigger_events_alert_time ON public.alert_trigger_events (alert_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_alert_trigger_events_status ON public.alert_trigger_events (status, created_at);

CREATE TABLE IF NOT EXISTS public.alert_delivery_jobs (
    id BIGSERIAL PRIMARY KEY,
    alert_id BIGINT NOT NULL REFERENCES public.alerts(id) ON DELETE CASCADE,
    trigger_event_id BIGINT NOT NULL REFERENCES public.alert_trigger_events(id) ON DELETE CASCADE,
    channel VARCHAR(24) NOT NULL,
    destination_reference VARCHAR(500) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_error VARCHAR(500),
    provider_response_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    dead_at TIMESTAMPTZ,
    UNIQUE (trigger_event_id, channel, destination_reference),
    CONSTRAINT ck_alert_delivery_status CHECK (status IN ('pending','processing','delivered','retrying','failed','dead','cancelled'))
);
CREATE INDEX IF NOT EXISTS ix_alert_delivery_jobs_queue ON public.alert_delivery_jobs (status, next_retry_at, created_at);
CREATE INDEX IF NOT EXISTS ix_alert_delivery_jobs_alert ON public.alert_delivery_jobs (alert_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.user_security_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ,
    sessions_revoked_before TIMESTAMPTZ,
    disabled_reason VARCHAR(240),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.user_security_profiles (
    user_id, is_active, must_change_password, failed_login_count,
    locked_until, last_login_at, password_changed_at
)
SELECT id, is_active, must_change_password, failed_login_count,
       locked_until, last_login_at, password_changed_at
FROM public.users
ON CONFLICT (user_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.admin_roles (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    description VARCHAR(240) NOT NULL DEFAULT '',
    is_system BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.admin_permissions (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(96) NOT NULL UNIQUE,
    description VARCHAR(240) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.admin_role_permissions (
    id BIGSERIAL PRIMARY KEY,
    role_id BIGINT NOT NULL REFERENCES public.admin_roles(id) ON DELETE CASCADE,
    permission_id BIGINT NOT NULL REFERENCES public.admin_permissions(id) ON DELETE CASCADE,
    UNIQUE (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS public.user_admin_roles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES public.admin_roles(id) ON DELETE CASCADE,
    assigned_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS public.admin_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    csrf_token_hash VARCHAR(64) NOT NULL,
    ip_address VARCHAR(64),
    user_agent_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    reauthenticated_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoke_reason VARCHAR(160)
);
CREATE INDEX IF NOT EXISTS ix_admin_sessions_user ON public.admin_sessions (user_id, expires_at);
CREATE INDEX IF NOT EXISTS ix_admin_sessions_active ON public.admin_sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS public.admin_mfa_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    encrypted_totp_secret TEXT,
    backup_code_digests JSONB NOT NULL DEFAULT '[]'::jsonb,
    recovery_locked_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor_admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    action VARCHAR(120) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id VARCHAR(160),
    before_data JSONB,
    after_data JSONB,
    ip_address VARCHAR(64),
    user_agent VARCHAR(512),
    request_id VARCHAR(80),
    result VARCHAR(32) NOT NULL,
    detail VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_time ON public.audit_logs (actor_admin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_resource_time ON public.audit_logs (resource_type, resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action_time ON public.audit_logs (action, created_at DESC);

CREATE TABLE IF NOT EXISTS public.support_ticket_admin_state (
    ticket_id BIGINT PRIMARY KEY REFERENCES public.support_tickets(id) ON DELETE CASCADE,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    assigned_admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    last_admin_response_at TIMESTAMPTZ,
    last_user_response_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.support_ticket_admin_state (
    ticket_id, priority, status, assigned_admin_id,
    last_admin_response_at, last_user_response_at, resolved_at, closed_at
)
SELECT id, priority, status, assigned_admin_id,
       last_admin_response_at, last_user_response_at, resolved_at, closed_at
FROM public.support_tickets
ON CONFLICT (ticket_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.support_internal_notes (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES public.support_tickets(id) ON DELETE CASCADE,
    admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_support_internal_notes_ticket ON public.support_internal_notes (ticket_id, created_at);

CREATE TABLE IF NOT EXISTS public.feature_flags (
    key VARCHAR(96) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    description VARCHAR(240) NOT NULL DEFAULT '',
    updated_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.operational_settings (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(96) NOT NULL,
    scope_id VARCHAR(160) NOT NULL DEFAULT 'global',
    value JSONB NOT NULL,
    description VARCHAR(240) NOT NULL DEFAULT '',
    is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
    version INTEGER NOT NULL DEFAULT 1,
    updated_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (key, scope_id),
    CONSTRAINT ck_operational_setting_not_secret CHECK (is_sensitive = FALSE)
);

CREATE TABLE IF NOT EXISTS public.provider_config_drafts (
    id BIGSERIAL PRIMARY KEY,
    provider_id VARCHAR(160) NOT NULL,
    before_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposed_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    impact_preview JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'draft',
    created_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    applied_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_provider_config_drafts_provider ON public.provider_config_drafts (provider_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.admin_operational_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(80) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id VARCHAR(160),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    requested_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR(500),
    next_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_admin_operational_jobs_queue ON public.admin_operational_jobs (status, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS public.admin_resource_reviews (
    id BIGSERIAL PRIMARY KEY,
    resource_type VARCHAR(80) NOT NULL,
    resource_id VARCHAR(160) NOT NULL,
    status VARCHAR(32) NOT NULL,
    note VARCHAR(1000) NOT NULL DEFAULT '',
    reviewed_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (resource_type, resource_id)
);

INSERT INTO public.admin_roles (name, description, is_system) VALUES
    ('super_admin', 'Full administrative access', TRUE),
    ('operator', 'Pricing and operations access', TRUE),
    ('support_agent', 'Support workflow access', TRUE),
    ('viewer', 'Read-only administrative access', TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.admin_permissions (key, description) VALUES
    ('admin.users.read','Read user accounts'),
    ('admin.users.manage','Manage user accounts'),
    ('admin.sessions.manage','Terminate user sessions'),
    ('admin.roles.read','Read roles and permissions'),
    ('admin.roles.manage','Manage administrative roles'),
    ('admin.support.read','Read support tickets'),
    ('admin.support.reply','Reply to support tickets'),
    ('admin.support.manage','Assign and close support tickets'),
    ('admin.pricing.read','Read pricing operations'),
    ('admin.pricing.manage','Manage pricing operations'),
    ('admin.providers.read','Read provider state'),
    ('admin.providers.manage','Manage provider settings'),
    ('admin.telegram.read','Read Telegram source state'),
    ('admin.telegram.manage','Manage Telegram sources'),
    ('admin.alerts.read','Read alert state'),
    ('admin.alerts.manage','Manage alert operations'),
    ('admin.dlq.read','Read dead-letter jobs'),
    ('admin.dlq.manage','Retry dead-letter jobs'),
    ('admin.audit.read','Read audit logs'),
    ('admin.settings.read','Read safe settings'),
    ('admin.settings.manage','Manage safe settings'),
    ('admin.health.read','Read detailed health'),
    ('admin.jobs.read','Read operational jobs'),
    ('admin.jobs.manage','Manage operational jobs')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.admin_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM public.admin_roles AS role
CROSS JOIN public.admin_permissions AS permission
WHERE role.name = 'super_admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO public.admin_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM public.admin_roles AS role
JOIN public.admin_permissions AS permission ON permission.key IN (
    'admin.users.read','admin.sessions.manage','admin.roles.read',
    'admin.support.read','admin.support.reply','admin.support.manage',
    'admin.pricing.read','admin.pricing.manage','admin.providers.read',
    'admin.providers.manage','admin.telegram.read','admin.telegram.manage',
    'admin.alerts.read','admin.alerts.manage','admin.dlq.read','admin.dlq.manage',
    'admin.health.read','admin.jobs.read','admin.jobs.manage'
)
WHERE role.name = 'operator'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO public.admin_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM public.admin_roles AS role
JOIN public.admin_permissions AS permission ON permission.key IN (
    'admin.users.read','admin.support.read','admin.support.reply','admin.support.manage'
)
WHERE role.name = 'support_agent'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO public.admin_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM public.admin_roles AS role
JOIN public.admin_permissions AS permission ON permission.key IN (
    'admin.users.read','admin.roles.read','admin.support.read','admin.pricing.read',
    'admin.providers.read','admin.telegram.read','admin.alerts.read','admin.dlq.read',
    'admin.audit.read','admin.settings.read','admin.health.read','admin.jobs.read'
)
WHERE role.name = 'viewer'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO public.feature_flags (key, enabled, description) VALUES
    ('comparison_visible', TRUE, 'Show stored provider comparison data'),
    ('derived_fallback_enabled', TRUE, 'Allow policy-controlled derived fallback'),
    ('backfill_enabled', TRUE, 'Allow background history gap jobs'),
    ('admin_frontend_enabled', TRUE, 'Enable administrative frontend access')
ON CONFLICT (key) DO NOTHING;
