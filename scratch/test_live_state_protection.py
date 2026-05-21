import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from ingestion.db.handler import DBHandler
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestLiveStateProtection")

async def test_live_state_protection():
    # Load DSN
    dsn = f"postgres://{Config.DB_USER}:{Config.DB_PASS}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
    db = DBHandler(dsn)
    await db.connect()
    
    imei = "864275071228707"
    
    # Define a fresh real-time timestamp
    now = datetime.now(timezone.utc)
    ts_fresh = now
    ts_stale = now - timedelta(hours=1)
    
    logger.info(f" ts_fresh: {ts_fresh.isoformat()}")
    logger.info(f" ts_stale: {ts_stale.isoformat()}")

    # Clean up existing live status so we start fresh
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM live_vehicle_status WHERE imei = $1", imei)
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", imei)
        await db.cache.client.delete(f"live:{imei}")
        await db.cache.client.delete(f"motion_state:{imei}")

    # 1. Send FRESH real-time packets to transition state to MOVING
    packet_fresh_1 = [{
        'timestamp': ts_fresh - timedelta(seconds=12),
        'priority': 1,
        'longitude': 58.3820,
        'latitude': 23.5870,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 60,
        'event_id': 0,
        'io_elements': {239: '1', 240: '1', 21: '5', 66: '12000', 67: '3700'} # Ignition ON
    }]
    
    packet_fresh_2 = [{
        'timestamp': ts_fresh,
        'priority': 1,
        'longitude': 58.3829,
        'latitude': 23.5880,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 60,
        'event_id': 0,
        'io_elements': {239: '1', 240: '1', 21: '5', 66: '12000', 67: '3700'} # Ignition ON
    }]
    
    logger.info("=== Sending FRESH real-time packets ===")
    await db.save_telemetry(imei, packet_fresh_1)
    await db.save_telemetry(imei, packet_fresh_2)

    # Verify live DB status is updated to moving at 60 km/h
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_timestamp, speed, status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row is not None, "Error: Live vehicle status was not created!"
        assert row['speed'] == 60, f"Error: Speed is {row['speed']}, expected 60"
        assert row['status'] == 'moving', f"Error: Status is {row['status']}, expected 'moving'"
        logger.info(f"Success: DB live status updated perfectly to Speed: {row['speed']}, Status: {row['status']}")

    # Verify Redis status
    redis_status = await db.cache.get_status(imei)
    assert redis_status is not None, "Error: Redis status cache was not populated!"
    assert float(redis_status['speed']) == 60, f"Error: Redis speed is {redis_status['speed']}, expected 60"
    logger.info("Success: Redis live cache populated perfectly with fresh real-time packet data.")

    # 2. Send STALE historical buffered packet (Stationary at 0 km/h from 1 hour ago)
    packet_stale = [{
        'timestamp': ts_stale,
        'priority': 1,
        'longitude': 58.3000,
        'latitude': 23.5000,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 0,
        'event_id': 0,
        'io_elements': {239: '0', 240: '0', 21: '5', 66: '12000', 67: '3700'} # Ignition OFF
    }]

    logger.info("=== Sending STALE historical buffered packet ===")
    await db.save_telemetry(imei, packet_stale)

    # 3. VERIFY LIVE STATE PROTECTION CONSTRAINTS
    # A. Stale packet MUST be in telemetry history table
    async with db.pool.acquire() as conn:
        telemetry_rows = await conn.fetch("SELECT speed, timestamp FROM telemetry WHERE imei = $1 ORDER BY timestamp ASC", imei)
        assert len(telemetry_rows) == 3, f"Error: Telemetry table has {len(telemetry_rows)} records, expected 3"
        logger.info("Success: All fresh and stale telemetry packets successfully inserted into historical timeseries table.")

    # B. Stale packet MUST NOT overwrite live status table (remains Speed: 60, Status: moving)
    async with db.pool.acquire() as conn:
        row_after = await conn.fetchrow("SELECT last_timestamp, speed, status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row_after['speed'] == 60, f"Violation: Stale packet overwrote live speed to {row_after['speed']}!"
        assert row_after['status'] == 'moving', f"Violation: Stale packet overwrote live status to {row_after['status']}!"
        logger.info("Success: Stale packet bypassed live vehicle status perfectly! Status remains 'moving' at 60 km/h.")

    # C. Stale packet MUST NOT overwrite Redis Cache
    redis_after = await db.cache.get_status(imei)
    assert float(redis_after['speed']) == 60, f"Violation: Stale packet overwrote Redis speed to {redis_after['speed']}!"
    assert redis_after['status'] == 'moving', f"Violation: Stale packet overwrote Redis status to {redis_after['status']}!"
    logger.info("Success: Stale packet bypassed Redis status cache perfectly! Cache remains 'moving' at 60 km/h.")

    logger.info("\n=== Chronological Packet Protection & Live-State Overwrite Protection Verified! Phase 1 PASSED! ===")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(test_live_state_protection())
