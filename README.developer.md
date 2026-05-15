# Nerkhban Developer Guide

This is the day-to-day setup guide for local development.

## Stack

- Desktop: Electron
- Frontend: React 18 + TypeScript + Vite
- Backend: FastAPI + SQLAlchemy + Pydantic
- DB: PostgreSQL

## Repo layout

```text
backend/      FastAPI app, auth, pricing services
frontend/     React app
electron/     Electron main/preload
docker-compose.yaml
```

## Prerequisites

- Node.js 18+
- npm 9+
- Python 3.11+
- Docker

## Install

```bash
npm install
cd frontend && npm install && cd ..

cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cd ..
```

## Run

Start Postgres:

```bash
docker compose up -d postgres
```

Start backend:

```bash
npm run backend
```

Start frontend + Electron:

```bash
npm run dev
```

## Main backend endpoints

- `GET /health`
- `GET /api/auth/me`
- `GET /api/prices`
- `GET /api/prices/health`
- `GET /api/providers`

## Pricing behavior (current)

- Per-asset provider chains (`gold`, `silver`, `usdt`, `btc`)
- Iran and international chains run independently
- Primary provider falls back to backup on failure
- If both fail, last value is read from `backend/price_cache.json`
- Asset responses include chain status: `live`, `cached`, or `unavailable`

## Smoke test

```bash
python backend/scripts/integration_smoke_test.py
```

## Notes

- Some providers need API keys (`METALS_DEV_API_KEY`, `GOLDAPI_API_KEY`)
- Startup checks read `PRICING_REQUIRE_PROVIDER_KEYS`:
  - `false` (default): app starts and uses backup/cache when keys are missing
  - `true`: app fails fast if required keys are missing
