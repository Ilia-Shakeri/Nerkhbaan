from sqlalchemy import Engine, text


ALERT_COLUMNS_MIGRATION = """
ALTER TABLE IF EXISTS public.alerts
    ADD COLUMN IF NOT EXISTS alert_type VARCHAR(16) NOT NULL DEFAULT 'price',
    ADD COLUMN IF NOT EXISTS formula TEXT,
    ADD COLUMN IF NOT EXISTS currency_mode VARCHAR(10) NOT NULL DEFAULT 'usd',
    ADD COLUMN IF NOT EXISTS notify_webhook BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS enable_dlq BOOLEAN NOT NULL DEFAULT FALSE,
    ALTER COLUMN target_price DROP NOT NULL
"""


def apply_schema_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(ALERT_COLUMNS_MIGRATION))
