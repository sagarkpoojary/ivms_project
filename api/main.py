from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import asyncio
import os
import json
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
import logging

# Production Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

class SafeJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        try:
            return super().render(jsonable_encoder(content))
        except Exception as e:
            logger.error(f"Serialization Error: {e}")
            return super().render({"error": "serialization_failure", "detail": str(e)})

app = FastAPI(
    title="Enterprise IVMS API", 
    version="2.0",
    default_response_class=SafeJSONResponse
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled API Error")
    return SafeJSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": str(exc)}
    )

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
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        events = native_report_service.get_analytics_events(None, 'overspeed', start_dt, end_dt, allowed_imeis)
        return events
    except Exception as e:
        return []

@app.get("/api/events")
async def get_events(allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    """Returns all analytics events for today, filtered by tenant."""
    try:
        from services.report_service import get_period_dates
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

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

async def get_db():
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()

@app.on_event("startup")
async def startup():
    await cache.connect()

@app.get("/api/v2/devices")
async def list_devices(
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    """Lists registered devices for the current tenant."""
    rows = await db.fetch("""
        SELECT v.*, p.name as profile_name 
        FROM vehicles v
        LEFT JOIN device_profiles p ON v.profile_id = p.id
        WHERE v.unique_id = ANY($1)
        ORDER BY v.id DESC
    """, allowed_imeis)
    return [dict(row) for row in rows]

@app.get("/api/v2/live-status")
async def live_status(allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    """Fetches real-time status from Redis cache, filtered by tenant."""
    all_live = await cache.get_all_live()
    return [d for d in all_live if str(d.get('imei')) in allowed_imeis]

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
        
    except Exception as e:
        health["status"] = "unhealthy"
        health["error"] = str(e)
    
    return health

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

# --- WebSocket for Real-time Streaming ---

class ConnectionManager:
    def __init__(self):
        # Store as (websocket, allowed_imeis_set)
        self.active_connections: List[tuple] = []

    async def connect(self, websocket: WebSocket, allowed_imeis: List[str]):
        await websocket.accept()
        self.active_connections.append((websocket, set(allowed_imeis)))

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [conn for conn in self.active_connections if conn[0] != websocket]

    async def broadcast(self, message: str):
        try:
            data = json.loads(message)
            imei = str(data.get('imei'))
        except:
            imei = None

        for websocket, allowed_set in self.active_connections:
            try:
                # Only send if user is allowed to see this IMEI
                if imei and imei in allowed_set:
                    await websocket.send_text(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws/live")
async def websocket_endpoint(
    websocket: WebSocket, 
    allowed_imeis: List[str] = Depends(get_allowed_imeis)
):
    await manager.connect(websocket, allowed_imeis)
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Background task to stream Redis pub/sub to WebSockets
async def stream_redis_to_ws():
    await cache.connect()
    pubsub = cache.client.pubsub()
    await pubsub.subscribe("live_updates")
    
    while True:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                raw_data = message['data']
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode('utf-8')
                await manager.broadcast(raw_data)
            await asyncio.sleep(0.01)
        except Exception as e:
            await asyncio.sleep(1)

@app.on_event("startup")
async def start_streaming():
    asyncio.create_task(stream_redis_to_ws())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
