-- Keep the permission tree compact and outside compressed history. Source rows
-- remain authoritative and are checked again before returning a quote.
CREATE FUNCTION public.canonical_permission_summary(summary JSONB, depth INTEGER DEFAULT 0)
RETURNS JSONB LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE result JSONB; children JSONB;
BEGIN
    IF jsonb_typeof(summary) <> 'object' THEN RETURN summary; END IF;
    SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb) INTO result
    FROM jsonb_each(summary)
    WHERE key IN ('provider_ids','primary_provider_id','candidate_provider_id',
                  'previous_provider_id','derived','historical_backfill','timestamp_precision');
    IF summary ? 'inputs' AND depth < 7 THEN
        IF jsonb_typeof(summary->'inputs') = 'array' THEN
            SELECT COALESCE(jsonb_agg(jsonb_build_object('source_summary',
                public.canonical_permission_summary(value->'source_summary', depth+1))), '[]'::jsonb)
            INTO children FROM jsonb_array_elements(summary->'inputs');
        ELSE children := summary->'inputs'; END IF;
        result := result || jsonb_build_object('inputs', children);
    END IF;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.canonical_lookup_summary(summary JSONB)
RETURNS JSONB LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT public.canonical_permission_summary(summary, 0);
$$;

ALTER TABLE public.canonical_quote_read_index ADD COLUMN candidate_price NUMERIC(30,10);

CREATE OR REPLACE FUNCTION public.update_canonical_quote_read_index()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        DELETE FROM public.canonical_quote_read_index
        WHERE id = OLD.id AND canonical_at = OLD.canonical_at;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO public.canonical_quote_read_index
            (id, canonical_at, instrument_id, observed_at, status,
             candidate_provider_id, candidate_price, source_summary)
        VALUES (NEW.id, NEW.canonical_at, NEW.instrument_id, NEW.observed_at,
                NEW.status, NEW.candidate_provider_id, NEW.candidate_price,
                public.canonical_lookup_summary(NEW.source_summary))
        ON CONFLICT (id, canonical_at) DO UPDATE SET
            instrument_id = EXCLUDED.instrument_id, observed_at = EXCLUDED.observed_at,
            status = EXCLUDED.status, candidate_provider_id = EXCLUDED.candidate_provider_id,
            candidate_price = EXCLUDED.candidate_price, source_summary = EXCLUDED.source_summary;
    END IF;
    RETURN NULL;
END;
$$;

UPDATE public.canonical_quote_read_index AS lookup SET
    source_summary = public.canonical_lookup_summary(source.source_summary),
    candidate_price = source.candidate_price
FROM public.canonical_quotes AS source
WHERE source.id = lookup.id AND source.canonical_at = lookup.canonical_at;
ANALYZE public.canonical_quote_read_index;
