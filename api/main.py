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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI(title="Enterprise IVMS API", version="2.0")
cache = LiveCache()

# Unify API paths to match dashboard expectations
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(commands.router, prefix="/api/commands", tags=["Commands"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])

@app.get("/api/alerts")
async def get_alerts():
    """Returns live overspeed alerts for today."""
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        events = native_report_service.get_analytics_events(None, 'overspeed', start_dt, end_dt)
        return events
    except Exception as e:
        return []

@app.get("/api/events")
async def get_events():
    """Returns all analytics events for today."""
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        events = native_report_service.get_analytics_events(None, 'all', start_dt, end_dt)
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
async def list_devices(db = Depends(get_db)):
    rows = await db.fetch("""
        SELECT d.*, p.name as profile_name 
        FROM devices d
        LEFT JOIN device_profiles p ON d.profile_id = p.id
        ORDER BY d.last_heartbeat DESC
    """)
    return [dict(row) for row in rows]

@app.get("/api/v2/live-status")
async def live_status():
    """Fetches real-time status from Redis cache."""
    return await cache.get_all_live()

@app.get("/api/v2/telemetry/{imei}")
async def get_telemetry(imei: str, limit: int = 100, db = Depends(get_db)):
    rows = await db.fetch(
        "SELECT * FROM telemetry WHERE imei = $1 ORDER BY timestamp DESC LIMIT $2",
        imei, limit
    )
    return [dict(row) for row in rows]

# --- Operational Tooling & Diagnostics ---

@app.get("/api/v2/diagnostics/packets/{imei}")
async def inspect_packets(imei: str, limit: int = 10, db = Depends(get_db)):
    """Operational tool to view raw AVL packets and their parsed JSON equivalents."""
    rows = await db.fetch(
        "SELECT timestamp, event_id, io_elements, raw_packet FROM telemetry WHERE imei = $1 ORDER BY timestamp DESC LIMIT $2",
        imei, limit
    )
    return [dict(row) for row in rows]

@app.get("/api/v2/diagnostics/health")
async def system_health(db = Depends(get_db)):
    """High-level infrastructure health check."""
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
        
    except Exception as e:
        health["status"] = "unhealthy"
        health["error"] = str(e)
    
    return health

# --- WebSocket for Real-time Streaming ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
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
