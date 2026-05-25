import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set dummy environment variables to prevent loading config exceptions
os.environ["FLASK_SECRET"] = "dummy"
os.environ["IVMS_API_URL"] = "http://localhost:8000"
os.environ["ODOO_REPORT_TOKEN"] = "dummy"
os.environ["SMTP_USER"] = "dummy"
os.environ["SMTP_PASS"] = "dummy"

from api.main import get_bulk_sync, cache
from core.cache import LiveCache
from starlette.requests import Request
import asyncpg
import redis.asyncio as redis

async def test_cache_resiliency():
    print("=== TESTING CACHE RESILIENCY AND DATABASE REHYDRATION ===")
    
    # 1. Verify Redis keys count
    live_cache = LiveCache()
    await live_cache.connect()
    keys = await live_cache.client.keys("live:*")
    print(f"Initial Redis 'live:*' keys count: {len(keys)}")
    
    # 2. Setup mock DB and user session
    DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    db = await asyncpg.connect(DB_URL)
    
    # Subscriptable mock user dictionary
    mock_user = {
        "email": "sagar@conceptgrps.com",
        "role": "super_admin"
    }
    
    # Mock Starlette Request for Limiter validation
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "path": "/api/dashboard/bulk-sync",
        "query_string": b"",
        "server": ("127.0.0.1", 80),
        "client": ("127.0.0.1", 50000)
    }
    mock_request = Request(scope)
    
    # 3. Trigger get_bulk_sync
    print("\nExecuting get_bulk_sync API with mock request and user...")
    result = await get_bulk_sync(
        request=mock_request,
        period="Today",
        uid=None,
        environment="production",
        user=mock_user,
        db=db
    )
    
    devices = result.get("devices", [])
    summaries = result.get("summaries", {})
    print(f"API returned {len(devices)} devices:")
    
    has_gps = 0
    for d in devices:
        uid = d.get("uniqueId")
        status = d.get("status")
        lat = d.get("latitude")
        lon = d.get("longitude")
        summ = summaries.get(uid, {})
        print(f"  - Device {uid}: status={status}, GPS=({lat}, {lon})")
        print(f"    Summary -> dist: {summ.get('distance')} km, engineHours: {summ.get('engineHours')} h, fuel: {summ.get('fuelLiters')} L")
        if lat is not None and lon is not None:
            has_gps += 1
            
    print(f"\nTotal devices returned with valid GPS: {has_gps}")
    
    # 4. Wait a brief moment for the background rehydration task to finish
    print("\nWaiting 2 seconds for Redis rehydration tasks to finish...")
    await asyncio.sleep(2)
    
    # 5. Check Redis again to prove rehydration worked
    keys_after = await live_cache.client.keys("live:*")
    print(f"Final Redis 'live:*' keys count: {len(keys_after)}")
    
    await db.close()
    await live_cache.disconnect()
    
    if len(keys_after) > 0 and has_gps > 0:
        print("\n🎉 SUCCESS: DATABASE POSITION FALLBACK AND CACHE AUTO-HEALING WORKED PERFECTLY!")
        return True
    else:
        print("\n❌ FAILURE: Cache did not auto-heal.")
        return False

if __name__ == "__main__":
    asyncio.run(test_cache_resiliency())
