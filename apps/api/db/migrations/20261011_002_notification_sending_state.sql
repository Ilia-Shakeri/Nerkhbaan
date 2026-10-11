-- The delivery worker commits this state before crossing the network boundary.
-- Keep every previous state and existing row; applied migrations stay immutable.
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.alert_delivery_jobs
    DROP CONSTRAINT IF EXISTS ck_alert_delivery_status;
ALTER TABLE public.alert_delivery_jobs
    ADD CONSTRAINT ck_alert_delivery_status
    CHECK (status IN ('pending','processing','sending','delivered','retrying','failed','dead','cancelled'));
