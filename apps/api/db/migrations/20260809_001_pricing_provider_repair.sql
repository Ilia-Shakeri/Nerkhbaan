INSERT INTO public.instruments (
    instrument_id, base_asset, quote_currency, market, region, weight_unit, purity,
    display_decimals, operational_ttl_seconds, stale_after_seconds, expire_after_seconds,
    base_anomaly_threshold_percent, maximum_dynamic_threshold_percent,
    minimum_sanity_price, maximum_sanity_price, importance, allow_derived_fallback
) VALUES (
    'GOLD_24K_TOMAN_GRAM','XAU_24K','TOMAN','iran_physical','iran','gram','0.9999',
    0,60,180,900,1.5000,5.0000,100000,150000000,9,TRUE
)
ON CONFLICT (instrument_id) DO UPDATE SET
    base_asset = EXCLUDED.base_asset,
    quote_currency = EXCLUDED.quote_currency,
    market = EXCLUDED.market,
    region = EXCLUDED.region,
    weight_unit = EXCLUDED.weight_unit,
    purity = EXCLUDED.purity,
    display_decimals = EXCLUDED.display_decimals,
    operational_ttl_seconds = EXCLUDED.operational_ttl_seconds,
    stale_after_seconds = EXCLUDED.stale_after_seconds,
    expire_after_seconds = EXCLUDED.expire_after_seconds,
    base_anomaly_threshold_percent = EXCLUDED.base_anomaly_threshold_percent,
    maximum_dynamic_threshold_percent = EXCLUDED.maximum_dynamic_threshold_percent,
    minimum_sanity_price = EXCLUDED.minimum_sanity_price,
    maximum_sanity_price = EXCLUDED.maximum_sanity_price,
    importance = EXCLUDED.importance,
    allow_derived_fallback = EXCLUDED.allow_derived_fallback,
    updated_at = now();

UPDATE public.pricing_providers
SET enabled = FALSE,
    role = 'fallback',
    priority = 99,
    trust_score = LEAST(trust_score, 0.5000),
    updated_at = now()
WHERE provider_id IN ('coincap_btc', 'coincap_usdt');

UPDATE public.instrument_provider_configs
SET enabled = FALSE,
    role = 'fallback',
    priority = 99,
    updated_at = now()
WHERE provider_id IN ('coincap_btc', 'coincap_usdt');

INSERT INTO public.pricing_providers (
    provider_id, display_name, source_type, role, priority, trust_score, enabled,
    required_key_name, parser_name, parser_version, requests_per_minute,
    requests_per_hour, requests_per_day, reserved_anomaly_requests,
    reserved_fallback_requests, minimum_interval_seconds,
    cooldown_after_429_seconds, estimated_request_cost
) VALUES
    ('coinbase_btc_usd','Coinbase BTC-USD','http','primary',1,0.9400,TRUE,NULL,'coinbase_btc_usd_v1','coinbase-ticker/1.0.0',12,360,4000,20,20,30,300,1),
    ('coinbase_usdt_usd','Coinbase USDT-USD','http','primary',1,0.9300,TRUE,NULL,'coinbase_usdt_usd_v1','coinbase-ticker/1.0.0',12,360,4000,20,20,30,300,1),
    ('coingecko_btc','CoinGecko Bitcoin','http','fallback',2,0.8200,TRUE,NULL,'coingecko_bitcoin_usd_v1','coingecko-simple-price/1.0.0',10,200,2000,20,20,60,300,1),
    ('coingecko_usdt','CoinGecko Tether','http','fallback',2,0.8200,TRUE,NULL,'coingecko_tether_usd_v1','coingecko-simple-price/1.0.0',10,200,2000,20,20,60,300,1),
    ('wallex_btc_toman','Wallex BTC-Toman','http','fallback',4,0.9000,TRUE,NULL,'wallex_btc_toman_v1','wallex-market/1.0.0',12,360,5000,20,20,20,300,1),
    ('wallex_usdt_toman','Wallex USDT-Toman','http','fallback',4,0.9000,TRUE,NULL,'wallex_usdt_toman_v1','wallex-market/1.0.0',12,360,5000,20,20,20,300,1),
    ('tala_gold24_toman','TALA 24K Gold','http','fallback',10,0.7800,FALSE,'tala_api_key','tala_gold24_toman_v1','tala-rates/1.0.0',4,80,1000,10,10,60,300,1),
    ('nerkh_io_gold24','Nerkh.io Gold 24K','http','fallback',30,0.7400,FALSE,'nerkh_io_bearer_token','nerkh_io_gold24_v1','nerkh-io-lite/1.0.0',4,80,1000,10,10,120,300,1)
