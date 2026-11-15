-- Keep only lookup keys and inexpensive eligibility fields outside compressed
-- history. Price, full provenance and permission decisions remain in the source.
CREATE TABLE public.canonical_quote_read_index (
    id BIGINT NOT NULL,
    canonical_at TIMESTAMPTZ NOT NULL,
    instrument_id VARCHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL,
    candidate_provider_id VARCHAR(128),
    source_summary JSONB NOT NULL,
    PRIMARY KEY (id, canonical_at)
);

CREATE INDEX ix_canonical_quote_read_index_order
    ON public.canonical_quote_read_index
    (instrument_id, observed_at DESC, canonical_at DESC, id DESC);

CREATE FUNCTION public.canonical_lookup_summary(summary JSONB)
RETURNS JSONB LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'provider_ids', summary->'provider_ids',
        'primary_provider_id', summary->'primary_provider_id',
        'candidate_provider_id', summary->'candidate_provider_id',
        'previous_provider_id', summary->'previous_provider_id',
        'derived', summary->'derived',
        'historical_backfill', summary->'historical_backfill',
        'timestamp_precision', summary->'timestamp_precision'
    ));
$$;

CREATE FUNCTION public.update_canonical_quote_read_index()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        DELETE FROM public.canonical_quote_read_index
        WHERE id = OLD.id AND canonical_at = OLD.canonical_at;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO public.canonical_quote_read_index
            (id, canonical_at, instrument_id, observed_at, status,
             candidate_provider_id, source_summary)
        VALUES (NEW.id, NEW.canonical_at, NEW.instrument_id, NEW.observed_at,
                NEW.status, NEW.candidate_provider_id,
                public.canonical_lookup_summary(NEW.source_summary))
        ON CONFLICT (id, canonical_at) DO UPDATE SET
            instrument_id = EXCLUDED.instrument_id,
            observed_at = EXCLUDED.observed_at,
            status = EXCLUDED.status,
            candidate_provider_id = EXCLUDED.candidate_provider_id,
            source_summary = EXCLUDED.source_summary;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER canonical_quote_read_index_sync
AFTER INSERT OR UPDATE OR DELETE ON public.canonical_quotes
FOR EACH ROW EXECUTE FUNCTION public.update_canonical_quote_read_index();

INSERT INTO public.canonical_quote_read_index
    (id, canonical_at, instrument_id, observed_at, status,
     candidate_provider_id, source_summary)
SELECT id, canonical_at, instrument_id, observed_at, status,
       candidate_provider_id, public.canonical_lookup_summary(source_summary)
FROM public.canonical_quotes;

ANALYZE public.canonical_quote_read_index;
