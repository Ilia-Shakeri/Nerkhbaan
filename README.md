# 📈 Nerkhbaan (نرخ‌بان)

![Electron](https://img.shields.io/badge/Electron-191970?style=for-the-badge&logo=Electron&logoColor=58C4DC)
![React](https://img.shields.io/badge/React-191970?style=for-the-badge&logo=react&logoColor=58C4DC)
![Vite](https://img.shields.io/badge/Vite-191970?style=for-the-badge&logo=vite&logoColor=646CFF)
![FastAPI](https://img.shields.io/badge/FastAPI-191970?style=for-the-badge&logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-191970?style=for-the-badge&logo=postgresql&logoColor=white)

Nerkhbaan is a highly resilient, cross-platform application ecosystem designed for real-time market price tracking and alert management. Built with a focus on zero-downtime data delivery, it tracks precious metals, cryptocurrencies, and fiat currencies in both Toman and USD.

## 🏗️ Monorepo Architecture
This repository utilizes a unified workspace model to house the entire Nerkhbaan ecosystem:
- **`apps/api`**: FastAPI backend service managing asynchronous market data fetching, caching layers, and PostgreSQL connections.
- **`apps/web`**: Progressive Web App (PWA) client built with React 18 and Tailwind CSS for standard browser access.
- **`apps/desktop`**: Standalone cross-platform desktop shell utilizing Electron and React.

## ✨ Core Features
- **Bilingual Interface:** Full RTL (Persian) and LTR (English) localization support.
- **Resilient Pricing Engine:** Implements priority-based fallback chains for market APIs, guaranteeing data availability even during upstream rate limits or outages.
- **Offline Grace Degradation:** Disk-cached pricing (`price_cache.json`) ensures the user interface remains stable during complete external network failures.
- **Secure Authentication:** JWT-based user sessions strictly managed via the FastAPI backend supporting both username and email logins.

## 🚀 Production Deployment (Quick Start)
For production environments, Nerkhbaan uses Docker Compose to reliably orchestrate the backend, frontend, and database containers.

1. **Clone & Configure:**
   ```bash
   git clone [https://github.com/Ilia-Shakeri/Nerkhbaan.git](https://github.com/Ilia-Shakeri/Nerkhbaan.git)
   cd Nerkhbaan
   cp apps/api/.env.example apps/api/.env
   # Edit .env with your secure production credentials
2. **Deploy via Docker Compose:**
   ```bash
   docker compose up -d --build
   ```
3. **Verify Health:**
   ```bash
   curl http://localhost:8000/health
   ```

## 📚 Documentation

* **[Developer Guide](https://www.google.com/search?q=README.developer.md):** Detailed instructions for local setup, workspace management, architecture flows, and testing protocols.