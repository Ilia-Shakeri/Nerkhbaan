# Nerkhbaan

Nerkhbaan is a full-stack market price tracking platform for gold, silver, USDT, and Bitcoin prices across Iranian and international markets. It includes a FastAPI backend, TimescaleDB time-series storage, Redis caching, a React PWA, an Electron desktop shell, alert delivery, provider health reporting, and an optional Telegram MTProto ingestion worker.

## Production Stack

- FastAPI backend with SQLAlchemy and JWT authentication
- TimescaleDB on PostgreSQL 16 for tick storage and OHLCV rollups
- Redis for shared price cache and fast fallback reads
- React + Vite web app served by Nginx
- Optional Electron desktop app
- Optional Telegram MTProto worker using Telethon
- Prometheus metrics endpoint at `/metrics`

## Repository Structure

```text
Nerkhbaan/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── routers/
│   │   │   ├── services/
│   │   │   ├── config.py
│   │   │   ├── db.py
│   │   │   ├── main.py
│   │   │   └── models.py
│   │   ├── db/
│   │   │   ├── init/
│   │   │   └── migrations/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── desktop/
│   │   ├── electron/
│   │   └── src/
│   ├── telegram_worker/
│   │   ├── app/
│   │   ├── Dockerfile
│   │   ├── login.py
│   │   └── telegram_setup_guide.txt
│   └── web/
│       ├── public/
│       ├── src/
│       ├── Dockerfile
│       └── nginx.conf
├── nginx/
├── packages/
│   └── ui/
├── API_DOCUMENTATION.md
├── docker-compose.prod.yaml
├── docker-compose.yaml
├── package.json
└── README.md
```

## Required Environment Variables

Create a `.env` file in the repository root before starting Docker. Use `.env.example` as the template.

Minimum production values:

```env
COMPOSE_FILE=docker-compose.prod.yaml

POSTGRES_USER=nerkhbaan
POSTGRES_DB=nerkhbaan
POSTGRES_PASSWORD=replace-with-a-long-random-password
DATABASE_URL=postgresql+psycopg://nerkhbaan:replace-with-a-long-random-password@postgres:5432/nerkhbaan

JWT_SECRET_KEY=replace-with-a-random-secret-at-least-32-characters
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_EMAIL=admin@your-domain.example
ADMIN_BOOTSTRAP_PASSWORD=Change-This-Strong-Password-14!
ADMIN_BOOTSTRAP_FULL_NAME=System Administrator
ALLOWED_ORIGINS=https://your-domain.example,https://www.your-domain.example

REDIS_URL=redis://redis:6379/0
VITE_API_URL=
```

Optional provider keys:

```env
GOLDAPI_API_KEY=
METALS_DEV_API_KEY=
EXCHANGERATE_API_KEY=
ALANCHAND_API_TOKEN=
```

Optional Telegram ingestion values:

```env
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_STRING=
TELEGRAM_CHANNELS=
```

See `apps/telegram_worker/telegram_setup_guide.txt` before enabling the Telegram worker.

## Fresh Linux VPS Deployment Guide

These steps assume Ubuntu 22.04 or 24.04 with a non-root sudo user.

### 1. Install system packages

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw
```

### 2. Install Docker Engine and Compose

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker --version
docker compose version
```

### 3. Clone the repository

```bash
git clone <your-repository-url> Nerkhbaan
cd Nerkhbaan
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env
```

Set at least:

- `POSTGRES_PASSWORD`
- `DATABASE_URL` with the same password
- `JWT_SECRET_KEY`
- all four `ADMIN_BOOTSTRAP_*` identity values
- `ALLOWED_ORIGINS`

Keep `COMPOSE_FILE=docker-compose.prod.yaml` in `.env` so Docker uses the production stack by default.

### 5. Start the production stack

Run this exact command from the repository root:

```bash
docker compose up -d --build --force-recreate
```

This starts:

- `postgres` with TimescaleDB
- `redis`
- `backend`
- `frontend`
- `db-backup`

The Telegram worker is defined but not started by default because it requires MTProto credentials.

### 6. Verify deployment

```bash
docker compose ps
curl -f http://127.0.0.1:8000/api/health
curl -f http://127.0.0.1:8000/api/prices
```

Open the frontend through your reverse proxy or local tunnel. For the default compose port mapping, the web container is published on `127.0.0.1:3000`.

### 7. Enable Telegram ingestion

After generating `TELEGRAM_SESSION_STRING` and setting `TELEGRAM_CHANNELS`, start the profile:

```bash
docker compose --profile telegram up -d --build telegram-worker
```

### 8. Apply TimescaleDB migration to an existing database

New Docker volumes run `apps/api/db/init/001_timescale_market_prices.sql` automatically. Existing databases must run:

```bash
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < apps/api/db/migrations/20260705_timescale_market_prices.sql
```

## Local Development

Use Node.js 22.23.0 with npm 10.9.8. The versions are pinned in `.nvmrc` and `package.json`. The production backend image uses Python 3.12.13.

Install Node dependencies:

```bash
npm ci
```

Install backend dependencies:

```bash
cd apps/api
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

Run services:

```bash
npm run dev:api
npm run dev:web
```

Run builds:

```bash
npm run build:web
npm run build:admin
npm run build:desktop
```

Run backend tests:

```bash
npm run verify
```

## Frontend Container Build

The web image installs only `nerkhbaan-web` and `@nerkhbaan/ui` from the root lockfile. Desktop and Electron dependencies are not installed in this image.

The registry order is:

1. `https://package-mirror.liara.ir/repository/npm/`
2. `https://mirror2.chabokan.net/npm/`
3. `https://registry.npmjs.org/` as the final fallback

Each registry is checked before use. A failed deterministic `npm ci` attempt moves to the next registry, while package integrity stays enforced by `package-lock.json`. BuildKit keeps the npm download cache between builds.

Build with full logs:

```bash
DOCKER_BUILDKIT=1 docker compose build --no-cache --progress=plain frontend
```

Build again with layer and npm cache reuse:

```bash
DOCKER_BUILDKIT=1 docker compose build --progress=plain frontend
```

Start or recreate the stack:

```bash
docker compose up -d --force-recreate
```

Registry URLs can be overridden without editing the Dockerfile:

```bash
NPM_REGISTRY_PRIMARY=https://package-mirror.liara.ir/repository/npm/ \
NPM_REGISTRY_SECONDARY=https://mirror2.chabokan.net/npm/ \
docker compose build --progress=plain frontend
```

When dependency manifests change, regenerate the lockfile with the repository npm settings so registry-specific tarball URLs are not stored:

```bash
npm config set omit-lockfile-registry-resolved true --location=project
npm install --package-lock-only
```

## API Endpoints

- `GET /api/health`
- `GET /api/prices`
- `GET /api/prices/health`
- `GET /api/providers`
- `POST /api/auth/signup`
- `POST /api/auth/signin`
- `GET /api/auth/me`
- `GET /metrics`

Detailed provider documentation is in `API_DOCUMENTATION.md`.

## Operations Notes

- Keep `.env` out of version control.
- Rotate `JWT_SECRET_KEY` only with a planned user-session invalidation window.
- Keep TimescaleDB backups in the `db_backups` Docker volume or export them to external object storage.
- Monitor `/api/prices/health` for provider degradation.
- If Redis is unavailable, the backend falls back to file cache behavior, but Redis is recommended for multi-worker deployments.
