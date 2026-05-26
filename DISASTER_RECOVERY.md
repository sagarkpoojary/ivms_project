# IVMS Enterprise Disaster Recovery Runbook

This manual defines the step-by-step procedures for operators to handle active production incident failures and recover state with zero data loss.

## 1. Failover Checklists

### Incident A: TimescaleDB Database Failure / Crash
- **Observation**: UI dashboards throw HTTP 500/503 errors; log streams capture `psycopg2.OperationalError`.
- **Immediate Recovery Action**:
  ```bash
  # Check database container status
  docker compose ps db
  # Restart if exited
  docker compose restart db
  # If DB data is corrupted, retrieve last night's encrypted backup
  /root/ivms_project/scripts/restore_encrypted.sh /root/ivms_project/backups/ivmsdb_backup_latest.sql.gz.gpg
  ```

### Incident B: Redis Cache Reset / Outage
- **Observation**: Map markers freeze, live state updates halt, but ingestion continues.
- **Immediate Recovery Action**:
  ```bash
  # Restart Redis container
  docker compose restart redis
  # Rebuild telemetry cache from persistent TimescaleDB status:
  docker exec ivms-web python -c "import app; from services.external_api_service import _get_all_live_with_fallback; from models.database import load_vehicles; _get_all_live_with_fallback(load_vehicles())"
  ```

## 2. Recovery Validation Procedures
After every restore operation, execute `verify-production.sh` to validate system limits, SSL certificates, socket bindings, and cache status:
```bash
/root/ivms_project/verify-production.sh
```
All system indicators must return `[OK]`.
