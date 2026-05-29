# 🛠️ Nerkhbaan Developer Guide

Welcome to the Nerkhbaan internal documentation. This guide covers local environment setup, architecture patterns, and testing protocols required for contributing to the codebase.

## 💻 Tech Stack
- **Desktop Wrapper:** Electron (Main/Preload processes)
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Backend:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy
- **Database:** PostgreSQL 16
- **Containerization:** Docker & Docker Compose

## 📂 Repository Structure
```text
Nerkhbaan/
├── backend/            # FastAPI microservice, async fetchers, pricing logic
├── frontend/           # React SPA, state management, UI components
├── electron/           # Electron main thread, IPC bridges
├── docker-compose.yaml # Infrastructure orchestration
└── README.developer.md # This file
```

## ⚙️ Local Development Setup

### 1. Prerequisites

Ensure you have the following installed on your machine:

* [Node.js 18+](https://nodejs.org/) & npm 9+
* [Python 3.11+](https://www.python.org/)
* [Docker Engine](https://docs.docker.com/get-docker/)

### 2. Environment Configuration

Duplicate the example environment file and populate it with your local keys:

```bash
cd backend
cp .env.example .env
```

*Note: The system checks `PRICING_REQUIRE_PROVIDER_KEYS` on startup. If set to `false`, the app boots successfully without API keys and utilizes the cache/fallback logic.*

### 3. Initialize the Database

Spin up the local PostgreSQL container:

```bash
docker compose up -d postgres
```

### 4. Start the Backend

Navigate to the `backend` directory, initialize the virtual environment, and run Uvicorn:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start the Frontend & Electron Shell

In a new terminal window at the project root:

```bash
# Install root, frontend, and electron dependencies
npm install
cd frontend && npm install && cd ..

# Launch the dev environment
npm run dev
```

## 🧠 System Behavior: The Pricing Engine

The core value of Nerkhbaan relies on its zero-downtime pricing fetcher. The logic flows as follows:

1. **Chain Execution:** Assets (`gold`, `silver`, `usdt`, `btc`) are fetched via isolated provider chains. Iranian and International markets execute concurrently.
2. **Fallback Mechanism:** The primary API is polled. On timeout or 5xx error, the system instantly routes the request to the secondary provider.
3. **Last-Resort Cache:** If the entire chain fails (e.g., global network outage), the system reads the last known valid state from `backend/price_cache.json`.
4. **Transparency:** API responses always attach a health status flag: `live`, `cached`, or `unavailable`.

## 🧪 Testing

### Smoke Tests

Before pushing commits, verify the integration points of the pricing engine:

```bash
python backend/scripts/integration_smoke_test.py
```

### Core API Endpoints

* `GET /health` - System health check
* `GET /api/prices` - Fetch unified market data
* `GET /api/prices/health` - Check provider latency and status
* `GET /api/providers` - List active fallback chains
