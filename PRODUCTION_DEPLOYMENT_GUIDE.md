# IVMS LIVE MAP SYNCHRONIZATION - PRODUCTION STABILIZATION

## EXECUTIVE SUMMARY

Implemented Traccar-style authoritative live position reconciliation engine to fix stale vehicle markers on the live map. The system now guarantees:

✓ Latest valid telemetry packets ALWAYS update live state  
✓ Stale/historical packets NEVER corrupt runtime state  
✓ Historical telemetry ALWAYS preserved for reports/playback  
✓ Redis cache stays synchronized with authoritative DB  
✓ WebSocket clients receive real-time updates with delivery tracking  
✓ Automatic cache rebuild on infrastructure restart  
✓ Comprehensive audit logging for troubleshooting  

---

## CHANGES MADE

### 1. DATABASE SCHEMA MIGRATION

**File**: `sql/migration_live_position_reconciliation.sql`

**Changes**:
- Added `last_telemetry_id` to `live_vehicle_status` - tracks authoritative position ID  
- Added `last_valid_packet_time` - timestamps first authoritative position use  
- Added `reconciliation_flags` - JSON flags for future extensions  
- Added `live_position_reconciliation_version` - version tracking for future migrations  

**New Audit Tables**:
- `live_position_updates` - Every position reconciliation event with timestamps and latency  
- `redis_cache_health` - Cache consistency monitoring  
- `websocket_sync_log` - WebSocket emission tracking  

**Deployment**:
```bash
# Apply migration
psql -U $DB_USER -h $DB_HOST -d $DB_NAME < sql/migration_live_position_reconciliation.sql
```

### 2. CORE RECONCILIATION ENGINE

**File**: `core/reconciliation.py` (NEW)

**Architecture**:
```
INCOMING PACKET
    ↓
[ATOMIC READ-COMPARE-WRITE in DB transaction]
    ↓
If timestamp > existing:
    ✓ Update live_vehicle_status with last_telemetry_id
    ✓ Update Redis cache
    ✓ Emit WebSocket event
    ✓ Log audit trail
Else (stale packet):
    → Skip live updates (preserve stale protection)
    → Still preserve in telemetry table for history
    → Log as "already_stale"
```

**Key Features**:
- **UTC-aware timestamp comparison** - Handles timezone edge cases
- **Atomic DB transactions** - Prevents race conditions  
- **Explicit position ID tracking** - No ambiguity about "latest"
- **Audit trail logging** - Every position change tracked with reason
- **Error handling** - Graceful degradation on Redis/WebSocket failures

**Usage**:
```python
result = await reconciliation_engine.reconcile_position(
    imei="868575043159851",
    telemetry_id=12345,           # DB ID of this telemetry record
    timestamp=datetime(2026, 5, 20, 14, 30, 0, tzinfo=timezone.utc),
    longitude=77.5432,
    latitude=28.6139,
    speed=45,
    ignition=True,
    movement=True,
    gsm=25,
    ext_v=13.2,
    bat_v=0.0,
    status="moving"
)
# Returns: {
#   'reconciled': True,
#   'reason': 'newer_packet',
#   'websocket_notified': True,
#   'redis_updated': True,
#   'latency_ms': 45
# }
```

### 3. INGESTION HANDLER INTEGRATION

**File**: `ingestion/db/handler.py` (MODIFIED)

**Changes**:

a) **Imports**:
```python
from core.reconciliation import LivePositionReconciliationEngine
```

b) **DBHandler.__init__**:
```python
self.reconciliation_engine = None  # Initialized on connect
```

c) **DBHandler.connect**:
- Initialize reconciliation engine
- Auto-rebuild Redis cache from DB (production safety)

d) **save_telemetry flow**:
```
OLD (buggy):
  - Save telemetry
  - Check if stale (simple timestamp comparison)
  - Skip live updates if stale
  - If not stale, update DB + Redis + NOT calling reconciliation

NEW (fixed):
  - Save telemetry (capture returned ID)
  - Get telemetry ID from DB
  - Call reconciliation_engine.reconcile_position()
    - Engine handles atomic comparison
    - Engine handles DB update
    - Engine handles Redis update
    - Engine handles WebSocket emit
    - Engine logs audit trail
  - Analytics/hysteresis still work for validated updates
  - Driver session management
```

