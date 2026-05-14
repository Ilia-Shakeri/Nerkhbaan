# Nerkhban Desktop App (Developer README)

This document is the detailed developer guide.  
If you are looking for a quick project overview, see `README.md`.

Nerkhban is a bilingual (Persian/English) desktop interface for monitoring market prices and managing price alerts. The project is built with Electron for the desktop shell and React + Vite for the frontend.

## Overview

This repository currently represents a **frontend-first desktop MVP**:
- Demo authentication (local token)
- Mocked market data and charting
- Alert management UI
- Theme and language preferences persisted in local storage

It is well-suited for UI validation, desktop integration testing, and future backend/API integration.

## Key Features

- Electron desktop window with custom title bar controls
- Route protection using local auth token state
- Dashboard with interactive price charts
- Alert list management (toggle and delete)
- Settings for theme, language, and notification preferences
- Persian (RTL) and English (LTR) support
- Responsive layout optimized for desktop-first usage

## Tech Stack

- **Desktop shell:** Electron
- **Frontend:** React 18, TypeScript, Vite
- **Styling:** Tailwind CSS + component primitives (Radix UI)
- **Charts:** Recharts
- **Animation:** Motion
- **Icons:** Lucide React

## Repository Structure

```text
Nerkhban-app/
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
├── package.json              # Root scripts for Electron + frontend orchestration
├── README.md                # Short marketing overview for GitHub visitors
└── README.developer.md      # Detailed developer documentation
```

## Prerequisites

- Node.js **18+**
- npm **9+** (recommended)
- Windows environment with Electron executable available at:
  - `C:\electron\electron.exe`

> Note: The current root `electron` script is Windows-specific. If your Electron binary is elsewhere, update the `electron` script in `package.json`.

## Installation

Install dependencies for both root and frontend workspaces:

```bash
npm install
cd frontend
npm install
cd ..
```

## Development

### Run full desktop app (Vite + Electron)

```bash
npm run dev
```

This command starts:
1. Vite dev server at `http://localhost:5173`
2. Electron window after the frontend is reachable

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
- `npm run frontend` - Start frontend dev server
- `npm run electron` - Start Electron shell
- `npm run build:frontend` - Build frontend for production
- `npm start` - Alias for `npm run dev`

## Security Notes

Electron is configured with secure defaults in this project:
- `contextIsolation: true`
- `nodeIntegration: false`
- Preload-only renderer access to native capabilities

The exposed renderer API is intentionally minimal (window controls + runtime metadata).

## Current Scope and Limitations

- Authentication is demo-only (no backend identity provider)
- Market prices are mocked, not live API data
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
