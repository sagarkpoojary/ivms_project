#!/usr/bin/env python3
"""
LIVE PRODUCTION DEVICE FLOW AUDIT
=================================
Comprehensive diagnostic tool for IVMS vehicle tracking issues.

This script performs a 7-phase audit to determine root cause of:
- Vehicles showing no movement when physically moving
- 0 km, 0 engine hours, offline status
- Stale telemetry

Usage: python audit_devices.py [--imei IMEI] [--all]
"""

import asyncio
import asyncpg
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from core.cache import LiveCache
from services.native_report_service import native_report_service

# Database connection
DB_DSN = Config.DATABASE_URL if hasattr(Config, 'DATABASE_URL') else "postgresql://ivms:ivms@localhost/ivms"

async def get_db_pool():
    return await asyncpg.create_pool(dsn=DB_DSN)

async def audit_device(imei, pool, cache):
    """
    PHASE 1: Device-by-device live audit
    Returns comprehensive device status
    """
    result = {
        "imei": imei,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {}
    }
    
    # 1. Check live_vehicle_status table
    async with pool.acquire() as conn:
        live_status = await conn.fetchrow(
            "SELECT * FROM live_vehicle_status WHERE imei = $1", str(imei)
        )
        result["checks"]["db_live_status"] = dict(live_status) if live_status else None
        
        # 2. Check latest telemetry
        latest_telemetry = await conn.fetchrow(
            """SELECT * FROM telemetry 
               WHERE imei = $1 
               ORDER BY timestamp DESC 
               LIMIT 1""",
            str(imei)
        )
        result["checks"]["latest_telemetry"] = dict(latest_telemetry) if latest_telemetry else None
        
        # 3. Check trip_summary
        trip_summary = await conn.fetchrow(
            """SELECT * FROM trip_summary 
               WHERE imei = $1 
               ORDER BY start_time DESC 
               LIMIT 5""",
            str(imei)
        )
        result["checks"]["trip_summary"] = dict(trip_summary) if trip_summary else None
        
        # 4. Check analytics events
        events = await conn.fetch(
            """SELECT event_type, timestamp, value 
               FROM analytics_events 
               WHERE imei = $1 
               ORDER BY timestamp DESC 
               LIMIT 10""",
            str(imei)
        )
        result["checks"]["analytics_events"] = [dict(e) for e in events]
    
    # 5. Check Redis cache
    try:
        redis_data = await cache.get_status(imei)
        result["checks"]["redis_cache"] = redis_data
    except Exception as e:
        result["checks"]["redis_cache"] = {"error": str(e)}
    
    # 6. Check reconciliation audit
    async with pool.acquire() as conn:
        audit = await conn.fetch(
            """SELECT * FROM live_position_updates 
               WHERE imei = $1 
               ORDER BY new_timestamp DESC 
               LIMIT 10""",
            str(imei)
        )
        result["checks"]["reconciliation_audit"] = [dict(a) for a in audit]
    
    return result

async def audit_all_devices():
    """Audit all registered vehicles"""
    pool = await get_db_pool()
    cache = LiveCache()
    await cache.connect()
    
    # Get all registered IMEIs
    async with pool.acquire() as conn:
        vehicles = await conn.fetch("SELECT unique_id, name FROM vehicles")
    
    results = []
    for v in vehicles:
        imei = str(v['unique_id'])
        print(f"\n{'='*60}")
        print(f"AUDITING: {imei} - {v['name']}")
        print('='*60)
        
        result = await audit_device(imei, pool, cache)
        results.append(result)
        
        # Print summary
        live = result["checks"].get("db_live_status")
        telemetry = result["checks"].get("latest_telemetry")
        redis = result["checks"].get("redis_cache")
        
        print(f"  DB Live Status: {'EXISTS' if live else 'MISSING'}")
        if live:
            print(f"    - Last timestamp: {live.get('last_timestamp')}")
            print(f"    - Ignition: {live.get('ignition')}")
            print(f"    - Speed: {live.get('speed')}")
        
        print(f"  Latest Telemetry: {'EXISTS' if telemetry else 'MISSING'}")
        if telemetry:
            print(f"    - Timestamp: {telemetry.get('timestamp')}")
            print(f"    - Speed: {telemetry.get('speed')}")
            print(f"    - IO Elements: {telemetry.get('io_elements')}")
        
        print(f"  Redis Cache: {'EXISTS' if redis else 'MISSING'}")
        if redis:
            print(f"    - Timestamp: {redis.get('timestamp')}")
            print(f"    - Ignition: {redis.get('ignition')}")
    
    await pool.close()
    return results

async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        results = await audit_all_devices()
        print(f"\n\nAUDIT COMPLETE. {len(results)} devices audited.")
    else:
        print("Usage: python audit_devices.py --all")
        print("       python audit_devices.py --imei <IMEI>")

if __name__ == "__main__":
    asyncio.run(main())