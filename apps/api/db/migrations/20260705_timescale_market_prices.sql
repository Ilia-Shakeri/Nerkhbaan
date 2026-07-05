CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS public.market_prices (
    time TIMESTAMPTZ NOT NULL,
    asset TEXT NOT NULL,
    region TEXT NOT NULL,
    source TEXT NOT NULL,
    price_usd DOUBLE PRECISION,
    price_toman DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

SELECT create_hypertable(
    'public.market_prices',
    'time',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

CREATE INDEX IF NOT EXISTS ix_market_prices_asset_region_time
    ON public.market_prices (asset, region, time DESC);

CREATE MATERIALIZED VIEW IF NOT EXISTS public.market_prices_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset,
    region,
    first(COALESCE(price_toman, price_usd), time) AS open,
    max(COALESCE(price_toman, price_usd)) AS high,
    min(COALESCE(price_toman, price_usd)) AS low,
    last(COALESCE(price_toman, price_usd), time) AS close,
    sum(COALESCE(volume, 0)) AS volume,
    count(*) AS samples
FROM public.market_prices
GROUP BY bucket, asset, region
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS public.market_prices_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    asset,
    region,
    first(COALESCE(price_toman, price_usd), time) AS open,
    max(COALESCE(price_toman, price_usd)) AS high,
    min(COALESCE(price_toman, price_usd)) AS low,
    last(COALESCE(price_toman, price_usd), time) AS close,
    sum(COALESCE(volume, 0)) AS volume,
    count(*) AS samples
FROM public.market_prices
GROUP BY bucket, asset, region
WITH NO DATA;

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'public.market_prices_1h',
        start_offset => INTERVAL '14 days',
        end_offset => INTERVAL '5 minutes',
        schedule_interval => INTERVAL '15 minutes'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'public.market_prices_1d',
        start_offset => INTERVAL '1 year',
        end_offset => INTERVAL '1 hour',
        schedule_interval => INTERVAL '1 hour'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
