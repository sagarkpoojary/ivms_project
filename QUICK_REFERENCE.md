# QUICK REFERENCE: LIVE MAP SYNCHRONIZATION DEBUG

## 🚀 Deployment Commands

```bash
# Apply migration (idempotent)
psql -U $DB_USER -h $DB_HOST -d $DB_NAME < sql/migration_live_position_reconciliation.sql

# Verify tables created
psql -U $DB_USER -h $DB_HOST -d $DB_NAME -c "
  SELECT table_name FROM information_schema.tables 
  WHERE schema='public' AND table_name IN (
    'live_position_updates', 'redis_cache_health', 'websocket_sync_log'
  );"

# Restart services
systemctl restart ivms-ingestion
systemctl restart ivms-api
```

---

## 🔍 Diagnostics - "Why is vehicle stuck at old location?"

### Step 1: Check if telemetry is arriving
```bash
# Recent packets for vehicle
psql -U $DB_USER -h $DB_HOST -d $DB_NAME -c "
  SELECT timestamp, longitude, latitude, speed 
  FROM telemetry 
  WHERE imei='868575043159851' 
  ORDER BY timestamp DESC LIMIT 5;"
```

✓ **Good**: Recent timestamps (within last minute)  
✗ **Bad**: All packets are old, or no packets

### Step 2: Check authoritative position in DB
```bash
psql -U $DB_USER -h $DB_HOST -d $DB_NAME -c "
  SELECT 
    last_telemetry_id, 
    last_timestamp, 
    longitude, 
    latitude 
  FROM live_vehicle_status 
  WHERE imei='868575043159851';"
```

✓ **Good**: timestamp matches recent telemetry  
✗ **Bad**: timestamp is old, or NULL

### Step 3: Check Redis cache
```bash
redis-cli GET live:868575043159851 | jq .

# Expected output:
# {
#   "imei": "868575043159851",
#   "timestamp": "2026-05-20T14:30:00+00:00",
#   "longitude": 77.5432,
#   "latitude": 28.6139,
#   ...
# }
```

✓ **Good**: timestamp matches DB  
✗ **Bad**: timestamp is old, or key doesn't exist

### Step 4: Check reconciliation audit trail
```bash
# Using diagnostic endpoint (preferred)
curl http://localhost:8000/api/v2/diagnostics/live-update-audit/868575043159851 | jq .

# Or direct SQL
psql -U $DB_USER -h $DB_HOST -d $DB_NAME -c "
  SELECT 
    new_telemetry_id, 
    reason, 
    websocket_emitted, 
    redis_updated, 
    update_latency_ms, 
    created_at 
  FROM live_position_updates 
  WHERE imei='868575043159851' 
  ORDER BY created_at DESC LIMIT 10;"
```

✓ **Good**: Recent entries with reason='newer_packet', ws=true, redis=true  
✗ **Bad**: Entries with reason='already_stale' (stale protection triggered), or ws=false/redis=false

### Step 5: Check WebSocket health
```bash
curl http://localhost:8000/api/v2/diagnostics/websocket-health | jq .

# Expected: {"active_websocket_connections": 5, "status": "healthy"}
```

✓ **Good**: active_websocket_connections > 0  
✗ **Bad**: 0 connections

---

## ⚠️ Common Issues & Fixes

### Issue: "Map shows position from 1 hour ago"

**Step**: Run Step 1-4 diagnostics above

**Common causes**:

| Cause | Fix |
|-------|-----|
| **Stale protection too aggressive** | Check timestamp comparison in logs. If "already_stale" for new packets, report bug. |
| **Redis cache corrupted** | Run: `redis-cli DEL live:<IMEI>` then force rebuild: `curl -X POST http://localhost:8000/api/v2/diagnostics/reconcile-cache` |
| **WebSocket not broadcasting** | Check logs: `grep "WS_BROADCAST" api.log`. If all failed, restart API server. |
| **Device sending old timestamps** | Check device-side clock sync. Run: `ssh <device> date` |

### Issue: "Position updates show huge latency (>1000ms)"

**Check**: `SELECT update_latency_ms FROM live_position_updates WHERE created_at > NOW() - INTERVAL '1 hour' ORDER BY update_latency_ms DESC LIMIT 5;`

**Causes**:

| Cause | Fix |
|-------|-----|
| **DB slow** | Check DB load: `SELECT * FROM pg_stat_statements` |
| **Redis slow** | Check Redis memory: `redis-cli INFO memory` |
| **Network congestion** | Check throughput: `sar -n DEV 1 10` |

