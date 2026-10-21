SET LOCAL lock_timeout = '5s';

ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS notify_voip boolean NOT NULL DEFAULT false;
ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS priority varchar(16) NOT NULL DEFAULT 'normal';
ALTER TABLE public.alert_delivery_jobs DROP CONSTRAINT IF EXISTS ck_alert_delivery_status;
ALTER TABLE public.alert_delivery_jobs ADD CONSTRAINT ck_alert_delivery_status
 CHECK (status IN ('pending','processing','sending','accepted','delivered','retrying','failed','dead','cancelled','unknown'));

CREATE TABLE IF NOT EXISTS public.admin_secrets (
 id serial PRIMARY KEY,
 key varchar(120) NOT NULL UNIQUE,
 ciphertext text NOT NULL,
 key_version integer NOT NULL DEFAULT 1,
 updated_by integer REFERENCES public.users(id) ON DELETE SET NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.communication_recipients (
 id serial PRIMARY KEY,
 owner_user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 label varchar(80) NOT NULL,
 phone_ciphertext text NOT NULL,
 phone_masked varchar(32) NOT NULL,
 consented boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_communication_recipients_owner_user_id ON public.communication_recipients(owner_user_id);
CREATE TABLE IF NOT EXISTS public.communication_events (
 id serial PRIMARY KEY,
 owner_user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
 recipient_id integer REFERENCES public.communication_recipients(id) ON DELETE SET NULL,
 channel varchar(16) NOT NULL,
 status varchar(24) NOT NULL DEFAULT 'queued',
 dry_run boolean NOT NULL DEFAULT true,
 client_request_id varchar(36) NOT NULL,
 delivery_key varchar(120) NOT NULL UNIQUE,
 provider_reference varchar(160),
 error_code varchar(80),
 attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 provider_response_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_communication_request UNIQUE(owner_user_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS ix_communication_events_owner_user_id ON public.communication_events(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_communication_events_status ON public.communication_events(status);