**Before/After Logging**:
```
BEFORE:
  "Stale/backfill packet ignored for live status updates on 868575043159851"

AFTER:
  "[LIVE_UPDATED] 868575043159851: Position reconciled | t_id=12345 ts=2026-05-20T14:30:00+00:00 ws=True redis=True latency=45ms"
  
  OR
  
  "[STALE_PRESERVED] 868575043159851: Historical packet preserved | reason=already_stale previous_id=12344 latency=18ms"
```

### 4. WEBSOCKET & REDIS LAYER

**File**: `api/main.py` (ENHANCED)

**Improvements**:

a) **ConnectionManager**:
- Track connection time and last heartbeat  
- Monitor active connection count
- Enhanced error handling in broadcast

b) **WebSocket Endpoint**:
- Heartbeat monitoring  
- Better reconnection handling
- Logged connection/disconnection events

c) **Redis PubSub Stream** (`stream_redis_to_ws_with_reconciliation`):
- **Automatic reconnection** with exponential backoff
- **Deduplication** - prevents rapid duplicate updates for same IMEI
- **Health monitoring** - periodic connection checks
- **Graceful degradation** - logs errors without crashing
- **Message validation** - JSON parse with error handling

**Features**:
```python
# Deduplication: Max 1 update per 100ms per IMEI
# Prevents storm of rapid updates overwhelming clients

# Exponential backoff: 1s → 1.5s → 2.25s ... up to 30s
# Auto-recovers from temporary Redis failures

# Health check: Every 60s with no messages, log connection status
# Helpful for diagnosing silent pubsub failures
```

### 5. PRODUCTION DIAGNOSTICS

**File**: `api/v2/diagnostics.py` (ENHANCED)

**New Endpoints**:

a) **GET /api/v2/diagnostics/live-position/{imei}**
```
Returns:
{
  "imei": "868575043159851",
  "timestamp": "2026-05-20T14:35:00+00:00",
  "authoritative_position": {
    "telemetry_id": 12345,
    "timestamp": "2026-05-20T14:30:00+00:00",
    "longitude": 77.5432,
    "latitude": 28.6139,
    ...
  },
  "recent_telemetry": [
    {
      "id": 12345,
      "timestamp": "2026-05-20T14:30:00+00:00",
      "is_authoritative": true
    },
    ...
  ],
  "reconciliation_history": [
    {
      "telemetry_id": 12345,
      "reason": "newer_packet",
      "websocket_notified": true,
      "redis_updated": true,
      "latency_ms": 45,
      ...
    }
  ],
  "issues": []
}
```

b) **GET /api/v2/diagnostics/live-update-audit/{imei}**
- Full audit trail of position updates
- Useful for investigating why map didn't update

---

## ROOT CAUSE ANALYSIS

### Original Issues Fixed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| **Stale markers** | Timestamps compared without timezone info | UTC-aware comparison in reconciliation engine |
| **Race conditions** | No atomic read-compare-write | Explicit DB row lock in transaction |
| **No position ID** | Only tracked timestamp, not telemetry ID | Added `last_telemetry_id` to schema |
| **Redis misses** | Failed on Redis error, continued processing | Error handling + reconnection logic |
| **WebSocket silent failures** | PubSub could lose subscription silently | Health monitoring + auto-reconnect |
| **No audit trail** | Couldn't debug why position didn't update | Audit tables + diagnostic endpoints |

---

## DEPLOYMENT STRATEGY

### Phase 1: Pre-Deployment (NO downtime)

```bash
# 1. Run migration (idempotent - safe to re-run)
psql -U $DB_USER -h $DB_HOST -d $DB_NAME < sql/migration_live_position_reconciliation.sql

# 2. Verify tables exist
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('live_position_updates', 'redis_cache_health', 'websocket_sync_log');
```

### Phase 2: Code Deployment

