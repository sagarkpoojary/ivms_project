"""
LIVE POSITION DIAGNOSTICS ENDPOINT

Provides comprehensive visibility into live map synchronization state.
Helps identify stale cache, misaligned DB/Redis, or websocket failures.

Endpoints:
  GET /diagnostics/live-position/{imei}
  GET /diagnostics/live-cache-health
  POST /diagnostics/reconcile-cache
"""

import json
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from core.cache import LiveCache
from core.reconciliation import LivePositionReconciliationEngine
import asyncpg

router = APIRouter(prefix="/diagnostics", tags=["live-position-diagnostics"])
logger = logging.getLogger(__name__)

# These will be set by main app
db_pool = None
cache_client = None
reconciliation_engine = None


def init_diagnostics(pool, redis_client, recon_engine):
    """Initialize diagnostics with DB and cache connections."""
    global db_pool, cache_client, reconciliation_engine
    db_pool = pool
    cache_client = redis_client
    reconciliation_engine = recon_engine


@router.get("/live-position/{imei}")
async def diagnose_live_position(imei: str) -> Dict[str, Any]:
    """
    Diagnoses the current live position state for a vehicle.
    Compares DB vs Redis vs historical telemetry to identify mismatches.
    """
    if not db_pool or not cache_client:
        raise HTTPException(status_code=503, detail="Diagnostics not initialized")
    
    result = {
        "imei": imei,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_state": None,
        "cache_state": None,
        "consistency": None,
        "issues": []
    }
    
    try:
        async with db_pool.acquire() as conn:
            # Get current DB state
            db_row = await conn.fetchrow(
                """
                SELECT 
                    last_telemetry_id, last_timestamp, longitude, latitude, 
                    speed, ignition, status, updated_at
                FROM live_vehicle_status
                WHERE imei = $1
                """,
                imei
            )
            
            if db_row:
                result["db_state"] = {
                    "telemetry_id": db_row['last_telemetry_id'],
                    "timestamp": db_row['last_timestamp'].isoformat() if db_row['last_timestamp'] else None,
                    "longitude": float(db_row['longitude']) if db_row['longitude'] else None,
                    "latitude": float(db_row['latitude']) if db_row['latitude'] else None,
                    "speed": db_row['speed'],
                    "ignition": db_row['ignition'],
                    "status": db_row['status'],
                    "updated_at": db_row['updated_at'].isoformat() if db_row['updated_at'] else None,
                }
                
                # Get telemetry record details
                if db_row['last_telemetry_id']:
                    telem = await conn.fetchrow(
                        "SELECT id, timestamp, priority FROM telemetry WHERE id = $1",
                        db_row['last_telemetry_id']
                    )
                    if telem:
                        result["db_state"]["telemetry_priority"] = telem['priority']
                        result["db_state"]["telemetry_timestamp"] = telem['timestamp'].isoformat()
            else:
                result["issues"].append("No live_vehicle_status record found in DB")
    except Exception as e:
        result["issues"].append(f"DB query failed: {str(e)}")
    
    try:
        # Get Redis cache state
        cache_data = await cache_client.get(f"live:{imei}")
        if cache_data:
            result["cache_state"] = json.loads(cache_data)
        else:
            result["issues"].append("No data in Redis cache")
    except Exception as e:
        result["issues"].append(f"Redis read failed: {str(e)}")
    
    # Consistency check
    if result["db_state"] and result["cache_state"]:
        consistency = reconciliation_engine.verify_redis_consistency(imei) if reconciliation_engine else None
        result["consistency"] = consistency
        
        if consistency and not consistency.get('consistent'):
            result["issues"].append(f"Cache inconsistency detected: {consistency.get('reason')}")
    
    return result


@router.get("/live-cache-health")
async def check_cache_health() -> Dict[str, Any]:
    """
    Checks overall Redis cache health.
    Returns count of vehicles, cache hit rate, and any error patterns.
    """
    if not cache_client:
        raise HTTPException(status_code=503, detail="Diagnostics not initialized")
    
    try:
        keys = await cache_client.keys("live:*")
        total_cached = len(keys) if keys else 0
        
        # Check database for comparison
        total_in_db = 0
        if db_pool:
            async with db_pool.acquire() as conn:
                count_row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM live_vehicle_status")
                total_in_db = count_row['cnt'] if count_row else 0
        
        hit_rate = (total_cached / total_in_db * 100) if total_in_db > 0 else 0
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached_vehicles": total_cached,
            "db_live_vehicles": total_in_db,
            "cache_hit_rate": f"{hit_rate:.1f}%",
            "missing_from_cache": total_in_db - total_cached,
            "status": "healthy" if hit_rate >= 90 else "degraded"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.post("/reconcile-cache")
async def reconcile_cache_from_db(limit: int = None) -> Dict[str, Any]:
    """
    Force reconciliation of Redis cache from authoritative DB state.
    Useful after Redis incidents or cache corruption detection.
    
    CAUTION: This is a write operation. Only run when cache is suspected to be stale.
    """
    if not reconciliation_engine:
        raise HTTPException(status_code=503, detail="Reconciliation engine not initialized")
    
    try:
        count = await reconciliation_engine.rebuild_redis_cache_from_db(limit=limit)
        return {
            "status": "success",
            "vehicles_reconciled": count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": f"Redis cache rebuilt from DB: {count} vehicles"
        }
    except Exception as e:
        logger.error(f"Cache reconciliation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {str(e)}")


@router.get("/live-update-audit/{imei}")
async def get_live_update_audit(imei: str, limit: int = 50) -> Dict[str, Any]:
    """
    Returns recent live position update history for debugging.
    Shows each position reconciliation event with reason and timing.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB not initialized")
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    id, new_telemetry_id, new_timestamp, reason,
                    websocket_emitted, redis_updated, update_latency_ms, created_at
                FROM live_position_updates
                WHERE imei = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                imei, limit
            )
            
            updates = []
            for row in rows:
                updates.append({
                    "update_id": row['id'],
                    "telemetry_id": row['new_telemetry_id'],
                    "timestamp": row['new_timestamp'].isoformat() if row['new_timestamp'] else None,
                    "reason": row['reason'],
                    "websocket_notified": row['websocket_emitted'],
                    "redis_updated": row['redis_updated'],
                    "latency_ms": row['update_latency_ms'],
                    "recorded_at": row['created_at'].isoformat() if row['created_at'] else None,
                })
            
            return {
                "imei": imei,
                "total_records": len(updates),
                "updates": updates
            }
    except Exception as e:
        logger.error(f"Audit query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Audit query failed: {str(e)}")


@router.get("/websocket-health")
async def get_websocket_health() -> Dict[str, Any]:
    """
    Returns WebSocket connection health metrics.
    """
    from api.main import manager  # Import the connection manager
    
    active_count = await manager.get_active_connection_count()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_websocket_connections": active_count,
        "status": "healthy" if active_count > 0 else "no_clients"
    }
