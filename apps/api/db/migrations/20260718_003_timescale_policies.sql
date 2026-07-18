SELECT create_hypertable(
    'public.provider_quotes',
    'observed_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

SELECT create_hypertable(
    'public.canonical_quotes',
    'canonical_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS public.canonical_quotes_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', canonical_at) AS bucket,
    instrument_id,
    first(price, canonical_at) AS open,
    max(price) AS high,
    min(price) AS low,
    last(price, canonical_at) AS close,
    count(*) AS samples
FROM public.canonical_quotes
WHERE status IN ('live','confirmed','fresh_cache','derived_fallback','stale','unpersisted')
GROUP BY bucket, instrument_id
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS public.canonical_quotes_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', canonical_at) AS bucket,
    instrument_id,
    first(price, canonical_at) AS open,
    max(price) AS high,
    min(price) AS low,
    last(price, canonical_at) AS close,
    count(*) AS samples
FROM public.canonical_quotes
WHERE status IN ('live','confirmed','fresh_cache','derived_fallback','stale','unpersisted')
GROUP BY bucket, instrument_id
WITH NO DATA;

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'public.canonical_quotes_1h',
        start_offset => INTERVAL '45 days',
        end_offset => INTERVAL '5 minutes',
        schedule_interval => INTERVAL '15 minutes'
    );
EXCEPTION
    WHEN duplicate_object OR unique_violation THEN NULL;
END $$;

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'public.canonical_quotes_1d',
        start_offset => INTERVAL '420 days',
        end_offset => INTERVAL '1 hour',
        schedule_interval => INTERVAL '1 hour'
    );
EXCEPTION
    WHEN duplicate_object OR unique_violation THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE public.provider_quotes SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id,provider_id',
        timescaledb.compress_orderby = 'observed_at DESC'
    );
    PERFORM add_compression_policy('public.provider_quotes', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION
    WHEN undefined_function OR feature_not_supported THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE public.canonical_quotes SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'canonical_at DESC'
    );
    PERFORM add_compression_policy('public.canonical_quotes', INTERVAL '14 days', if_not_exists => TRUE);
EXCEPTION
    WHEN undefined_function OR feature_not_supported THEN NULL;
END $$;

DO $$
BEGIN
    PERFORM add_retention_policy('public.provider_quotes', INTERVAL '90 days', if_not_exists => TRUE);
    PERFORM add_retention_policy('public.canonical_quotes', INTERVAL '420 days', if_not_exists => TRUE);
EXCEPTION
    WHEN undefined_function OR feature_not_supported THEN NULL;
END $$;

CREATE OR REPLACE PROCEDURE public.purge_expired_operational_data(job_id INTEGER, config JSONB)
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.raw_provider_payloads WHERE expires_at < now();
    DELETE FROM public.otp_verifications WHERE expires_at < now() - INTERVAL '1 day';
    DELETE FROM public.password_resets WHERE expires_at < now() - INTERVAL '1 day';
    DELETE FROM public.user_sessions WHERE expires_at < now() - INTERVAL '7 days';
    DELETE FROM public.admin_sessions WHERE expires_at < now() - INTERVAL '30 days';
END;
$$;

DO $$
BEGIN
    PERFORM add_job(
        'public.purge_expired_operational_data',
        INTERVAL '1 day',
        config => '{}'::jsonb,
        initial_start => now() + INTERVAL '10 minutes'
    );
EXCEPTION
    WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