```bash
# 1. Deploy files
# - core/reconciliation.py (NEW)
# - ingestion/db/handler.py (MODIFIED)
# - api/main.py (MODIFIED)
# - api/v2/diagnostics.py (MODIFIED)
# - sql/migration_live_position_reconciliation.sql

# 2. Test imports (in Python shell):
python -c "from core.reconciliation import LivePositionReconciliationEngine; print('OK')"

# 3. Deploy API with new code
# Restart ingestion server (handles DB pool restart)
# Restart API server
```

### Phase 3: Validation (Same day, during traffic hours)

```bash
# 1. Verify reconciliation engine is active
curl http://localhost:8000/api/v2/diagnostics/live-position/868575043159851

# 2. Send test telemetry packet
# Watch logs for:
# "[RECONCILIATION_START] ..."
# "[LIVE_UPDATED] ... latency=XXms" (should be <100ms)

# 3. Check WebSocket health
curl http://localhost:8000/api/v2/diagnostics/websocket-health

# 4. Monitor logs for errors:
tail -f ingestion.log | grep -i "error\|failed"
```

---

## ROLLBACK STRATEGY

### If Issues Occur

**Immediate Action** (< 2 minutes):

```bash
# 1. REVERT code (roll back to previous version)
git checkout HEAD~1 -- core/reconciliation.py
git checkout HEAD~1 -- ingestion/db/handler.py  
git checkout HEAD~1 -- api/main.py

# 2. Restart services
systemctl restart ivms-ingestion
systemctl restart ivms-api

# 3. Verify old code is running:
curl http://localhost:8000/ | grep version
```

**Database Rollback** (Optional - database changes are additive):

```bash
# If needed, drop new tables (CAUTION: Will lose audit data)
psql -U $DB_USER -h $DB_HOST -d $DB_NAME -c "
DROP TABLE IF EXISTS websocket_sync_log;
DROP TABLE IF EXISTS redis_cache_health;
DROP TABLE IF EXISTS live_position_updates;
ALTER TABLE live_vehicle_status
DROP COLUMN IF EXISTS last_telemetry_id,
DROP COLUMN IF EXISTS last_valid_packet_time,
DROP COLUMN IF EXISTS reconciliation_flags,
DROP COLUMN IF EXISTS live_position_reconciliation_version;
"
```

**Data Safety**:
- ✓ Historical telemetry table UNTOUCHED
- ✓ live_vehicle_status columns are ADDITIVE (backward compatible)
- ✓ New audit tables contain only diagnostic data
- ✓ No data loss on rollback

---

## TESTING STRATEGY

### Unit Tests (Can run in dev)

Create `tests/test_live_position.py`:

```python
import pytest
from core.reconciliation import LivePositionReconciliationEngine
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_new_packet_updates_live():
    """Verify newer packet updates authoritative position"""
    result = await engine.reconcile_position(
        imei="TEST_IMEI",
        telemetry_id=1,
        timestamp=datetime.now(timezone.utc),
        longitude=77.5,
        latitude=28.6,
        speed=50,
        ignition=True,
        movement=True
    )
    assert result['reconciled'] == True
    assert result['reason'] == 'initial_position'

@pytest.mark.asyncio
async def test_stale_packet_rejected():
    """Verify stale packet doesn't update live state"""
    old_time = datetime(2026, 5, 19, 0, 0, 0, tzinfo=timezone.utc)
    new_time = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    
    # First (old) packet
    await engine.reconcile_position(
        imei="TEST_IMEI", telemetry_id=1,
        timestamp=old_time, ...
    )
    
    # Second (newer) packet - should update
    result = await engine.reconcile_position(
        imei="TEST_IMEI", telemetry_id=2,
        timestamp=new_time, ...
    )
    assert result['reconciled'] == True
    
    # Third (stale) packet - should NOT update
    result = await engine.reconcile_position(
        imei="TEST_IMEI", telemetry_id=3,
        timestamp=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc), ...
    )
    assert result['reconciled'] == False
    assert result['reason'] == 'already_stale'
```

### Integration Tests (Production-like)

