# Nerkhbaan - Smart Price Tracking Platform

A modern, full-stack price tracking and alerting platform built with FastAPI, React, and Electron.

## Features

### Frontend
- **Glassmorphism UI** with dark/light themes
- **Real-time Price Charts** with TradingView-style scrubbing
- **Smart Alerts** with webhook, email, and push notification support
- **PWA Support** with offline capability
- **Support Ticketing System** with live chat interface
- **Multi-currency** toggle (USD/Toman)
- **Responsive Design** optimized for desktop and mobile

### Backend
- **Layered Pricing Architecture** with primary/fallback providers
- **Redis Caching** with automatic file-based fallback
- **Prometheus Metrics** for monitoring
- **Alert Engine** with single-pass evaluation
- **Dead Letter Queue** with exponential backoff retry
- **JWT Authentication** with secure password hashing
- **RESTful API** with OpenAPI documentation

## Quick Start (Windows)

### Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL 14+
- Docker Desktop (recommended)

### Setup

1. **Install Dependencies**
```powershell
npm install
cd apps\api
.\setup_windows.bat
```

2. **Configure Environment**

Create `apps\api\.env`:
```env
DATABASE_URL=postgresql+psycopg://nerkhbaan:nerkhbaan@localhost:5432/nerkhbaan
JWT_SECRET_KEY=your-random-32-character-secret-key
ALLOWED_ORIGINS=http://localhost:5173
ADMIN_INITIAL_PASSWORD=admin123
REDIS_URL=redis://localhost:6379/0
```

3. **Start Database**
```powershell
docker run -d --name nerkhbaan-postgres -e POSTGRES_USER=nerkhbaan -e POSTGRES_PASSWORD=nerkhbaan -e POSTGRES_DB=nerkhbaan -p 5432:5432 postgres:15
```

4. **Start Redis (Optional)**
```powershell
docker run -d --name nerkhbaan-redis -p 6379:6379 redis:7-alpine
```

5. **Run Application**
```powershell
npm run dev:all
```

Access:
- Web: http://localhost:5173
- API: http://localhost:8000/api/docs
- Metrics: http://localhost:8000/metrics

## Documentation

- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Comprehensive setup instructions
- **[QUICK_START.md](QUICK_START.md)** - Fast track setup for Windows
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Frontend features
- **[BACKEND_IMPLEMENTATION_SUMMARY.md](BACKEND_IMPLEMENTATION_SUMMARY.md)** - Backend architecture

## Project Structure

```
Nerkhbaan/
├── apps/
│   ├── api/              # FastAPI backend
│   │   ├── app/
│   │   │   ├── routers/  # API endpoints
│   │   │   ├── services/ # Business logic
│   │   │   └── models.py # Database models
│   │   └── requirements.txt
│   ├── web/              # React PWA
│   │   └── src/
│   │       ├── app/
│   │       │   ├── views/      # Page components
│   │       │   ├── components/ # Reusable components
│   │       │   └── services/   # API client
│   │       └── pwa/            # Service worker
│   └── desktop/          # Electron wrapper
└── packages/
    └── ui/               # Shared UI library
```

## Tech Stack

### Frontend
- React 18
- TypeScript
- Tailwind CSS
- Vite
- Motion (Framer Motion)
- Recharts
- Lucide Icons

### Backend
- FastAPI
- SQLAlchemy
- PostgreSQL
- Redis
- Prometheus
- Python-JOSE (JWT)
- Bcrypt
- HTTPX

### DevOps
- Docker
- Uvicorn
- Concurrently
- ESLint
- Prettier

## Key Features Implementation

### Password Visibility Toggle
All password inputs automatically include eye icon toggle for show/hide functionality.

### Currency Toggle
Segmented control with sliding indicator showing both USD and Toman options simultaneously.

### Alert Modal
Production-ready modal with:
- In-app notifications
- Email delivery
- Webhook integration
- Dead Letter Queue for failed deliveries

### Chart Fullscreen
Maximize button on each chart opens modal with 60vh detailed view for technical analysis.

### Support System
Full ticketing interface with:
- Ticket creation and listing
- Live chat with admin
- Message history
- File attachment placeholder

### PWA Offline Support
Network detection with stabilization delay prevents false offline banner flashes during reconnection.

## API Endpoints

### Authentication
- `POST /api/auth/signin` - User login
- `POST /api/auth/signup` - User registration

### Prices
- `GET /api/prices` - Get current prices with history

### Support
- `POST /api/support/ticket` - Create ticket
- `GET /api/support/tickets` - List user tickets
- `GET /api/support/ticket/{id}/messages` - Get messages
- `POST /api/support/ticket/{id}/message` - Send message

### Monitoring
- `GET /api/health` - Health check
- `GET /metrics` - Prometheus metrics

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `JWT_SECRET_KEY` | JWT signing key (32+ chars) | Yes |
| `ALLOWED_ORIGINS` | CORS allowed origins | Yes |
| `ADMIN_INITIAL_PASSWORD` | Admin account password | Yes |
| `REDIS_URL` | Redis connection string | No |
| `ALANCHAND_API_TOKEN` | Alanchand API key | No |
| `METALS_DEV_API_KEY` | Metals.dev API key | No |
| `GOLDAPI_API_KEY` | GoldAPI key | No |
| `EXCHANGERATE_API_KEY` | ExchangeRate API key | No |

## Monitoring

### Prometheus Metrics
- `price_fetches_total` - Total price fetches by asset/region/status
- `cache_staleness_seconds` - Cache age by asset/region
- `price_fetch_duration_seconds` - Fetch latency histogram

### Grafana Dashboards
Configure Prometheus scraper:
```yaml
scrape_configs:
  - job_name: 'nerkhbaan'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

## Development

### Run Tests
```bash
cd apps/api
pytest

cd apps/web
npm test
```

### Build Production
```bash
npm run build:web
npm run build:desktop
```

## Troubleshooting

**Uvicorn not found:**
```powershell
cd apps\api
venv\Scripts\activate
pip install -r requirements.txt
```

**Electron binary missing:**
```powershell
cd apps\desktop
npm rebuild electron
```

**Database connection error:**
```powershell
docker ps | findstr postgres
docker restart nerkhbaan-postgres
```

**Redis timeout (optional):**
Remove `REDIS_URL` from `.env` to use file-based cache fallback.

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

[Your License Here]

## Support

For issues or questions, please open a GitHub issue or contact the development team.
