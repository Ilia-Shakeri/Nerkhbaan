-- A transactional generation invalidates completed chart snapshots on every
-- source edit, deletion, insertion and truncation, including older history.
CREATE TABLE public.canonical_history_versions (
    instrument_id VARCHAR(64) PRIMARY KEY,
    generation BIGINT NOT NULL DEFAULT 1
);

INSERT INTO public.canonical_history_versions (instrument_id)
SELECT DISTINCT instrument_id FROM public.canonical_quotes;

CREATE FUNCTION public.update_canonical_history_version()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE instrument TEXT;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        UPDATE public.canonical_history_versions SET generation = generation + 1;
        RETURN NULL;
    END IF;
    FOR instrument IN
        SELECT DISTINCT value FROM unnest(ARRAY[
            CASE WHEN TG_OP <> 'INSERT' THEN OLD.instrument_id END,
            CASE WHEN TG_OP <> 'DELETE' THEN NEW.instrument_id END
        ]) AS names(value) WHERE value IS NOT NULL ORDER BY value
    LOOP
        INSERT INTO public.canonical_history_versions (instrument_id, generation)
        VALUES (instrument, 1)
        ON CONFLICT (instrument_id) DO UPDATE
            SET generation = public.canonical_history_versions.generation + 1;
    END LOOP;
    RETURN NULL;
END;
$$;

CREATE TRIGGER canonical_history_version_sync
AFTER INSERT OR UPDATE OR DELETE ON public.canonical_quotes
FOR EACH ROW EXECUTE FUNCTION public.update_canonical_history_version();

CREATE TRIGGER canonical_history_version_truncate
AFTER TRUNCATE ON public.canonical_quotes
FOR EACH STATEMENT EXECUTE FUNCTION public.update_canonical_history_version();