```bash
# 1. Simulate vehicle movement
curl -X POST http://telemetry-server:5027/api/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "devices": [{
      "imei": "868575043159851",
      "timestamp": '$(date +%s)'000,
      "gps": {"lat": 28.6139, "lon": 77.5432, "speed": 45}
    }]
  }'

# 2. Check live position updated
curl http://localhost:8000/api/v2/diagnostics/live-position/868575043159851 | jq '.authoritative_position.timestamp'

# 3. Verify Redis cache updated
redis>  GET live:868575043159851 | jq '.timestamp'

# 4. Check WebSocket clients received update
grep "position_update" ingestion.log | tail -5
```

---

## MONITORING & OBSERVABILITY

### Key Metrics to Watch

```python
# 1. Position reconciliation latency
SELECT avg(update_latency_ms), max(update_latency_ms)
FROM live_position_updates
WHERE imei = '<vehicle_imei>'
AND created_at > NOW() - INTERVAL '1 hour';

# 2. Stale vs Live updates ratio
SELECT 
  reason,
  COUNT(*) as count
FROM live_position_updates
GROUP BY reason
WHERE created_at > NOW() - INTERVAL '24 hours';

# 3. Redis cache consistency
SELECT 
  COUNT(*) as divergent_records
FROM live_vehicle_status lvs
WHERE NOT EXISTS (
  SELECT 1 FROM redis_cache_health rch
  WHERE rch.imei = lvs.imei
  AND rch.cache_status = 'consistent'
);

# 4. WebSocket emission failures
SELECT COUNT(*) as failed_emits
FROM live_position_updates
WHERE websocket_emitted = FALSE
AND created_at > NOW() - INTERVAL '1 hour';
```

### Log Patterns to Watch

**Good Signs**:
- `[LIVE_UPDATED] ... latency=<50ms` - Normal operation
- `[STALE_PRESERVED] ... reason=already_stale` - Stale protection working
- `[RECONCILIATION_START]` - Position update in progress

**Warning Signs**:
- `[RECONCILIATION_ERROR]` - Reconciliation failure
- `[REDIS_CONNECTION_FAILED]` - Cache out of sync
- `[WS_BROADCAST] delivered=0` - No clients receiving updates

---

## CONFIGURATION

No new configuration needed. Uses existing:
- DB connection string (env vars)
- Redis connection string (env vars)
- Logger configuration

---

## COMPATIBILITY

- ✓ Backward compatible with existing telemetry schema
- ✓ Existing reports/playback unaffected (historical data untouched)
- ✓ Existing dashboard code works (just gets updated live state)
- ✓ Existing ingestion pipeline continues working
- ✓ Existing Redis cache format extended (additive only)

---

## SUPPORT & DIAGNOSTICS

### If Live Map Still Shows Stale Position

```bash
# 1. Check if telemetry is arriving
psql> SELECT timestamp FROM telemetry WHERE imei='<IMEI>' ORDER BY timestamp DESC LIMIT 5;

# 2. Check if DB position is updating
psql> SELECT last_timestamp, updated_at FROM live_vehicle_status WHERE imei='<IMEI>';

# 3. Check if Redis has latest value
redis> GET live:<IMEI>

# 4. Check reconciliation audit trail
curl http://localhost:8000/api/v2/diagnostics/live-update-audit/<IMEI>

# 5. Check for WebSocket delivery
curl http://localhost:8000/api/v2/diagnostics/websocket-health

# 6. Force cache rebuild (production safe)
curl -X POST http://localhost:8000/api/v2/diagnostics/reconcile-cache
```

---

## FUTURE ENHANCEMENTS

- [ ] Position smoothing for rapid GPS drifts
- [ ] Geofence-based position validation
- [ ] Historical timeline for position replay
- [ ] Cache invalidation strategies
- [ ] Distributed cache synchronization (for multi-server deployments)

---

**Deployment Owner**: DevOps/Infrastructure  
**Testing Owner**: QA/Testing Team  
**Support Owner**: Production Support  
**Documentation Last Updated**: 2026-05-20
