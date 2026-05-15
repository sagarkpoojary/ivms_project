from fastapi import APIRouter, Depends, HTTPException
from typing import List
from datetime import datetime, timedelta
from models.database import get_conn
from auth.utils import role_required_api
import psycopg2.extras

router = APIRouter(prefix="/api/v2/diagnostics", tags=["Diagnostics"])

@router.get("/alerts")
async def get_system_alerts(
    days: int = 7,
    user_data: dict = Depends(role_required_api("main_admin"))
):
    """Fetch system health alerts for main admins and super admins."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM system_alerts 
            WHERE created_at >= NOW() - INTERVAL '1 day' * %s
            ORDER BY created_at DESC LIMIT 100
        """, (days,))
        return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close(); conn.close()

@router.get("/health")
async def get_system_health(
    user_data: dict = Depends(role_required_api("main_admin"))
):
    """Summary of system health (DB latency, Active Devices, Recent Errors)."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # DB Latency check
        start = datetime.now()
        cur.execute("SELECT 1")
        latency = (datetime.now() - start).total_seconds() * 1000 # ms
        
        # Active sessions
        cur.execute("SELECT COUNT(*) FROM live_vehicle_status WHERE status != 'offline'")
        active = cur.fetchone()['count']
        
        # Recent errors (last 1h)
        cur.execute("SELECT COUNT(*) FROM system_alerts WHERE severity = 'ERROR' AND created_at >= NOW() - INTERVAL '1 hour'")
        errors = cur.fetchone()['count']
        
        return {
            "status": "healthy" if errors == 0 else "degraded",
            "db_latency_ms": round(latency, 2),
            "active_devices": active,
            "recent_errors_1h": errors,
            "server_time": datetime.now().isoformat()
        }
    finally:
        cur.close(); conn.close()
@router.get("/device/{imei}")
async def get_device_diagnostics(
    imei: str,
    user_data: dict = Depends(role_required_api("main_admin"))
):
    """Detailed diagnostic view for a specific device (Phase 13)."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM live_vehicle_status WHERE imei = %s", (imei,))
        live = cur.fetchone()
        
        cur.execute("SELECT timestamp, event_id FROM telemetry WHERE imei = %s ORDER BY timestamp DESC LIMIT 5", (imei,))
        recent = cur.fetchall()
        
        return {
            "imei": imei,
            "live_status": live,
            "recent_packets": recent,
            "status": "online" if live and live['status'] != 'offline' else "offline"
        }
    finally:
        cur.close(); conn.close()
