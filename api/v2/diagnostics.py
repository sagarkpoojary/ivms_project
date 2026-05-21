from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from models.database import get_conn
from auth.api_utils import role_required_api
import psycopg2.extras
import logging
import json

logger = logging.getLogger(__name__)

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
            WHERE timestamp >= NOW() - INTERVAL '1 day' * %s
            ORDER BY timestamp DESC LIMIT 100
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
        cur.execute("SELECT COUNT(*) FROM system_alerts WHERE severity = 'ERROR' AND timestamp >= NOW() - INTERVAL '1 hour'")
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


# ============================================================
# LIVE POSITION RECONCILIATION DIAGNOSTICS
# ============================================================

@router.get("/live-position/{imei}")
async def diagnose_live_position(
    imei: str,
    user_data: dict = Depends(role_required_api("main_admin"))
) -> Dict[str, Any]:
    """
    PRODUCTION DIAGNOSTIC: Inspect live position reconciliation state.
    Compares DB vs historical telemetry to identify stale cache issues.
    
    Returns:
    - DB authoritative position (last_telemetry_id, timestamp, coordinates)
    - Recent telemetry history
    - Reconciliation audit trail
    - Any detected inconsistencies
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Get current authoritative position
        cur.execute(
            """
            SELECT 
                last_telemetry_id, last_timestamp, longitude, latitude,
                speed, ignition, status, updated_at
            FROM live_vehicle_status
            WHERE imei = %s
            """,
            (imei,)
        )
        live_state = cur.fetchone()
        
        # Get recent telemety history
        cur.execute(
            """
            SELECT id, timestamp, longitude, latitude, speed, priority
            FROM telemetry
            WHERE imei = %s
            ORDER BY timestamp DESC
            LIMIT 10
            """,
            (imei,)
        )
        recent_telemetry = cur.fetchall()
        
        # Get reconciliation audit trail
        cur.execute(
            """
            SELECT 
                new_telemetry_id, new_timestamp, reason,
                websocket_emitted, redis_updated, update_latency_ms, created_at
            FROM live_position_updates
            WHERE imei = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (imei,)
        )
        update_history = cur.fetchall()
        
        result = {
            "imei": imei,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "authoritative_position": None,
            "recent_telemetry": [],
            "reconciliation_history": [],
            "issues": []
        }
        
        if live_state:
            result["authoritative_position"] = {
                "telemetry_id": live_state['last_telemetry_id'],
                "timestamp": live_state['last_timestamp'].isoformat() if live_state['last_timestamp'] else None,
                "longitude": float(live_state['longitude']) if live_state['longitude'] else None,
                "latitude": float(live_state['latitude']) if live_state['latitude'] else None,
                "speed": live_state['speed'],
                "ignition": live_state['ignition'],
                "status": live_state['status'],
                "db_updated_at": live_state['updated_at'].isoformat() if live_state['updated_at'] else None,
            }
        else:
            result["issues"].append("No live_vehicle_status record found")
        
        for telem in (recent_telemetry or []):
            result["recent_telemetry"].append({
                "id": telem['id'],
                "timestamp": telem['timestamp'].isoformat() if telem['timestamp'] else None,
                "longitude": float(telem['longitude']) if telem['longitude'] else None,
                "latitude": float(telem['latitude']) if telem['latitude'] else None,
                "speed": telem['speed'],
                "priority": telem['priority'],
                "is_authoritative": live_state and telem['id'] == live_state['last_telemetry_id']
            })
        
        for update in (update_history or []):
            result["reconciliation_history"].append({
                "telemetry_id": update['new_telemetry_id'],
                "timestamp": update['new_timestamp'].isoformat() if update['new_timestamp'] else None,
                "reason": update['reason'],
                "websocket_notified": update['websocket_emitted'],
                "redis_updated": update['redis_updated'],
                "latency_ms": update['update_latency_ms'],
                "recorded_at": update['created_at'].isoformat() if update['created_at'] else None,
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Live position diagnosis failed for {imei}: {e}")
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {str(e)}")
    finally:
        cur.close(); conn.close()


@router.get("/live-update-audit/{imei}")
async def get_live_position_audit(
    imei: str,
    limit: int = 50,
    user_data: dict = Depends(role_required_api("main_admin"))
) -> Dict[str, Any]:
    """
    PRODUCTION AUDIT: Get detailed live position update history.
    Shows every reconciliation event for debugging live sync issues.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            SELECT 
                id, previous_telemetry_id, new_telemetry_id,
                previous_timestamp, new_timestamp, reason,
                websocket_emitted, redis_updated, update_latency_ms, created_at
            FROM live_position_updates
            WHERE imei = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (imei, limit)
        )
        updates = cur.fetchall()
        
        result = {
            "imei": imei,
            "total_records": len(updates) if updates else 0,
            "updates": []
        }
        
        for update in (updates or []):
            result["updates"].append({
                "update_id": update['id'],
                "previous_telemetry_id": update['previous_telemetry_id'],
                "new_telemetry_id": update['new_telemetry_id'],
                "previous_ts": update['previous_timestamp'].isoformat() if update['previous_timestamp'] else None,
                "new_ts": update['new_timestamp'].isoformat() if update['new_timestamp'] else None,
                "reason": update['reason'],
                "websocket_notified": update['websocket_emitted'],
                "redis_updated": update['redis_updated'],
                "latency_ms": update['update_latency_ms'],
                "recorded_at": update['created_at'].isoformat() if update['created_at'] else None,
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Audit query failed for {imei}: {e}")
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(e)}")
    finally:
        cur.close(); conn.close()
