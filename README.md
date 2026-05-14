# Nerkhban

Nerkhban is a bilingual (Persian/English) desktop app prototype for market monitoring and alert management.

Built with Electron + React, it focuses on a fast desktop UX, clear charting, and a localized interface (RTL/LTR).

Docs: [Project Overview](README.md) | [Developer Guide](README.developer.md)

## Why It Is Interesting

- Desktop-first experience for fintech workflows
- Bilingual UI with direction-aware layouts
- Clean dashboard and alert-management flow
- Secure Electron defaults with a minimal preload bridge

## Current MVP Includes

- Demo sign-in flow
- Mock market data and interactive charts
- Alert list management (enable/disable, delete)
- Theme/language/notification preferences saved locally

## Quick Start

```bash
# 1) Database
docker compose up -d postgres

# 2) Backend
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
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

Or start backend + database with Docker Compose:

```bash
docker compose up -d postgres backend
```

Run API smoke test (signup/signin/prices):

```bash
python backend/scripts/integration_smoke_test.py
```

## Developer Docs

For full setup, scripts, architecture, constraints, and roadmap details, see:

- `README.developer.md`
