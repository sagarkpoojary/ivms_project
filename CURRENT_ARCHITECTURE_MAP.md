# IVMS CURRENT ARCHITECTURE MAP

## Overview
IVMS (Intelligent Vehicle Management System) is a production telematics platform built with a microservices architecture using Docker containers. The system processes GPS telemetry from Teltonika devices, stores it in TimescaleDB, and provides real-time tracking via WebSocket connections to a web dashboard.

## Service Topology

### 1. Ingestion Layer
- **Service**: `ingestion/main.py` (DeviceSession, IngestionServer)
- **Port**: 5027 (TCP) - Direct device connections
- **Protocol**: Teltonika Codec8E over TCP
- **Function**: 
  - Authenticates devices via IMEI handshake
  - Decodes AVL packets
  - Applies filtering pipeline
  - Queues telemetry for database processing
  - Maintains active session registry in Redis
  - Handles backpressure control when queues are full

### 2. Database Processing Layer
- **Service**: `ingestion/db/handler.py` (DBHandler)
- **Function**:
  - Processes telemetry from partitioned queues
  - Implements per-device sequencing
  - Handles database inserts with retry logic
  - Calls reconciliation engine for live position updates
  - Manages analytics and hysteresis engines
  - Handles device offline detection
  - Implements dead-letter queue for failed records

### 3. API Layer
- **Service**: `api/main.py` (FastAPI application)
- **Port**: 8000 (internal)
- **Function**:
  - RESTful API for external integrations
  - WebSocket endpoints for real-time data
  - Diagnostic and monitoring endpoints
  - Authentication and authorization

### 4. Web Layer
- **Service**: `app.py` (Flask application)
- **Port**: 5000 (internal)
- **Function**:
  - Serves web dashboard and UI
  - Handles user authentication and sessions
  - Renders templates and static assets
  - Exposes Prometheus metrics endpoint

### 5. Reverse Proxy & SSL Termination
- **Service**: `nginx` (nginx:alpine image)
- **Ports**: 80 (HTTP), 443 (HTTPS)
- **Function**:
  - SSL/TLS termination with modern cipher suites
  - HTTP to HTTPS redirect
  - Reverse proxy to web and API services
  - WebSocket proxying with proper headers
  - Security headers (HSTS, CSP, etc.)
  - Rate limiting and DDoS protection

### 6. Background Workers
- **Service**: `celery_worker` (celery -A celery_app worker)
- **Function**:
  - Asynchronous task processing
  - Report generation
  - Maintenance operations
  - External API calls

### 7. Monitoring Stack
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and alerting
- **Function**:
  - Collects application metrics via Prometheus client
  - Stores time-series data
  - Provides dashboards for system health
  - Sends alerts on anomalies

### 8. Caching & Pub/Sub
- **Service**: Redis (redis:7-alpine)
- **Port**: 6379 (internal)
- **Function**:
  - Live vehicle status cache (TTL: 7 days)
  - Pub/sub channel for real-time updates ("live_updates")
  - Distributed locks for hysteresis engine
  - Active session registry
  - Rate limiting counters
  - Event storm control mechanisms

### 9. Data Storage
- **Service**: TimescaleDB/PostgreSQL (timescale/timescaledb:latest-pg15)
- **Port**: 5432 (internal)
- **Function**:
  - Primary telemetry storage (hypertables)
  - Device and configuration metadata
  - Command queue for device management
  - Live vehicle status table
  - Analytics events and system logs
  - Retention policies (90 days hot storage)
  - Compression policies (after 7 days)

## Network Topology
```
[Teltonika Devices] 
        ↓ (TCP/5027)
[Ingestion Server] ←→ [Redis] ←→ [WebSocket Clients]
        ↓
[Database Workers] ←→ [TimescaleDB]
        ↓
[Web/API Services] ←→ [Nginx] ←→ [Internet Users]
        ↓
[Celery Workers] 
        ↓
[Prometheus] ←→ [Grafana]
```

## Key Architectural Patterns
1. **Partitioned Queues**: 5 partitions for device-sequential processing
2. **Backpressure Control**: Socket pausing when queue > 8000 items
3. **Atomic Reconciliation**: DB FOR UPDATE locks prevent race conditions
4. **Event Sourcing**: Position updates stored in live_position_updates table
5. **Caching Strategy**: Redis as primary read cache with DB as source of truth
6. **Observability**: Prometheus metrics integrated throughout
7. **Resilience**: Supervisor loops restart failed background tasks
8. **Security**: Rate limiting, input validation, SQL injection prevention

## Current Limitations Identified
1. Single point of failure: Nginx as sole ingress point
2. Limited horizontal scaling: Services not designed for multi-instance
3. Shared database: No tenant isolation for multi-customer deployments
4. File-based caching: Flask cache uses filesystem (not Redis-cluster ready)
5. Local backups: No off-site or cross-region backup strategy
6. Monitoring gaps: No business-level metrics or SLA tracking