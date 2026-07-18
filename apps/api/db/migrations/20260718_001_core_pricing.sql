CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ,
    security_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS security_version INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS ix_users_username ON public.users (username);
CREATE INDEX IF NOT EXISTS ix_users_email ON public.users (email);

CREATE TABLE IF NOT EXISTS public.password_resets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    code_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_password_resets_user_id ON public.password_resets (user_id);

CREATE TABLE IF NOT EXISTS public.push_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    endpoint VARCHAR(500) NOT NULL UNIQUE,
    p256dh VARCHAR(255) NOT NULL,
    auth VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user_id ON public.push_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS public.notification_preferences (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    push_app BOOLEAN NOT NULL DEFAULT TRUE,
    sms_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sms_phone VARCHAR(32),
    sms_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    email_address VARCHAR(255),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_id VARCHAR(64),
    telegram_verified BOOLEAN NOT NULL DEFAULT FALSE,
    silent_mode BOOLEAN NOT NULL DEFAULT FALSE,
    aggressive_alerts BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.otp_verifications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    channel VARCHAR(16) NOT NULL,
    destination VARCHAR(255) NOT NULL,
    code_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_otp_verifications_user_id ON public.otp_verifications (user_id);

CREATE TABLE IF NOT EXISTS public.assistant_chat_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL DEFAULT 'New chat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_assistant_chat_sessions_user_id ON public.assistant_chat_sessions (user_id);

CREATE TABLE IF NOT EXISTS public.assistant_chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES public.assistant_chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_assistant_chat_messages_session_id ON public.assistant_chat_messages (session_id);

CREATE TABLE IF NOT EXISTS public.support_tickets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    subject VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    assigned_admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    last_message TEXT NOT NULL DEFAULT '',
    last_admin_response_at TIMESTAMPTZ,
    last_user_response_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_support_status CHECK (status IN ('open','in_progress','waiting_for_user','resolved','closed')),
    CONSTRAINT ck_support_priority CHECK (priority IN ('low','normal','high','urgent'))
);

