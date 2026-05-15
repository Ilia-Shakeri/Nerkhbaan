# Nerkhban

Nerkhban is a desktop app (Electron + React) for tracking market prices and managing alerts in Persian and English.

## What is in the repo today

- Desktop shell with a custom title bar
- React frontend with RTL/LTR language support
- FastAPI backend with JWT auth and PostgreSQL
- Live pricing endpoint with provider fallback + cache

## Quick start

```bash
# 1) Start Postgres
docker compose up -d postgres

# 2) Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3) Frontend + Electron (new terminal)
cd ..
npm install
cd frontend && npm install && cd ..
npm run dev
```

## Useful endpoints

- `GET /health`
- `GET /api/prices`
- `GET /api/prices/health`
- `GET /api/providers`

## Developer docs

See `README.developer.md` for project structure, scripts, and backend/frontend details.
