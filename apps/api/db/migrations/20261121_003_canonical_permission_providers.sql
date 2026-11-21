-- Necessary provider exclusions are cheap; source validation remains mandatory.
CREATE FUNCTION public.canonical_permission_providers(summary JSONB, depth INTEGER DEFAULT 0)
RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE result TEXT[] := '{}'; item JSONB; field TEXT; child TEXT[];
BEGIN
    IF jsonb_typeof(summary) <> 'object' OR depth > 7 THEN RETURN result; END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(CASE
        WHEN jsonb_typeof(summary->'provider_ids')='array' THEN summary->'provider_ids'
        ELSE '[]'::jsonb END) LOOP
        IF jsonb_typeof(item)='string' AND item #>> '{}' NOT LIKE 'derived:%' THEN
            result := array_append(result, item #>> '{}');
        END IF;
    END LOOP;
    FOREACH field IN ARRAY ARRAY['candidate_provider_id','previous_provider_id'] LOOP
        item := summary->field;
        IF jsonb_typeof(item)='string' AND item #>> '{}' NOT LIKE 'derived:%' THEN
            result := array_append(result, item #>> '{}');
        END IF;
    END LOOP;
    -- Direct quotes do not derive permission from incidental input metadata.
    IF depth < 7 AND (summary->>'derived'='true' OR summary->>'primary_provider_id' LIKE 'derived:%')
       AND jsonb_typeof(summary->'inputs')='array'
       AND jsonb_array_length(CASE WHEN jsonb_typeof(summary->'inputs')='array' THEN summary->'inputs' ELSE '[]'::jsonb END) BETWEEN 1 AND 16 THEN
        FOR item IN SELECT value FROM jsonb_array_elements(summary->'inputs') LOOP
            child := public.canonical_permission_providers(item->'source_summary',depth+1);
            result := result || COALESCE(child, '{}'::text[]);
        END LOOP;
    END IF;
    RETURN ARRAY(SELECT DISTINCT value FROM unnest(result) AS value ORDER BY value);
END;
$$;

ALTER TABLE public.canonical_quote_read_index
    ADD COLUMN permission_provider_ids TEXT[] NOT NULL DEFAULT '{}';

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
             candidate_provider_id, candidate_price, source_summary, permission_provider_ids)
        VALUES (NEW.id, NEW.canonical_at, NEW.instrument_id, NEW.observed_at,
                NEW.status, NEW.candidate_provider_id, NEW.candidate_price,
                public.canonical_lookup_summary(NEW.source_summary),
                public.canonical_permission_providers(NEW.source_summary,0))
        ON CONFLICT (id, canonical_at) DO UPDATE SET
            instrument_id = EXCLUDED.instrument_id, observed_at = EXCLUDED.observed_at,
            status = EXCLUDED.status, candidate_provider_id = EXCLUDED.candidate_provider_id,
            candidate_price = EXCLUDED.candidate_price, source_summary = EXCLUDED.source_summary,
            permission_provider_ids = EXCLUDED.permission_provider_ids;
    END IF;
    RETURN NULL;
END;
$$;

UPDATE public.canonical_quote_read_index
SET permission_provider_ids = public.canonical_permission_providers(source_summary,0);
CREATE INDEX ix_canonical_current_permission_order
    ON public.canonical_quote_read_index
    (instrument_id, observed_at DESC, canonical_at DESC, id DESC)
    WHERE cardinality(permission_provider_ids)>0;
CREATE INDEX ix_canonical_permission_providers
    ON public.canonical_quote_read_index USING GIN (permission_provider_ids)
    WHERE cardinality(permission_provider_ids)>0;
ANALYZE public.canonical_quote_read_index;
