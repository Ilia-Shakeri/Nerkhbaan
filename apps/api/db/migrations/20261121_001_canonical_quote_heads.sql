-- One transactionally maintained, full source row per instrument. The lookup
-- path still checks that the source exists and applies current permissions.
CREATE TABLE public.canonical_quote_heads (
    instrument_id VARCHAR(64) PRIMARY KEY,
    quote_id BIGINT NOT NULL,
    canonical_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE FUNCTION public.update_canonical_quote_head()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        DELETE FROM public.canonical_quote_heads
        WHERE instrument_id = OLD.instrument_id
          AND quote_id = OLD.id AND canonical_at = OLD.canonical_at;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE')
       AND COALESCE(NEW.source_summary->>'historical_backfill', 'false') <> 'true'
       AND COALESCE(NEW.source_summary->>'timestamp_precision', '') <> 'day' THEN
        INSERT INTO public.canonical_quote_heads AS head
            (instrument_id, quote_id, canonical_at, observed_at, payload)
        VALUES (NEW.instrument_id, NEW.id, NEW.canonical_at, NEW.observed_at, to_jsonb(NEW))
        ON CONFLICT (instrument_id) DO UPDATE SET
            quote_id = EXCLUDED.quote_id, canonical_at = EXCLUDED.canonical_at,
            observed_at = EXCLUDED.observed_at, payload = EXCLUDED.payload
        WHERE (EXCLUDED.observed_at, EXCLUDED.canonical_at, EXCLUDED.quote_id)
            > (head.observed_at, head.canonical_at, head.quote_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER canonical_quote_head_sync
AFTER INSERT OR UPDATE OR DELETE ON public.canonical_quotes
FOR EACH ROW EXECUTE FUNCTION public.update_canonical_quote_head();

INSERT INTO public.canonical_quote_heads
    (instrument_id, quote_id, canonical_at, observed_at, payload)
SELECT source.instrument_id, source.id, source.canonical_at, source.observed_at, to_jsonb(source)
FROM (SELECT DISTINCT instrument_id FROM public.canonical_quote_read_index) AS instruments
CROSS JOIN LATERAL (
    SELECT id, canonical_at FROM public.canonical_quote_read_index
    WHERE instrument_id = instruments.instrument_id
      AND COALESCE(source_summary->>'historical_backfill', 'false') <> 'true'
      AND COALESCE(source_summary->>'timestamp_precision', '') <> 'day'
    ORDER BY observed_at DESC, canonical_at DESC, id DESC LIMIT 1
) AS selected
JOIN public.canonical_quotes AS source
  ON source.id = selected.id AND source.canonical_at = selected.canonical_at;

ANALYZE public.canonical_quote_heads;
