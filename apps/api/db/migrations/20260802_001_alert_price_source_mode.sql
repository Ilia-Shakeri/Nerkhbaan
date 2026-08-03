ALTER TABLE IF EXISTS public.alerts
    ADD COLUMN IF NOT EXISTS price_source_mode VARCHAR(16) NOT NULL DEFAULT 'ordinary';

UPDATE public.alerts
SET price_source_mode = 'ordinary'
WHERE price_source_mode IS NULL;

ALTER TABLE IF EXISTS public.alerts
    ALTER COLUMN price_source_mode SET DEFAULT 'ordinary',
    ALTER COLUMN price_source_mode SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_alert_price_source_mode'
          AND conrelid = 'public.alerts'::regclass
    ) THEN
        ALTER TABLE public.alerts
            ADD CONSTRAINT ck_alert_price_source_mode
            CHECK (price_source_mode IN ('ordinary', 'reference', 'derived'));
    END IF;
END
$$;
