# 🛠️ Nerkhbaan Developer Guide

Welcome to the Nerkhbaan internal documentation. This guide covers local environment setup, our monorepo architecture patterns, and the testing protocols required for contributing to the codebase.

## 💻 Tech Stack
- **Workspace Management:** NPM Workspaces
- **Backend (`apps/api`):** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, PostgreSQL 16
- **Web (`apps/web`):** React 18, TypeScript, Vite, Tailwind CSS
- **Desktop (`apps/desktop`):** Electron, React 18, TypeScript, Vite

## 📂 Repository Structure
```text
Nerkhbaan/
├── apps/
│   ├── api/             # FastAPI microservice and pricing fetchers
│   ├── desktop/         # Electron wrapper and React desktop UI
│   └── web/             # Web application frontend
├── docker-compose.yaml  # Infrastructure orchestration for production
├── package.json         # Root workspace configuration and scripts
├── README.md            # Public repository documentation
└── README.developer.md  # This file
```

## ⚙️ Local Development Setup

### 1. Prerequisites

Ensure you have the following installed on your machine:

* Node.js 22.23.0 and npm 10.9.8 (pinned by `.nvmrc` and `package.json`)
* Python 3.12 (the production image version)
* [Docker Engine](https://docs.docker.com/get-docker/)

### 2. Environment Configuration

Duplicate the example environment file for the backend and populate it with your local keys:

```bash
cd apps/api
cp .env.example .env
cd ../..
```

*Note: The system checks `PRICING_REQUIRE_PROVIDER_KEYS` on startup. If set to `false`, the API boots successfully without external keys and intelligently utilizes the cache/fallback logic.*

### 3. Initialize the Database

Spin up the local PostgreSQL container from the root directory:

```bash
docker compose up -d postgres
```

### 4. Install Dependencies

Install all Node modules across the monorepo workspaces:

```bash
npm ci
```

Set up the Python virtual environment for the backend:

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cd ../..
```

### 5. Running the Ecosystem

The root `package.json` contains unified scripts to start any part of the stack.

* **Start Backend API:** `npm run dev:api`
* **Start Web App:** `npm run dev:web`
* **Start Desktop App:** `npm run dev:desktop`

## 🧠 System Behavior: The Pricing Engine

The core value of Nerkhbaan relies on a highly resilient, zero-downtime pricing engine located in `apps/api/app/services`. The logic flows as follows:

1. **Chain Execution:** Assets (`gold`, `silver`, `usdt`, `btc`) are fetched via isolated provider chains. Iranian and International markets execute concurrently.
2. **Fallback Mechanism:** The primary API is polled. On timeout or a 5xx error, the system instantly routes the request to the secondary provider.
3. **Last-Resort Cache:** If the entire chain fails (e.g., a global network outage), the system reads the last known valid state from `price_cache.json`.
4. **Transparency:** API responses always attach a health status flag: `live`, `cached`, or `unavailable`.

## 🧪 Testing

### Smoke Tests

Before pushing commits, verify the integration points of the pricing engine. Ensure your backend server is running locally, then execute:

```bash
python apps/api/scripts/integration_smoke_test.py --base-url [http://127.0.0.1:8000](http://127.0.0.1:8000)
```
