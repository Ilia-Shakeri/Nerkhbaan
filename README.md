# 📈 Nerkhbaan (نرخ‌بان)

![Electron](https://img.shields.io/badge/Electron-191970?style=for-the-badge&logo=Electron&logoColor=58C4DC)
![React](https://img.shields.io/badge/React-191970?style=for-the-badge&logo=react&logoColor=58C4DC)
![FastAPI](https://img.shields.io/badge/FastAPI-191970?style=for-the-badge&logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-191970?style=for-the-badge&logo=postgresql&logoColor=white)

Nerkhbaan is a highly resilient, cross-platform desktop application designed for real-time market price tracking and alert management. Built with a focus on zero-downtime data delivery, it tracks precious metals, cryptocurrencies, and fiat currencies in both Toman and USD.

## ✨ Core Features
- **Bilingual Interface:** Full RTL (Persian) and LTR (English) support.
- **Resilient Pricing Engine:** Implements a priority-based fallback chain for market APIs, ensuring data availability even if primary providers face rate limits.
- **Offline Grace Degradation:** Disk-cached pricing (`price_cache.json`) guarantees the UI never breaks during complete network provider failures.
- **Secure Authentication:** JWT-based user sessions managed via a robust FastAPI backend.
- **Modern Desktop Shell:** Custom, clean UI wrapper powered by Electron and React 18.

## 🏗️ Architecture Overview
Nerkhbaan separates concerns into three distinct layers:
1. **Desktop Client:** Electron container managing OS-level interactions.
2. **Frontend UI:** React application utilizing Tailwind CSS and Shadcn UI.
3. **Backend Service:** FastAPI with asynchronous data fetching, backed by PostgreSQL and SQLAlchemy connection pooling.

## 🚀 Production Deployment (Quick Start)
For production environments, Nerkhbaan utilizes Docker to ensure isolated, reproducible builds.

1. **Clone & Configure:**
   ```bash
   git clone [https://github.com/your-username/nerkhbaan.git](https://github.com/Ilia-Shakeri/Nerkhbaan.git)
   cd nerkhbaan
   cp backend/.env.example backend/.env
   # Edit .env with your secure production credentials
```

2. **Deploy via Docker Compose:**
```bash
docker compose up -d --build
```


3. **Verify Health:**
```bash
curl http://localhost:8000/health
```



## 📚 Documentation

* **[Developer Guide](https://www.google.com/search?q=README.developer.md):** Detailed instructions for local setup, architecture flows, and testing.
