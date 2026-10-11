-- Forward-only release migration. Existing migration checksums remain unchanged.
ALTER TABLE public.admin_mfa_profiles ADD COLUMN IF NOT EXISTS last_totp_step BIGINT;
-- Repair the old registry default while preserving an explicit operator role.
UPDATE public.pricing_providers provider SET role = 'fallback'
WHERE provider.provider_id = 'gold_api_free_xag' AND provider.role = 'verifier'
  AND NOT EXISTS (SELECT 1 FROM public.operational_settings setting
                  WHERE setting.key = 'provider.config' AND setting.scope_id = provider.provider_id
                    AND setting.value::jsonb ? 'role');
UPDATE public.instrument_provider_configs config SET role = 'fallback'
WHERE config.provider_id = 'gold_api_free_xag' AND config.role = 'verifier'
  AND NOT EXISTS (SELECT 1 FROM public.operational_settings setting
                  WHERE setting.key = 'provider.config' AND setting.scope_id = config.provider_id
                    AND setting.value::jsonb ? 'role');
-- Old worker backfills used only the provider quote role. Preserve history,
-- but prevent their primary canonical rows from becoming live snapshots.
-- Existing compressed history can exceed Timescale's default DML guard.
-- Scope the override to this bounded release transaction; the runner retains
-- its statement timeout and ordinary application transactions keep the guard.
DO $delivery$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM set_config('timescaledb.max_tuples_decompressed_per_dml_transaction', '0', true);
    END IF;
END
$delivery$;
UPDATE public.canonical_quotes canonical
SET source_summary = canonical.source_summary::jsonb || '{"historical_backfill": true}'::jsonb
WHERE COALESCE(canonical.source_summary->>'historical_backfill', 'false') <> 'true'
  AND EXISTS (SELECT 1 FROM public.provider_quotes provider
              WHERE provider.id = canonical.primary_quote_id
                AND provider.instrument_id = canonical.instrument_id
                AND (provider.quote_role = 'backfill' OR provider.metadata->>'quote_role' = 'backfill'));
CREATE INDEX IF NOT EXISTS ix_canonical_quotes_latest_live
ON public.canonical_quotes (instrument_id, observed_at DESC, canonical_at DESC, id DESC)
WHERE COALESCE(source_summary->>'historical_backfill', 'false') <> 'true';
ALTER TABLE public.instruments
    ALTER COLUMN base_asset TYPE VARCHAR(32),
    ALTER COLUMN weight_unit TYPE VARCHAR(24),
    ALTER COLUMN base_anomaly_threshold_percent TYPE NUMERIC(10,4),
    ALTER COLUMN maximum_dynamic_threshold_percent TYPE NUMERIC(10,4);

-- Unsupported legacy parser defaults are repaired; arbitrary custom names are disabled.
UPDATE public.telegram_sources SET parser_type = 'strict_explicit' WHERE parser_type = 'strict_generic';
UPDATE public.telegram_sources SET enabled = FALSE WHERE parser_type NOT IN ('strict_explicit','strict_hashtag');
-- A raw positive channel ID and its marked ID are one channel. Do not rewrite conflicts.
UPDATE public.telegram_sources source SET channel_id = '-100' || source.channel_id
WHERE source.channel_id ~ '^[1-9][0-9]*$'
  AND NOT EXISTS (SELECT 1 FROM public.telegram_sources other WHERE other.channel_id = '-100' || source.channel_id);
UPDATE public.telegram_sources source SET enabled = FALSE
WHERE source.channel_id ~ '^[1-9][0-9]*$'
  AND EXISTS (SELECT 1 FROM public.telegram_sources other WHERE other.channel_id = '-100' || source.channel_id);
UPDATE public.telegram_sources SET enabled = FALSE WHERE channel_id !~ '^-100[1-9][0-9]*$' AND username IS NULL;
UPDATE public.telegram_messages message SET channel_id = '-100' || message.channel_id
WHERE message.channel_id ~ '^[1-9][0-9]*$'
  AND NOT EXISTS (SELECT 1 FROM public.telegram_messages other
                  WHERE other.channel_id = '-100' || message.channel_id AND other.message_id = message.message_id);
