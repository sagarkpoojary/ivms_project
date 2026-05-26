# IVMS Enterprise Scalability & Multi-VPS Guide

This manual documents the stateless design patterns, shared cache strategies, and load balancing configurations required to scale IVMS horizontally.

## 1. Stateless Web Services
To support multiple Flask/FastAPI backend nodes behind an L7 load balancer (e.g. F5, HAProxy, or Nginx Plus):
- **Sessions**: Flask cookie sessions are completely self-contained and encrypted using `FLASK_SECRET`. Any server can decrypt and parse incoming cookies.
- **FS Cache**: Ensure `CACHE_TYPE` in `app.py` is configured to `RedisCache` (pointing to the shared Redis instance) instead of local `FileSystemCache`.

## 2. Horizontal Ingestion Scaling
The Teltonika ingestion service listens on TCP port `5027`.
- To scale beyond 5,000 active devices, deploy multiple `ingestion` VPS instances behind a TCP Layer 4 load balancer.
- Configure sticky-session or round-robin hashing based on the client device's IMEI to route packets sequentially to the same ingestion worker partition.
- Shard database partitions dynamically using PostgreSQL/TimescaleDB hypertypes.