ON CONFLICT (provider_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    source_type = EXCLUDED.source_type,
    role = EXCLUDED.role,
    priority = EXCLUDED.priority,
    trust_score = EXCLUDED.trust_score,
    enabled = EXCLUDED.enabled,
    required_key_name = EXCLUDED.required_key_name,
    parser_name = EXCLUDED.parser_name,
    parser_version = EXCLUDED.parser_version,
    requests_per_minute = EXCLUDED.requests_per_minute,
    requests_per_hour = EXCLUDED.requests_per_hour,
    requests_per_day = EXCLUDED.requests_per_day,
    reserved_anomaly_requests = EXCLUDED.reserved_anomaly_requests,
    reserved_fallback_requests = EXCLUDED.reserved_fallback_requests,
    minimum_interval_seconds = EXCLUDED.minimum_interval_seconds,
    cooldown_after_429_seconds = EXCLUDED.cooldown_after_429_seconds,
    estimated_request_cost = EXCLUDED.estimated_request_cost,
    updated_at = now();

INSERT INTO public.instrument_provider_configs (
    instrument_id, provider_id, enabled, role, priority, trust_score,
    operational_ttl_seconds, maximum_verification_depth, parser_config
) VALUES
    ('BTC_USD','coinbase_btc_usd',TRUE,'primary',1,0.9400,30,2,'{"parser_id":"coinbase_btc_usd_v1","route_id":"coinbase_btc_usd_rest","source_family":"coinbase","venue":"coinbase"}'::jsonb),
    ('USDT_USD','coinbase_usdt_usd',TRUE,'primary',1,0.9300,30,2,'{"parser_id":"coinbase_usdt_usd_v1","route_id":"coinbase_usdt_usd_rest","source_family":"coinbase","venue":"coinbase"}'::jsonb),
    ('BTC_USD','coingecko_btc',TRUE,'fallback',2,0.8200,120,2,'{"parser_id":"coingecko_bitcoin_usd_v1","route_id":"coingecko_btc_rest","source_family":"coingecko","venue":"opaque_aggregator"}'::jsonb),
    ('USDT_USD','coingecko_usdt',TRUE,'fallback',2,0.8200,120,2,'{"parser_id":"coingecko_tether_usd_v1","route_id":"coingecko_usdt_rest","source_family":"coingecko","venue":"opaque_aggregator"}'::jsonb),
    ('BTC_TOMAN','wallex_btc_toman',TRUE,'fallback',4,0.9000,20,2,'{"parser_id":"wallex_btc_toman_v1","route_id":"wallex_btc_toman_rest","source_family":"wallex","venue":"wallex"}'::jsonb),
    ('USDT_TOMAN','wallex_usdt_toman',TRUE,'fallback',4,0.9000,20,2,'{"parser_id":"wallex_usdt_toman_v1","route_id":"wallex_usdt_toman_rest","source_family":"wallex","venue":"wallex"}'::jsonb),
    ('GOLD_24K_TOMAN_GRAM','tala_gold24_toman',FALSE,'fallback',10,0.7800,60,2,'{"parser_id":"tala_gold24_toman_v1","credential_placement":"header","venue":"opaque_aggregator"}'::jsonb),
    ('GOLD_24K_TOMAN_GRAM','nerkh_io_gold24',FALSE,'fallback',30,0.7400,120,2,'{"parser_id":"nerkh_io_gold24_v1","credential_placement":"header","unit_source":"nerkh_io_gold_unit","venue":"opaque_aggregator"}'::jsonb)
ON CONFLICT (instrument_id, provider_id) DO UPDATE SET
    enabled = EXCLUDED.enabled,
    role = EXCLUDED.role,
    priority = EXCLUDED.priority,
    trust_score = EXCLUDED.trust_score,
    operational_ttl_seconds = EXCLUDED.operational_ttl_seconds,
    maximum_verification_depth = EXCLUDED.maximum_verification_depth,
    parser_config = EXCLUDED.parser_config,
    updated_at = now();
