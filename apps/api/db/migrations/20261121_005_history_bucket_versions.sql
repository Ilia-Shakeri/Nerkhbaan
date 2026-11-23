-- Whole-hour revisions keep long-chart validation independent of tick count.
-- Partial boundary hours still use exact row versions in the lookup index.
ALTER TABLE public.canonical_history_versions
    ADD COLUMN reset_generation BIGINT NOT NULL DEFAULT 0;

CREATE TABLE public.canonical_history_bucket_versions (
    instrument_id VARCHAR(64) NOT NULL,
    bucket TIMESTAMPTZ NOT NULL,
    generation BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (instrument_id, bucket)
);

INSERT INTO public.canonical_history_bucket_versions (instrument_id, bucket)
SELECT DISTINCT instrument_id,
    date_bin(INTERVAL '1 hour', canonical_at, TIMESTAMPTZ '2000-01-01 00:00:00+00')
FROM public.canonical_quotes;

CREATE INDEX ix_canonical_history_boundary
    ON public.canonical_quote_read_index (instrument_id, canonical_at, id);

CREATE FUNCTION public.update_canonical_history_bucket_version()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE changed RECORD;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        UPDATE public.canonical_history_versions
            SET reset_generation = reset_generation + 1;
        RETURN NULL;
    END IF;
    FOR changed IN
        SELECT DISTINCT instrument, hour FROM (VALUES
            (CASE WHEN TG_OP <> 'INSERT' THEN OLD.instrument_id END,
             CASE WHEN TG_OP <> 'INSERT' THEN date_bin(INTERVAL '1 hour',
                 OLD.canonical_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') END),
            (CASE WHEN TG_OP <> 'DELETE' THEN NEW.instrument_id END,
             CASE WHEN TG_OP <> 'DELETE' THEN date_bin(INTERVAL '1 hour',
                 NEW.canonical_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') END)
        ) AS changes(instrument, hour)
        WHERE instrument IS NOT NULL ORDER BY instrument, hour
    LOOP
        INSERT INTO public.canonical_history_bucket_versions (instrument_id, bucket, generation)
        VALUES (changed.instrument, changed.hour, 1)
        ON CONFLICT (instrument_id, bucket) DO UPDATE
            SET generation = public.canonical_history_bucket_versions.generation + 1;
    END LOOP;
    RETURN NULL;
END;
$$;

CREATE TRIGGER canonical_history_bucket_version_sync
AFTER INSERT OR UPDATE OR DELETE ON public.canonical_quotes
FOR EACH ROW EXECUTE FUNCTION public.update_canonical_history_bucket_version();

CREATE TRIGGER canonical_history_bucket_version_truncate
AFTER TRUNCATE ON public.canonical_quotes
FOR EACH STATEMENT EXECUTE FUNCTION public.update_canonical_history_bucket_version();

ANALYZE public.canonical_history_bucket_versions;
ANALYZE public.canonical_quote_read_index;
