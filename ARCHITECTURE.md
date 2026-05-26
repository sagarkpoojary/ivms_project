# IVMS Enterprise Platform Architecture

This document outlines the Intelligent Vehicle Management System (IVMS) production topology, service roles, and database interaction paradigms.

## 1. System Topology

```
                  [ Teltonika Telematics Devices ]
                                 │
                                 ▼ (TCP/5027)
                      ┌──────────────────────┐
                      │   Ingestion Server   │
                      └──────────┬───────────┘
                                 │
                                 ▼ (Async Queue)
                      ┌──────────────────────┐
                      │   Database Workers   │
                      └──────────┬───────────┘
                                 │
         ┌───────────────────────┴───────────────────────┐
         ▼ (Write)                                       ▼ (Read)
  ┌─────────────┐                                 ┌─────────────┐
  │ TimescaleDB │◄────────────────────────────────┤ Redis Cache │
  │ (Database)  │                                 │ (Active PGs)│
  └──────┬──────┘                                 └──────┬──────┘
         │                                               │
         └───────────────────────┬───────────────────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │      Nginx Proxy     │
                      └──────────┬───────────┘
                                 │
                        ┌────────┴────────┐
                        ▼                 ▼
                 [ Web Clients ]   [ API Consumers ]
```

## 2. Component Directory

### Ingestion Service (`ingestion/main.py`)
Directly binds to TCP port `5027` to handle real-time Teltonika GPS trackers. Implements Codec8E AVL frame parser, sequenced queue distribution, and backpressure control.

### Database Worker (`ingestion/db/handler.py`)
Processes telemetry batches from the ingestion queue, executes atomic live position reconciliations, caches the status directly in Redis, and pushes status notifications through Redis Pub/Sub channels.

### API Gateway (`api/main.py`)
Uvicorn-backed FastAPI application serving low-latency REST calls and active WebSocket subscription broadcasts for the map dashboard interfaces.

### Web Dashboard Application (`app.py`)
Flask-based multi-tenant user portal serving dashboard templates, historical playbacks, analytics widgets, maintenance schedules, RFID driver assignments, and Prometheus metrics.

### Persistent Datastore (TimescaleDB)
Time-series optimized PostgreSQL database storing GPS records in daily chunked hypertables, alongside standard models for user permissions, audit tracking, sites, and ticket workflows.
