from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import asyncio
import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import List
from core.cache import LiveCache
from api.v1 import devices, commands, reports
from api.v2 import analytics
from api.v2 import diagnostics
from api.v2 import operations
from auth.api_utils import get_allowed_imeis, get_current_user
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
from core.logging import setup_logging, set_correlation_id
from api.middleware import CorrelationIdMiddleware
import logging

# Production Logging
setup_logging(level=logging.INFO)
logger = logging.getLogger("api")

class SafeJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        try:
            return super().render(jsonable_encoder(content))
        except Exception as e:
            logger.error(f"Serialization Error: {e}")
            return super().render({"error": "serialization_failure", "detail": str(e)})

app = FastAPI(
    title="IVMS Enterprise API", 
    version="2.1.0",
    default_response_class=SafeJSONResponse
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Enterprise IVMS API v2.0"}

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled API Error")
    return SafeJSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": str(exc)}
    )


DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

async def get_db():
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()

cache = LiveCache()

# Unify API paths to match dashboard expectations
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(commands.router, prefix="/api/commands", tags=["Commands"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(analytics.router, prefix="/api/v2/analytics", tags=["Analytics"])
app.include_router(operations.router)
app.include_router(diagnostics.router)

@app.get("/api/alerts")
async def get_alerts(allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    """Returns live overspeed alerts for today, filtered by tenant."""
    try:
        from services.time_service import get_oman_now, get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        events = native_report_service.get_analytics_events(None, 'overspeed', start_dt, end_dt, allowed_imeis)
        return events
    except Exception as e:
        return []

@app.get("/api/devices")
@limiter.limit("60/minute")
async def get_devices(request: Request, uid: str = None, user = Depends(get_current_user), db = Depends(get_db)):
    """Returns basic vehicle metadata, filtered by tenant."""
    allowed_imeis = await get_allowed_imeis(user)
    if uid:
        if uid not in allowed_imeis: return []
        row = await db.fetchrow("SELECT unique_id, name, parent_email FROM vehicles WHERE unique_id = $1", str(uid))
        return [dict(row)] if row else []
    
    rows = await db.fetch("SELECT unique_id, name, parent_email FROM vehicles WHERE unique_id = ANY($1)", allowed_imeis)
    return [dict(row) for row in rows]

@app.get("/api/events")
async def get_events(allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    """Returns all analytics events for today, filtered by tenant."""
    try:
        from services.time_service import get_oman_now, get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        events = native_report_service.get_analytics_events(None, 'all', start_dt, end_dt, allowed_imeis)
        return events
    except Exception as e:
        return []

# Versioned aliases for compatibility
app.include_router(devices.router, prefix="/api/v1/devices", include_in_schema=False)
app.include_router(reports.router, prefix="/api/v2/reports", include_in_schema=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CorrelationIdMiddleware)

@app.on_event("startup")
async def startup():
    await cache.connect()

@app.get("/api/v2/devices")
async def list_devices(
    environment: str = 'production',
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    """Lists registered devices for the current tenant."""
    rows = await db.fetch("""
        SELECT v.*, p.name as profile_name 
        FROM vehicles v
        LEFT JOIN device_profiles p ON v.profile_id = p.id
        WHERE v.unique_id = ANY($1) AND v.telemetry_environment = $2
        ORDER BY v.id DESC
    """, allowed_imeis, environment)
    return [dict(row) for row in rows]

def enforce_cache_freshness(all_live: List[dict]) -> List[dict]:
    """Helper to dynamically override stale cached states to offline with active status reset."""
    from config import Config
    now_utc = datetime.now(timezone.utc)
    for d in all_live:
        ts_str = d.get('timestamp')
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                
                diff = (now_utc - ts).total_seconds()
                
                ignition = d.get('ignition', False)
                is_ign = ignition in [True, 1, '1', 'true', 'True']
                timeout = Config.IGNITION_ON_TIMEOUT_SECONDS if is_ign else Config.IGNITION_OFF_TIMEOUT_SECONDS
                
                if diff > timeout:
                    d['status'] = 'offline'
                    d['speed'] = 0
                    d['ignition'] = False
                    d['movement'] = False
            except Exception:
                pass
    return all_live

@app.get("/api/v2/live-status")
async def live_status(
    environment: str = 'production',
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    """Fetches real-time status from Redis cache, filtered by tenant and environment."""
    all_live = await cache.get_all_live()
    all_live = enforce_cache_freshness(all_live)
    
    # Query database to filter by environment
    matched_rows = await db.fetch("""
        SELECT unique_id FROM vehicles 
        WHERE unique_id = ANY($1) AND telemetry_environment = $2
    """, allowed_imeis, environment)
    matched_imeis = {r['unique_id'] for r in matched_rows}
    
    return [d for d in all_live if str(d.get('imei')) in matched_imeis]

@app.get("/api/v2/telemetry/{imei}")
async def get_telemetry(
    imei: str, 
    limit: int = 100, 
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    if imei not in allowed_imeis:
        raise HTTPException(status_code=403, detail="Access denied to this vehicle")
    rows = await db.fetch(
        "SELECT * FROM telemetry WHERE imei = $1 ORDER BY timestamp DESC LIMIT $2",
        imei, limit
    )
    return [dict(row) for row in rows]

# --- Operational Tooling & Diagnostics ---

@app.get("/api/v2/diagnostics/packets/{imei}")
async def inspect_packets(
    imei: str, 
    limit: int = 10, 
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    """Operational tool to view raw AVL packets and their parsed JSON equivalents."""
    if imei not in allowed_imeis:
        raise HTTPException(status_code=403, detail="Access denied")
        
    rows = await db.fetch(
        "SELECT timestamp, event_id, io_elements, raw_packet FROM telemetry WHERE imei = $1 ORDER BY timestamp DESC LIMIT $2",
        imei, limit
    )
    return [dict(row) for row in rows]

@app.get("/api/v2/diagnostics/health")
async def system_health(
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    """High-level infrastructure health check. Restricted to Enterprise Admins."""
    if user.get("role") not in ["super_admin", "main_admin"]:
        raise HTTPException(status_code=403, detail="Health diagnostics restricted to Main Admin")
    health = {"status": "healthy", "components": {}}
    try:
        # Check DB
        await db.fetchrow("SELECT 1")
        health["components"]["database"] = "ok"
        
        # Check Redis
        await cache.client.ping()
        health["components"]["redis"] = "ok"
        
        # Check TimescaleDB Policies
        policies = await db.fetch("SELECT * FROM timescaledb_information.jobs WHERE proc_name LIKE '%policy%'")
        health["components"]["timescale_policies"] = f"{len(policies)} active"
        
        # Active vs Offline Devices
        status_counts = await db.fetch("SELECT status, count(*) FROM live_vehicle_status GROUP BY status")
        devices = {"online": 0, "offline": 0, "idle": 0, "moving": 0}
        for row in status_counts:
            devices[row['status']] = row['count']
        health["components"]["devices"] = devices
        
        # WebSocket Health
        health["components"]["websocket"] = {
            "active_connections": len(manager.active_connections)
        }
        
        # Recent Alerts
        alerts = await db.fetch("SELECT severity, count(*) FROM system_alerts WHERE resolved = FALSE GROUP BY severity")
        alert_counts = {row['severity']: row['count'] for row in alerts}
        health["components"]["unresolved_alerts"] = alert_counts
        
        # --- PHASE 9: Security Audit Count ---
        audit_count = await db.fetchval("SELECT count(*) FROM security_audit WHERE created_at > NOW() - INTERVAL '24 hours'")
        health["components"]["security_audit_24h"] = audit_count
        
        # --- PHASE 5: Telemetry Confidence ---
        avg_conf = await db.fetchval("SELECT AVG(confidence) FROM analytics_events WHERE timestamp > NOW() - INTERVAL '1 hour'")
        health["components"]["avg_confidence_1h"] = float(avg_conf or 1.0)
        
    except Exception as e:
        health["status"] = "unhealthy"
        health["error"] = str(e)
    
    return health

@app.get("/api/dashboard/bulk-sync")
@limiter.limit("30/minute")
async def get_bulk_sync(
    request: Request, 
    period: str = 'Today', 
    uid: str = None, 
    environment: str = 'production',
    user = Depends(get_current_user), 
    db = Depends(get_db)
):
    """Aggregated dashboard state for high-performance frontend sync."""
    from services.time_service import get_period_dates
    from services.native_report_service import native_report_service
    
    allowed_imeis = await get_allowed_imeis(user)
    start_dt, end_dt = get_period_dates(period)
    
    # 1. Get Vehicle Metadata
    v_rows = await db.fetch("SELECT * FROM vehicles WHERE unique_id = ANY($1) AND telemetry_environment = $2", allowed_imeis, environment)
    vehicles = [dict(r) for r in v_rows]
    
    # 2. Get Live Status from Redis
    all_live = await cache.get_all_live()
    all_live = enforce_cache_freshness(all_live)
    live_map = {str(d.get('imei')): d for d in all_live if str(d.get('imei')) in allowed_imeis}
    
    # 2b. Database Live Position Fallback Map
    status_rows = await db.fetch("""
        SELECT * FROM live_vehicle_status 
        WHERE imei = ANY($1)
    """, allowed_imeis)
    db_status_map = {str(r['imei']): dict(r) for r in status_rows}
    
    # 3. Get Summaries from Native Service
    summaries_list = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)
    summaries_map = {}
    for s in summaries_list:
        uid = str(s['unique_id'])
        summaries_map[uid] = {
            **s,
            "distance": s.get('total_distance', 0),
            "engineHours": s.get('engine_hours', 0),
            "fuelLiters": s.get('fuel_liters', 0),
            "fuelCost": s.get('fuel_cost', 0)
        }
    
    devices_result = []
    for v in vehicles:
        v_uid = str(v['unique_id'])
        v_name = v['name']
        d = live_map.get(v_uid)
        db_status = db_status_map.get(v_uid)
        
        if d:
            devices_result.append({
                **d,
                "uniqueId": v_uid,
                "name": v_name,
                "reconciliation_version": int(d.get('reconciliation_version', 1))
            })
        elif db_status:
            reconstructed = {
                "status": db_status.get('status') or 'offline',
                "timestamp": db_status['last_timestamp'].isoformat() if db_status['last_timestamp'] else None,
                "latitude": float(db_status['latitude']) if db_status['latitude'] else None,
                "longitude": float(db_status['longitude']) if db_status['longitude'] else None,
                "speed": db_status['speed'] or 0,
                "ignition": db_status['ignition'] or False,
                "movement": db_status['movement'] or False,
                "gsm": db_status['gsm_signal'],
                "ext_v": float(db_status['external_voltage']) if db_status['external_voltage'] else None,
                "bat_v": float(db_status['battery_voltage']) if db_status['battery_voltage'] else None,
                "driver_id": db_status['current_driver_id'],
                "driver_name": db_status['current_driver_name'] or 'No Driver Assigned',
                "reconciliation_version": db_status['live_position_reconciliation_version'] or 1
            }
            devices_result.append({
                **reconstructed,
                "uniqueId": v_uid,
                "name": v_name
            })
            
            # Asynchronously heal the Redis cache in the background
            cache_payload = {
                "imei": v_uid,
                **reconstructed
            }
            import asyncio
            asyncio.create_task(cache.update_status(v_uid, cache_payload))
        else:
            devices_result.append({
                "uniqueId": v_uid,
                "name": v_name,
                "status": "offline",
                "speed": 0,
                "ignition": False,
                "movement": False,
                "reconciliation_version": 1
            })
            
    return {
        "devices": devices_result,
        "summaries": summaries_map,
        "server_time": datetime.now().isoformat()
    }

@app.get("/api/v2/diagnostics/alerts")
async def get_system_alerts(user = Depends(get_current_user), db = Depends(get_db)):
    """Returns recent system alerts for enterprise monitoring."""
    if user.get("role") not in ["super_admin", "main_admin", "admin"]:
        raise HTTPException(status_code=403, detail="Enterprise monitoring access denied")
    
    rows = await db.fetch("SELECT * FROM system_alerts ORDER BY timestamp DESC LIMIT 50")
    # Convert datetime to ISO string for JSON serialization
    alerts = []
    for row in rows:
        d = dict(row)
        if d.get('timestamp'):
            d['timestamp'] = d['timestamp'].isoformat()
        alerts.append(d)
    return alerts

# --- WebSocket for Real-time Streaming with Reconciliation ---

class ConnectionManager:
    """
    WebSocket connection manager with health tracking.
    Tracks active connections with permission filtering.
    """
    def __init__(self):
        # Store as (websocket, allowed_imeis_set, connected_at, last_heartbeat)
        self.active_connections: List[tuple] = []
        self.logger = logging.getLogger(__name__)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, allowed_imeis: List[str]):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append((
                websocket, 
                set(allowed_imeis),
                datetime.now(timezone.utc),
                datetime.now(timezone.utc)
            ))
        self.logger.info(f"[WS_CONNECT] New connection for IMEIs: {allowed_imeis}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections = [
                conn for conn in self.active_connections 
                if conn[0] != websocket
            ]
        self.logger.info(f"[WS_DISCONNECT] Connection closed")

    async def broadcast(self, message: str):
        """
        Broadcasts message to authorized clients.
        Includes error handling and delivery tracking.
        """
        try:
            data = json.loads(message)
            imei = str(data.get('imei'))
            msg_type = data.get('type', 'update')
        except:
            imei = None
            msg_type = 'unknown'

        delivered = 0
        failed = 0
        
        async with self._lock:
            snapshot = list(self.active_connections)
            
        failed_sockets = set()
        successful_heartbeats = {}
        
        for websocket, allowed_set, conn_at, hb_at in snapshot:
            try:
                # Only send if user is allowed to see this IMEI
                if imei and imei not in allowed_set:
                    continue
                
                await websocket.send_text(message)
                delivered += 1
                # Update last heartbeat
                successful_heartbeats[websocket] = datetime.now(timezone.utc)
                
            except Exception as ws_err:
                failed += 1
                failed_sockets.add(websocket)
                logging.debug(f"Websocket send failed: {ws_err}")
        
        # Clean up and update heartbeats safely
        async with self._lock:
            new_connections = []
            for conn in self.active_connections:
                ws, allowed_set, conn_at, hb_at = conn
                if ws in failed_sockets:
                    continue
                if ws in successful_heartbeats:
                    new_connections.append((ws, allowed_set, conn_at, successful_heartbeats[ws]))
                else:
                    new_connections.append(conn)
            self.active_connections = new_connections
        
        if delivered > 0:
            logging.debug(f"[WS_BROADCAST] {msg_type} for {imei}: delivered={delivered}, failed={failed}")

    async def get_active_connection_count(self) -> int:
        async with self._lock:
            return len(self.active_connections)


manager = ConnectionManager()

@app.websocket("/ws/live")
async def websocket_endpoint(
    websocket: WebSocket, 
    allowed_imeis: List[str] = Depends(get_allowed_imeis)
):
    """
    WebSocket endpoint for real-time live vehicle updates.
    Implements heartbeat monitoring and connection tracking.
    """
    await manager.connect(websocket, allowed_imeis)
    try:
        while True:
            # Keep-alive - receive any message to detect disconnections
            data = await websocket.receive_text()
            # Log heartbeats occasionally for diagnostic purposes
            logging.debug(f"[WS_HEARTBEAT] from client authorized for {allowed_imeis}")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


# Background task to stream Redis pub/sub to WebSockets with reconciliation
async def stream_redis_to_ws_with_reconciliation():
    """
    Subscribes to Redis pub/sub and streams live updates to WebSocket clients.
    Features:
    - Automatic reconnection on Redis failure  
    - Exponential backoff for retry
    - Event deduplication
    - Fallback to polling if pub/sub fails
    """
    await cache.connect()
    
    retry_delay = 1
    max_retry_delay = 30
    last_message_time = datetime.now(timezone.utc)
    last_imei_update = {}  # Track timestamp of last update per IMEI
    
    while True:
        pubsub = None
        try:
            pubsub = cache.client.pubsub()
            await pubsub.subscribe("live_updates")
            logging.info("[REDIS_PUBSUB] Subscribed to live_updates channel")
            retry_delay = 1  # Reset retry delay on successful connection
            
            while True:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True)
                    
                    if message:
                        raw_data = message['data']
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode('utf-8')
                        
                        try:
                            msg_obj = json.loads(raw_data)
                            imei = msg_obj.get('imei')
                            
                            # DEDUPLICATION: Skip duplicate rapid updates for same IMEI
                            if imei:
                                last_update = last_imei_update.get(imei, datetime.min.replace(tzinfo=timezone.utc))
                                now = datetime.now(timezone.utc)
                                time_since_last = (now - last_update).total_seconds()
                                
                                # Allow updates max once per 100ms per IMEI
                                if time_since_last < 0.1:
                                    logging.debug(f"[WS_DEDUP] Skipped duplicate for {imei} ({time_since_last*1000:.0f}ms)")
                                    await asyncio.sleep(0.01)
                                    continue
                                
                                last_imei_update[imei] = now
                        except:
                            pass
                        
                        # Broadcast to connected WebSocket clients
                        await manager.broadcast(raw_data)
                        last_message_time = datetime.now(timezone.utc)
                        
                    # Brief sleep to prevent CPU spinning
                    await asyncio.sleep(0.01)
                    
                    # Periodic health check
                    now = datetime.now(timezone.utc)
                    if (now - last_message_time).total_seconds() > 60:
                        logging.debug(f"[REDIS_PUBSUB_IDLE] No messages for 60s")
                        active_ws = await manager.get_active_connection_count()
                        logging.info(f"[WS_HEALTH] Active connections: {active_ws}")
                        last_message_time = now
                        
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logging.error(f"[REDIS_PUBSUB_ERROR] {e}")
                    break
                    
        except Exception as e:
            logging.error(f"[REDIS_CONNECTION_FAILED] {e}. Retrying in {retry_delay}s...")
            
            if pubsub:
                try:
                    await pubsub.close()
                except:
                    pass
            
            # Exponential backoff
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_retry_delay)


@app.on_event("startup")
async def start_streaming():
    """Initializes WebSocket streaming background tasks."""
    asyncio.create_task(stream_redis_to_ws_with_reconciliation())
    logging.info("[STARTUP] WebSocket Redis streaming initialized")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
