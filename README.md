# IVMS (In-Vehicle Monitoring System) — Enterprise Edition

**Version:** 3.0 (Hardened Production Release)
**Architecture:** Distributed Microservices
**Core Stack:** Python (Flask/FastAPI), TimescaleDB (Time-series SQL), Redis, Celery, Nginx, Prometheus.

---

## 🚀 Overview
IVMS Enterprise is a professional, high-scale Fleet Management and Telemetry Operations platform. Designed for 24/7 reliability, it handles native telemetry ingestion directly from hardware (Teltonika, etc.) and provides real-time analytics with deep observability.

### 💎 Enterprise Features
- **Native Telemetry Pipeline:** High-performance TCP ingestion server (Teltonika Codec 8/8E supported).
- **Hardened Security:** JWT-based unified authentication, CSRF protection, and HSTS/SSL enforcement.
- **TimescaleDB Optimization:** Hypertable-based storage with automated retention and compression policies.
- **Distributed Jobs:** Celery background workers for reports, maintenance, and heavy analytics.
- **Enterprise Observability:** Full Prometheus/Grafana stack with custom telemetry lag and throughput metrics.
- **Multi-Tenant RBAC:** Isolated data environments for Super Admin, Main Admin, and Company Users.
- **Audit Trails:** Comprehensive security auditing and brute-force protection.

---

## 🏗️ Architecture

- **Web Portal (Flask):** The enterprise frontend and management console.
- **API Engine (FastAPI):** High-performance telemetry API and live WebSocket gateway.
- **Ingestion Server:** Low-latency TCP server for device communication.
- **Database (TimescaleDB):** Optimized PostgreSQL for time-series telemetry and relational metadata.
- **Background Workers (Celery):** Scalable workers for non-blocking operations.
- **Reverse Proxy (Nginx):** SSL termination and security header enforcement.

---

## 🛠️ Deployment

The system is fully containerized and managed via Docker Compose.

```bash
# 1. Configure environment
cp .env.example .env

# 2. Build and start the stack
docker compose up -d --build

# 3. Initialize Database
docker exec -i ivms-db psql -U ivmsuser -d ivmsdb < sql/hardening.sql
```

### 🔑 Authentication
The system uses a **Unified Auth Authority**.
- **Web:** Secure Session Cookies.
- **API/WS:** JWT (obtained via `/auth/token`).

---

## 📊 Monitoring & Observability

Access the diagnostic suite:
- **Prometheus:** `http://localhost:9090`
- **Grafana:** `http://localhost:3000` (Default: admin/admin)
- **Diagnostics Center:** Internal `/diagnostics` route (Super Admin only).

---

## 📄 License
Private Proprietary Software.
Copyright © 2026 Concept Groups. All rights reserved.
