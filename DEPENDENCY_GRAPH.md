# IVMS DEPENDENCY GRAPH

## Service Dependencies Analysis

### 1. Ingestion Service Dependencies
**Service**: `ingestion/main.py` (IngestionServer)
- **Depends on**:
  - Redis: For session registry, active device tracking, rate limiting
  - PostgreSQL/TimescaleDB: For device validation, telemetry storage
  - Internal Queues: Asyncio queues for workload distribution
  - DeviceSession class: For individual connection handling
  - Metrics: Prometheus client for observability
  - Config: Environment variables for connection strings

### 2. Database Handler Dependencies
**Service**: `ingestion/db/handler.py` (DBHandler)
- **Depends on**:
  - PostgreSQL/TimescaleDB: Primary data store
  - Redis: Live cache, pub/sub for WebSocket updates
  - LiveCache class: Redis wrapper with connection pooling
  - LivePositionReconciliationEngine: Atomic position updates
  - AnalyticsEngine: Trip detection and analytics processing
  - MotionHysteresisEngine: State machine for vehicle status
  - Config: Database connection parameters
  - AsyncPG: Async PostgreSQL driver

### 3. API Service Dependencies
**Service**: `api/main.py` (FastAPI)
- **Depends on**:
  - PostgreSQL/TimescaleDB: For data retrieval and reporting
  - Redis: For WebSocket pub/sub and caching
  - LiveCache: For real-time vehicle status
  - Pydantic: For data validation
  - Uvicorn: ASGI server
  - SQLModel/AsyncPG: Database access
  - Auth/JWT: For API security

### 4. Web Service Dependencies
**Service**: `app.py` (Flask)
- **Depends on**:
  - PostgreSQL/TimescaleDB: For reports and historical data
  - Redis: For Flask-Caching and session storage
  - Flask: Web framework
  - Flask-WTF: CSRF protection
  - Flask-Login: User session management
  - Prometheus Client: Metrics exposition
  - Config: Application configuration
  - Extensions: Cache, database, auth integrations

### 5. Nginx Dependencies
**Service**: `nginx` (nginx:alpine)
- **Depends on**:
  - Web Service (Flask): For dashboard and UI
  - API Service (FastAPI): For telemetry and external APIs
  - SSL Certificates: For HTTPS termination
  - Linux Base: Alpine Linux distribution

### 6. Monitoring Stack Dependencies
**Service**: `prometheus` and `grafana`
- **Depends on**:
  - All Services: Metrics collection via Prometheus client
  - Storage Volumes: For persistent metrics and dashboard data
  - Network: Service discovery for target endpoints

### 7. Celery Worker Dependencies
**Service**: `celery_worker`
- **Depends on**:
  - Redis: As broker and result backend
  - PostgreSQL/TimescaleDB: For report generation data
  - External APIs: For Odoo integration and notifications
  - File System: For report artifact storage

### 8. Redis Dependencies
**Service**: `redis:7-alpine`
- **Depends on**:
  - Linux Base: Alpine Linux
  - Network: For inter-service communication
  - Persistence Volume: For data durability (AOF/RDB)

### 9. Database Dependencies
**Service**: `timescale/timescaledb:latest-pg15`
- **Depends on**:
  - Linux Base: Alpine Linux
  - Persistence Volume: For data storage
  - Network: For inter-service communication
  - TimescaleDB Extension: For time-series optimizations

## Dependency Flow Analysis

### Data Flow: Device Telemetry → Dashboard
1. **Device** → TCP/5027 → **Ingestion Service**
   - Authenticates via IMEI
   - Decodes Codec8E packets
   - Applies filtering pipeline
   - Queues to asyncio DB queue

2. **Ingestion Service** → Asyncio Queues → **Database Workers**
   - Partitioned by IMEI hash for sequential processing
   - Each worker has dedicated DB connection pool

3. **Database Worker** → PostgreSQL → **TimescaleDB**
   - Inserts telemetry records
   - Returns telemetry_id
   - Calls reconciliation engine within same transaction

4. **Reconciliation Engine** → PostgreSQL + Redis → **Live Updates**
   - Atomic read-compare-write with FOR UPDATE lock
   - Updates live_vehicle_status table
   - Updates Redis cache with SETEX
   - Publishes to Redis "live_updates" channel
   - Inserts audit trail into live_position_updates

5. **Redis Pub/Sub** → **API Service** → **WebSocket Clients**
   - API service subscribes to "live_updates" channel
   - WebSocket endpoint broadcasts to connected clients
   - Includes deduplication and health monitoring

6. **WebSocket Clients** → Browser → **Dashboard Updates**
   - Frontend JavaScript processes WebSocket messages
   - Updates map markers and vehicle status
   - Refreshes info panels and analytics

### Control Flow: Management Operations
1. **External Commands** → Redis → **Device Sessions**
   - Commands published to `device_commands:{imei}` channel
   - Device session subscribes and executes commands
   - Results reported back via telemetry or alerts

2. **Maintenance Tasks** → Cron/Supervisor → **Background Workers**
   - Cache rebuilders sync PostgreSQL → Redis
   - Offline reconciliation marks stale devices
   - Socket cleanup terminates inactive connections
   - Watchdog detects and heals discrepancies

3. **Monitoring** → Prometheus → **Grafana/Alerts**
   - Services expose `/metrics` endpoints
   - Prometheus scrapes metrics periodically
   - Grafana visualizes trends and triggers alerts

## Circular Dependencies Identified
1. **Ingestion ↔ Database Handler**: Tight coupling through queues and direct calls
2. **API/Web ↔ Redis**: Both depend on Redis for caching and pub/sub
3. **All Services ↔ Config**: Environment variables create implicit coupling
4. **Database Handler ↔ LiveCache**: Direct instantiation creates tight coupling

## Single Points of Failure in Dependencies
1. **Redis**: If Redis fails, live updates, caching, and session tracking break
2. **PostgreSQL**: If database fails, all data persistence and reconciliation stops
3. **Nginx**: If reverse proxy fails, no external access to services
4. **Ingestion Service**: If ingestion fails, no new telemetry is processed

## Scalability Bottlenecks in Dependencies
1. **Redis Single Instance**: All services depend on one Redis instance
2. **PostgreSQL Single Instance**: All writes go through one database
3. **Shared File System**: Docker volumes mounted from host create I/O contention
4. **Nginx Single Instance**: All traffic terminates at one proxy

## Recommended Decoupling Strategies
1. **Introduce Message Queues**: Use Redis Streams or Apache Kafka for telemetry ingestion
2. **Database Read Replicas**: Separate read and write workloads
3. **Redis Cluster**: Shard caching and pub/sub workloads
4. **Service Mesh**: Implement Istio/Linkerd for traffic management
5. **Event-Driven Architecture**: Move to event sourcing with CQRS
6. **Circuit Breakers**: Add resilience patterns for external dependencies