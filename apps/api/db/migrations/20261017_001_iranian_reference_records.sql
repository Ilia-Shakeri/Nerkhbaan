-- Reference rates keep distinct IDs; old physical and exchange records stay intact.
SET LOCAL lock_timeout = '5s';
CREATE TABLE public.pricing_reference_records (
    reference_id varchar(64) NOT NULL,
    record_kind varchar(16) NOT NULL,
    slot varchar(32) NOT NULL,
    recorded_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    payload_hash varchar(64) NOT NULL,
    payload jsonb NOT NULL,
    saved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (reference_id, record_kind, slot),
    CONSTRAINT ck_pricing_reference_kind CHECK (record_kind IN ('snapshot', 'history')),
    CONSTRAINT ck_pricing_reference_id CHECK (reference_id IN (
        'GOLD_24K_REFERENCE_TOMAN_GRAM', 'BTC_USD_IRAN_REFERENCE', 'USDT_USD_IRAN_REFERENCE'
    )),
    CONSTRAINT ck_pricing_reference_slot CHECK (
        (record_kind = 'snapshot' AND slot = 'current') OR
        (record_kind = 'history' AND slot ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}$')
    ),
    CONSTRAINT ck_pricing_reference_payload CHECK (jsonb_typeof(payload) = 'object')
);
CREATE INDEX ix_pricing_reference_history
    ON public.pricing_reference_records (reference_id, record_kind, recorded_at);