CREATE TABLE IF NOT EXISTS public.support_messages (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES public.support_tickets(id) ON DELETE CASCADE,
    from_user VARCHAR(10) NOT NULL DEFAULT 'user',
    admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    is_internal BOOLEAN NOT NULL DEFAULT FALSE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.support_tickets
    ADD COLUMN IF NOT EXISTS priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS assigned_admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS last_admin_response_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_user_response_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

ALTER TABLE public.support_messages
    ADD COLUMN IF NOT EXISTS admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON public.support_tickets (user_id);
CREATE INDEX IF NOT EXISTS ix_support_tickets_status_priority ON public.support_tickets (status, priority, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_support_tickets_assigned_admin ON public.support_tickets (assigned_admin_id, status);
CREATE INDEX IF NOT EXISTS ix_support_messages_ticket_id ON public.support_messages (ticket_id, created_at);

CREATE TABLE IF NOT EXISTS public.instruments (
    instrument_id VARCHAR(64) PRIMARY KEY,
    base_asset VARCHAR(24) NOT NULL,
    quote_currency VARCHAR(16) NOT NULL,
    market VARCHAR(32) NOT NULL,
    region VARCHAR(32) NOT NULL,
    weight_unit VARCHAR(16),
    purity VARCHAR(16),
    display_decimals INTEGER NOT NULL,
    operational_ttl_seconds INTEGER NOT NULL,
    stale_after_seconds INTEGER NOT NULL,
    expire_after_seconds INTEGER NOT NULL,
    base_anomaly_threshold_percent NUMERIC(9,4) NOT NULL,
    maximum_dynamic_threshold_percent NUMERIC(9,4) NOT NULL,
    minimum_sanity_price NUMERIC(24,8) NOT NULL,
    maximum_sanity_price NUMERIC(24,8) NOT NULL,
    importance INTEGER NOT NULL DEFAULT 5,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    allow_derived_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_instrument_ttl_order CHECK (
        operational_ttl_seconds > 0
        AND stale_after_seconds >= operational_ttl_seconds
        AND expire_after_seconds > stale_after_seconds
    ),
    CONSTRAINT ck_instrument_sanity_bounds CHECK (minimum_sanity_price > 0 AND maximum_sanity_price > minimum_sanity_price)
);

INSERT INTO public.instruments (
    instrument_id, base_asset, quote_currency, market, region, weight_unit, purity,
    display_decimals, operational_ttl_seconds, stale_after_seconds, expire_after_seconds,
    base_anomaly_threshold_percent, maximum_dynamic_threshold_percent,
    minimum_sanity_price, maximum_sanity_price, importance, allow_derived_fallback
) VALUES
    ('GOLD_18K_TOMAN_GRAM','gold','TOMAN','physical','IR','gram','750',0,300,900,3600,1.5000,5.0000,100000,100000000,10,TRUE),
    ('XAU_USD_OZ','gold','USD','spot','GLOBAL','troy_ounce','9999',2,300,900,3600,1.2500,5.0000,100,20000,9,FALSE),
    ('SILVER_999_TOMAN_GRAM','silver','TOMAN','physical','IR','gram','999',0,600,1800,7200,2.0000,7.0000,1000,10000000,7,TRUE),
    ('SILVER_925_TOMAN_GRAM','silver','TOMAN','theoretical','IR','gram','925',0,600,1800,7200,2.0000,7.0000,1000,10000000,5,TRUE),
    ('XAG_USD_OZ','silver','USD','spot','GLOBAL','troy_ounce','999',3,600,1800,7200,2.0000,7.0000,1,1000,6,FALSE),
    ('USDT_TOMAN','usdt','TOMAN','exchange','IR',NULL,NULL,0,60,180,900,1.0000,4.0000,1000,10000000,10,TRUE),
    ('USDT_USD','usdt','USD','exchange','GLOBAL',NULL,NULL,4,60,180,900,1.0000,4.0000,0.5,2,8,FALSE),
    ('BTC_TOMAN','btc','TOMAN','exchange','IR',NULL,NULL,0,60,180,900,2.0000,8.0000,1000000,100000000000,10,TRUE),
    ('BTC_USD','btc','USD','exchange','GLOBAL',NULL,NULL,2,60,180,900,2.0000,8.0000,1000,10000000,10,FALSE)
ON CONFLICT (instrument_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.pricing_providers (
    provider_id VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(120) NOT NULL,
    source_type VARCHAR(24) NOT NULL DEFAULT 'http',
    role VARCHAR(16) NOT NULL DEFAULT 'fallback',
    priority INTEGER NOT NULL DEFAULT 100,
    trust_score NUMERIC(5,4) NOT NULL DEFAULT 0.5000,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    required_key_name VARCHAR(120),
    parser_name VARCHAR(120) NOT NULL,
    parser_version VARCHAR(32) NOT NULL,
    requests_per_minute INTEGER NOT NULL DEFAULT 10,
    requests_per_hour INTEGER NOT NULL DEFAULT 100,
    requests_per_day INTEGER NOT NULL DEFAULT 1000,
    reserved_anomaly_requests INTEGER NOT NULL DEFAULT 10,
    reserved_fallback_requests INTEGER NOT NULL DEFAULT 20,
    minimum_interval_seconds INTEGER NOT NULL DEFAULT 60,
    cooldown_after_429_seconds INTEGER NOT NULL DEFAULT 900,
    estimated_request_cost NUMERIC(10,4) NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.instrument_provider_configs (
    instrument_id VARCHAR(64) NOT NULL REFERENCES public.instruments(instrument_id) ON DELETE CASCADE,
    provider_id VARCHAR(64) NOT NULL REFERENCES public.pricing_providers(provider_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    role VARCHAR(16) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    trust_score NUMERIC(5,4),
    operational_ttl_seconds INTEGER,
    minimum_price NUMERIC(24,8),
    maximum_price NUMERIC(24,8),
    maximum_verification_depth INTEGER NOT NULL DEFAULT 2,
    parser_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, provider_id)
);

CREATE TABLE IF NOT EXISTS public.provider_quotes (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY,
    instrument_id VARCHAR(64) NOT NULL,
    provider_id VARCHAR(64) NOT NULL,
    source_type VARCHAR(24) NOT NULL,
    price NUMERIC(24,8),
    currency VARCHAR(16) NOT NULL,
    weight_unit VARCHAR(16),
    purity VARCHAR(16),
    bid NUMERIC(24,8),
    ask NUMERIC(24,8),
    volume NUMERIC(30,8),
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    latency_ms INTEGER,
    http_status INTEGER,
    parser_version VARCHAR(32) NOT NULL,
    validation_status VARCHAR(24) NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    is_direct BOOLEAN NOT NULL DEFAULT TRUE,
    is_derived BOOLEAN NOT NULL DEFAULT FALSE,
    is_suspicious BOOLEAN NOT NULL DEFAULT FALSE,
    rejection_reason VARCHAR(240),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload_reference VARCHAR(160),
    persistence_status VARCHAR(24) NOT NULL DEFAULT 'persisted',
    idempotency_key VARCHAR(160) NOT NULL,
    quote_role VARCHAR(24) NOT NULL DEFAULT 'normal',
    PRIMARY KEY (id, observed_at),
    UNIQUE (idempotency_key, observed_at)
);

CREATE INDEX IF NOT EXISTS ix_provider_quotes_instrument_time ON public.provider_quotes (instrument_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_provider_quotes_provider_time ON public.provider_quotes (provider_id, instrument_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_provider_quotes_validation_time ON public.provider_quotes (validation_status, observed_at DESC);

CREATE TABLE IF NOT EXISTS public.canonical_quotes (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY,
    instrument_id VARCHAR(64) NOT NULL,
    price NUMERIC(24,8) NOT NULL,
    status VARCHAR(32) NOT NULL,
    primary_quote_id BIGINT,
    verification_quote_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_price NUMERIC(24,8),
    candidate_provider_id VARCHAR(64),
    observed_at TIMESTAMPTZ NOT NULL,
    canonical_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until TIMESTAMPTZ NOT NULL,
    stale_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    is_persisted BOOLEAN NOT NULL DEFAULT TRUE,
    decision_reason VARCHAR(240) NOT NULL,
    verification_status VARCHAR(32) NOT NULL DEFAULT 'not_required',
    change_1h NUMERIC(12,6),
    change_24h NUMERIC(12,6),
    change_7d NUMERIC(12,6),
    change_30d NUMERIC(12,6),
    idempotency_key VARCHAR(160) NOT NULL,
    sequence_number BIGINT,
    PRIMARY KEY (id, canonical_at),
    UNIQUE (idempotency_key, canonical_at)
);

CREATE INDEX IF NOT EXISTS ix_canonical_quotes_instrument_time ON public.canonical_quotes (instrument_id, canonical_at DESC);
CREATE INDEX IF NOT EXISTS ix_canonical_quotes_status_time ON public.canonical_quotes (status, canonical_at DESC);

CREATE TABLE IF NOT EXISTS public.pricing_anomalies (
    id BIGSERIAL PRIMARY KEY,
    instrument_id VARCHAR(64) NOT NULL REFERENCES public.instruments(instrument_id),
    candidate_quote_id BIGINT,
    previous_canonical_quote_id BIGINT,
    deviation_percent NUMERIC(12,6) NOT NULL,
    dynamic_threshold_percent NUMERIC(12,6) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    reason VARCHAR(240) NOT NULL,
    reviewed_by_admin_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pricing_anomalies_status_time ON public.pricing_anomalies (status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.pricing_verifications (
    id BIGSERIAL PRIMARY KEY,
    anomaly_id BIGINT REFERENCES public.pricing_anomalies(id) ON DELETE CASCADE,
    instrument_id VARCHAR(64) NOT NULL REFERENCES public.instruments(instrument_id),
    candidate_quote_id BIGINT,
    verifier_quote_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision VARCHAR(32) NOT NULL,
    tolerance_percent NUMERIC(12,6) NOT NULL,
    decision_reason VARCHAR(240) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.raw_provider_payloads (
    id BIGSERIAL PRIMARY KEY,
    provider_id VARCHAR(64) NOT NULL,
    instrument_id VARCHAR(64),
    reason VARCHAR(32) NOT NULL,
    content_type VARCHAR(80),
    sanitized_payload JSONB,
    sanitized_text TEXT,
    payload_bytes INTEGER NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_raw_provider_payloads_expiry ON public.raw_provider_payloads (expires_at);

CREATE TABLE IF NOT EXISTS public.provider_runtime_events (
    id BIGSERIAL PRIMARY KEY,
    provider_id VARCHAR(64) NOT NULL,
    instrument_id VARCHAR(64),
    event_type VARCHAR(40) NOT NULL,
    status VARCHAR(24) NOT NULL,
    latency_ms INTEGER,
    http_status INTEGER,
    sanitized_error VARCHAR(500),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_provider_runtime_events_provider_time ON public.provider_runtime_events (provider_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.pricing_backfill_jobs (
    id BIGSERIAL PRIMARY KEY,
    instrument_id VARCHAR(64) NOT NULL REFERENCES public.instruments(instrument_id),
    provider_id VARCHAR(64),
    range_start TIMESTAMPTZ NOT NULL,
    range_end TIMESTAMPTZ NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    last_error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_pricing_backfill_jobs_queue ON public.pricing_backfill_jobs (status, priority, next_attempt_at);

CREATE TABLE IF NOT EXISTS public.pricing_persistence_events (
    id BIGSERIAL PRIMARY KEY,
    stream_event_id VARCHAR(80) NOT NULL UNIQUE,
    event_type VARCHAR(40) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    persisted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_pricing_persistence_events_status ON public.pricing_persistence_events (status, created_at);

CREATE TABLE IF NOT EXISTS public.telegram_sources (
    id BIGSERIAL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    channel_id VARCHAR(80) NOT NULL UNIQUE,
    username VARCHAR(80),
    display_name VARCHAR(160) NOT NULL,
    source_type VARCHAR(24) NOT NULL DEFAULT 'channel',
    allowed_instruments JSONB NOT NULL DEFAULT '[]'::jsonb,
    role VARCHAR(16) NOT NULL DEFAULT 'verifier',
    trust_score NUMERIC(5,4) NOT NULL DEFAULT 0.5000,
    minimum_confidence NUMERIC(5,4) NOT NULL DEFAULT 0.8000,
    maximum_message_age_seconds INTEGER NOT NULL DEFAULT 300,
    maximum_deviation_percent NUMERIC(8,4) NOT NULL DEFAULT 3,
    requires_multiple_sources BOOLEAN NOT NULL DEFAULT FALSE,
    parser_type VARCHAR(80) NOT NULL,
    parser_version VARCHAR(32) NOT NULL,
    expected_patterns JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.telegram_messages (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT REFERENCES public.telegram_sources(id) ON DELETE SET NULL,
    channel_id VARCHAR(80) NOT NULL,
    chat_id VARCHAR(80) NOT NULL,
    message_id VARCHAR(80) NOT NULL,
    message_date TIMESTAMPTZ NOT NULL,
    edited_at TIMESTAMPTZ,
    message_hash VARCHAR(64) NOT NULL,
    sanitized_text TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS ix_telegram_messages_channel_date ON public.telegram_messages (channel_id, message_date DESC);

CREATE TABLE IF NOT EXISTS public.telegram_parse_results (
    id BIGSERIAL PRIMARY KEY,
    telegram_message_id BIGINT NOT NULL REFERENCES public.telegram_messages(id) ON DELETE CASCADE,
    instrument_id VARCHAR(64),
    parsed_price NUMERIC(24,8),
    currency VARCHAR(16),
    weight_unit VARCHAR(16),
    purity VARCHAR(16),
    parser_version VARCHAR(32) NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    validation_status VARCHAR(24) NOT NULL,
    rejection_reason VARCHAR(240),
    provider_quote_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_telegram_parse_results_status_time ON public.telegram_parse_results (validation_status, created_at DESC);

INSERT INTO public.canonical_quotes (
    instrument_id, price, status, source_summary, observed_at, canonical_at,
    valid_until, stale_at, expires_at, is_persisted, decision_reason, idempotency_key
)
SELECT
    mapped.instrument_id,
    mapped.price,
    'stale',
    jsonb_build_object('legacy_source', legacy.source, 'legacy_region', legacy.region),
    legacy.time,
    legacy.time,
    legacy.time,
    legacy.time,
    legacy.time,
    TRUE,
    'unambiguous_legacy_backfill',
    encode(digest(concat_ws('|', legacy.time::text, legacy.asset, legacy.region, legacy.source, mapped.instrument_id), 'sha256'), 'hex')
FROM public.market_prices AS legacy
CROSS JOIN LATERAL (
    VALUES
        (CASE WHEN lower(legacy.asset) = 'btc' AND legacy.price_toman IS NOT NULL THEN 'BTC_TOMAN' END, legacy.price_toman),
        (CASE WHEN lower(legacy.asset) = 'btc' AND legacy.price_usd IS NOT NULL THEN 'BTC_USD' END, legacy.price_usd),
        (CASE WHEN lower(legacy.asset) IN ('usdt','tether') AND legacy.price_toman IS NOT NULL THEN 'USDT_TOMAN' END, legacy.price_toman),
        (CASE WHEN lower(legacy.asset) IN ('usdt','tether') AND legacy.price_usd IS NOT NULL THEN 'USDT_USD' END, legacy.price_usd)
) AS mapped(instrument_id, price)
WHERE mapped.instrument_id IS NOT NULL AND mapped.price IS NOT NULL AND mapped.price > 0
ON CONFLICT (idempotency_key, canonical_at) DO NOTHING;