### Issue: "WebSocket shows 0 connections"

**Check**: Are clients connecting?

```bash
# Monitor WebSocket connections
tail -f api.log | grep WS_CONNECT

# Force reconnect on dashboard (browser console):
location.reload()
```

**Causes**:

| Cause | Fix |
|-------|-----|
| **API not running** | Check: `systemctl status ivms-api` |
| **WebSocket port blocked** | Check firewall: `sudo netstat -tlnp \| grep 8000` |
| **Client-side error** | Check browser console for JS errors |

---

## 📊 Performance Expectations

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| **Position reconciliation latency** | <50ms | 50-100ms | >100ms |
| **WebSocket broadcast delay** | <10ms | 10-50ms | >50ms |
| **E2E (device→map) delay** | 100-150ms | 150-300ms | >300ms |
| **Active WebSocket connections** | >0 | Any | N/A |
| **Redis cache hit rate** | >90% | 70-90% | <70% |
| **Position update success rate** | 100% | >95% | <95% |

---

## 🔧 Manual Troubleshooting

### Force Redis cache rebuild
```bash
# Direct reconciliation
curl -X POST http://localhost:8000/api/v2/diagnostics/reconcile-cache?limit=100

# Or manual Redis clear + DB rebuild
redis-cli FLUSHDB  # ⚠️ DANGER: Clears ALL Redis data!

# Restart API to auto-rebuild on startup
systemctl restart ivms-api
```

### Check specific vehicle's complete state
```bash
curl http://localhost:8000/api/v2/diagnostics/live-position/868575043159851 | jq .

# Full output includes:
# - authoritative_position (from DB)
# - recent_telemetry (last 10 packets)
# - reconciliation_history (last 20 updates)
# - issues (any detected problems)
```

### Monitor in real-time
```bash
# Watch position updates as they happen
tail -f ingestion.log | grep "LIVE_UPDATED\|STALE_PRESERVED\|RECONCILIATION"

# Watch WebSocket broadcasts
tail -f api.log | grep "WS_BROADCAST"

# Watch Redis errors
redis-cli MONITOR | grep -i error
```

---

## 📋 Log Patterns

### ✓ Healthy System
```
[LIVE_UPDATED] 868575043159851: Position reconciled | t_id=12345 ts=2026-05-20T14:30:00+00:00 ws=True redis=True latency=45ms
[WS_BROADCAST] position_update for 868575043159851: delivered=5, failed=0
[RECONCILIATION_START] 868575043159851: telemetry_id=12345, timestamp=2026-05-20T14:30:00+00:00
✓ DB updated: 868575043159851 now has authoritative position from telemetry_id=12345
```

### ⚠️ Expected Warnings
```
[STALE_PRESERVED] 868575043159851: Historical packet preserved | reason=already_stale previous_id=12344 latency=18ms
[REDIS_PUBSUB_IDLE] No messages for 60s
[REDIS_CONNECTION_FAILED] [Errno ...]. Retrying in 1s...
```

### ✗ Error Patterns (Investigate)
```
[RECONCILIATION_ERROR] 868575043159851: Position reconciliation failed: ...
✗ DB update FAILED for 868575043159851
✗ Redis cache UPDATE FAILED for 868575043159851: ...
✗ Websocket emit FAILED for 868575043159851: ...
```

---

## 🆘 Escalation Path

| Issue | Owner | Action |
|-------|-------|--------|
| **Position not updating** | DevOps + DBA | Run diagnostics, check DB/Redis health |
| **WebSocket not working** | Backend Engineer | Check API logs, test WebSocket endpoint |
| **Telemetry not arriving** | Ingestion Team | Check device connection, TCP port, ingestion server |
| **Dashboard not rendering** | Frontend Engineer | Check browser console, network tab |
| **Performance degradation** | DBA | Check query performance, indexing |

---

## 📞 Support Contacts

- **On-call DevOps**: `#oncall-devops` on Slack
- **Database Team**: `#database` on Slack
- **API Team**: `#backend` on Slack

---

## 📖 Full Documentation

- **Deployment Guide**: `PRODUCTION_DEPLOYMENT_GUIDE.md`
- **Technical Architecture**: `TECHNICAL_ARCHITECTURE.md`
- **Implementation Summary**: `IMPLEMENTATION_SUMMARY.md`
- **This Quick Reference**: `QUICK_REFERENCE.md`

---

**Last Updated**: 2026-05-20  
**Status**: PRODUCTION READY  
**Maintainer**: Production Telematics Team
