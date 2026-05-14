# Nerkhban Desktop App (Developer README)

This document is the detailed developer guide.  
If you are looking for a quick project overview, see `README.md`.

Nerkhban is a bilingual (Persian/English) desktop interface for monitoring market prices and managing price alerts. The project is built with Electron for the desktop shell and React + Vite for the frontend.

## Overview

This repository currently represents a **frontend-first desktop MVP**:
- FastAPI backend with JWT authentication and PostgreSQL persistence
- Live pricing endpoint with dual-currency (USD/Toman) payloads
- Alert management UI
- Theme and language preferences persisted in local storage

It is well-suited for UI validation, desktop integration testing, and future backend/API integration.

## Key Features

- Electron desktop window with custom title bar controls
- Route protection using API-issued JWT tokens
- Dashboard with live gold/silver prices (USD + Toman toggle)
- Alert list management (toggle and delete)
- Settings for theme, language, and notification preferences
- Persian (RTL) and English (LTR) support
- Responsive layout optimized for desktop-first usage

## Tech Stack

- **Desktop shell:** Electron
- **Frontend:** React 18, TypeScript, Vite
- **Backend API:** FastAPI, SQLAlchemy, Pydantic
- **Database:** PostgreSQL 16
- **Styling:** Tailwind CSS + component primitives (Radix UI)
- **Charts:** Recharts
- **Animation:** Motion
- **Icons:** Lucide React

## Repository Structure

```text
Nerkhban-app/
├── backend/
│   ├── app/
│   │   ├── routers/            # Auth and pricing endpoints
│   │   ├── services/           # External API integrations + price aggregation
│   │   ├── main.py             # FastAPI app entrypoint
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   └── ...
│   ├── requirements.txt
│   └── .env.example
├── electron/
│   ├── main.cjs              # Electron main process
│   └── preload.js            # Secure API bridge (contextBridge)
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── components/
│   │   │   ├── context/
│   │   │   ├── layouts/
│   │   │   ├── views/
│   │   │   └── routes.tsx
│   │   ├── styles/
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yaml       # Local PostgreSQL setup
├── package.json              # Root scripts for backend + frontend + Electron orchestration
├── README.md                # Short marketing overview for GitHub visitors
└── README.developer.md      # Detailed developer documentation
```

## Prerequisites

- Node.js **18+**
- npm **9+** (recommended)
- Python **3.11+**
- Docker / Docker Compose (for PostgreSQL)
- Windows environment with Electron executable available at:
  - `C:\electron\electron.exe`

> Note: The current root `electron` script is Windows-specific. If your Electron binary is elsewhere, update the `electron` script in `package.json`.

## Installation

Install dependencies for root, frontend, and backend:

```bash
npm install
cd frontend
npm install
cd ..

cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cd ..
```

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Start backend + PostgreSQL via Compose:

```bash
docker compose up -d postgres backend
```

## Development

### Run full desktop app (Vite + Electron)

```bash
npm run dev
```

This command starts:
1. Vite dev server at `http://localhost:5173`
2. Electron window after the frontend is reachable

> Note: `npm run dev` does not launch Python automatically. Start backend separately (or use `npm run dev:full` once backend dependencies are installed and `uvicorn` is available).

### Run backend API only

```bash
npm run backend
```

API base URL: `http://localhost:8000`

### Run frontend only (browser)

```bash
cd frontend
npm run dev
```

## Build

Build the frontend production bundle:

```bash
npm run build:frontend
```

Output is generated in `frontend/dist/`.

## Available Root Scripts

- `npm run dev` - Run frontend and Electron together
- `npm run backend` - Start FastAPI backend
- `npm run dev:full` - Run backend + frontend + Electron together
- `npm run frontend` - Start frontend dev server
- `npm run electron` - Start Electron shell
- `npm run build:frontend` - Build frontend for production
- `npm start` - Alias for `npm run dev`

## Provider Catalog

Backend now includes a provider catalog endpoint at:

```bash
GET /api/providers
```

This returns the configured Iran/international market API list (TGJU, Nobitex, Tetherland, Bonbast, CoinGecko, CoinCap, Metals.dev, ExchangeRate-API, Frankfurter) for centralized backend reference.

## Smoke Test

A lightweight end-to-end API smoke test is available:

```bash
python backend/scripts/integration_smoke_test.py
```

It verifies:
- Backend health endpoint
- User signup
- User signin
- Live price payload from `/api/prices` (gold + silver)

## Security Notes

Electron is configured with secure defaults in this project:
- `contextIsolation: true`
- `nodeIntegration: false`
- Preload-only renderer access to native capabilities

The exposed renderer API is intentionally minimal (window controls + runtime metadata).

Backend security defaults:
- Password hashing with bcrypt (`passlib`)
- JWT access tokens (`python-jose`)
- Input validation through Pydantic schemas
- SQLAlchemy parameterized queries (ORM)

## Demo Access (Temporary)

For local demos without backend/database readiness, frontend includes a temporary **Enter Demo** button in the auth screen.

- Controlled by `VITE_ENABLE_DEMO_LOGIN` (default `true` in `frontend/.env.example`)
- Intended for non-production use only
- Set `VITE_ENABLE_DEMO_LOGIN=false` before deployment

## Current Scope and Limitations

- External API providers may enforce rate limits or API keys
- Alert channels (SMS/Email/Telegram) are UI-level toggles only
- No automated test suite is configured at the root level yet

## Suggested Next Steps

1. Add real authentication and token refresh flow
2. Integrate live price feeds via REST/WebSocket
3. Persist user alerts to a backend service
4. Add unit/integration tests for critical views
5. Add packaging/distribution workflow for desktop releases

## Contributing

Contributions are welcome. Please open an issue first for major changes, then submit a focused pull request with clear reproduction and validation steps.

## Project Status

Active MVP / UI prototype for desktop fintech monitoring workflows.
