"""Real HTTP routes on isolated ORM fixtures; no Timescale/migration readiness claim."""
from __future__ import annotations

from contextlib import asynccontextmanager

from browser_fixture_database import cleanup, prepare

schema, engine, async_engine = prepare()

from app.main import app
from app.pricing.service import instrument_pricing_service


@asynccontextmanager
async def fixture_lifespan(_app):
    await instrument_pricing_service.initialize()
    print(f"BROWSER_ORM_FIXTURE_READY schema={schema} migrations=not-tested timescale=not-tested redis=disabled")
    try:
        yield
    finally:
        await async_engine.dispose()
        engine.dispose()
        cleanup(schema)


app.router.lifespan_context = fixture_lifespan
app.state.browser_fixture_schema = schema


@app.get("/__fixture__/health", include_in_schema=False)
def fixture_health():
    return {"fixture": "postgresql-orm", "schema": schema, "migration_proof": False, "timescale_proof": False, "redis_proof": False}
