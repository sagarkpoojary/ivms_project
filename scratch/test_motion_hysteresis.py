import asyncio
import logging
from datetime import datetime, timedelta, timezone
from ingestion.db.handler import DBHandler
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestMotionHysteresis")

async def test_motion_hysteresis():
    dsn = f"postgres://{Config.DB_USER}:{Config.DB_PASS}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
    db = DBHandler(dsn)
    await db.connect()
    
    imei = "864275071228707"
    base_time = datetime.now(timezone.utc)
    
    # 0. Cleanup existing states
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM live_vehicle_status WHERE imei = $1", imei)
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", imei)
        await db.cache.client.delete(f"live:{imei}")
        await db.cache.client.delete(f"motion_state:{imei}")
        
    logger.info("=== 1. Simulating Ignition ON, Speed = 0 (Expected: idle immediately) ===")
    packet_1 = [{
        'timestamp': base_time,
        'priority': 1,
        'longitude': 58.3829,
        'latitude': 23.5880,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 0,
        'event_id': 0,
        'io_elements': {239: '1', 240: '0'} # Ignition ON
    }]
    await db.save_telemetry(imei, packet_1)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'idle', f"Expected idle, got {row['status']}"
        logger.info("Passed: Engine is ON but stationary -> state is 'idle'.")

    logger.info("=== 2. Simulating sudden Speed = 15 km/h for 2 seconds (Expected: still idle due to debounce) ===")
    packet_2 = [{
        'timestamp': base_time + timedelta(seconds=2),
        'priority': 1,
        'longitude': 58.3835,
        'latitude': 23.5885,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 15,
        'event_id': 0,
        'io_elements': {239: '1', 240: '1'} # Ignition ON, Moving
    }]
    await db.save_telemetry(imei, packet_2)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'idle', f"Expected still idle, got {row['status']}"
        logger.info("Passed: Short speed spike did not trigger 'moving'. State remains debounced at 'idle'.")

    logger.info("=== 3. Simulating sustained Speed = 15 km/h for 12 seconds (Expected: moving) ===")
    packet_3 = [{
        'timestamp': base_time + timedelta(seconds=12),
        'priority': 1,
        'longitude': 58.3845,
        'latitude': 23.5895,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 15,
        'event_id': 0,
        'io_elements': {239: '1', 240: '1'} # Ignition ON, Moving
    }]
    await db.save_telemetry(imei, packet_3)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'moving', f"Expected moving, got {row['status']}"
        logger.info("Passed: Sustained speed for 12 seconds correctly triggered transition to 'moving'.")

    logger.info("=== 4. Simulating sudden stop, Speed = 0 for 5 seconds (Expected: still moving due to debounce) ===")
    packet_4 = [{
        'timestamp': base_time + timedelta(seconds=17),
        'priority': 1,
        'longitude': 58.3845,
        'latitude': 23.5895,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 0,
        'event_id': 0,
        'io_elements': {239: '1', 240: '0'} # Ignition ON, Stationary
    }]
    await db.save_telemetry(imei, packet_4)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'moving', f"Expected still moving, got {row['status']}"
        logger.info("Passed: Short stop did not trigger 'idle'. State remains debounced at 'moving'.")

    logger.info("=== 5. Simulating sustained stop, Speed = 0 for 35 seconds (Expected: idle) ===")
    packet_5 = [{
        'timestamp': base_time + timedelta(seconds=48),
        'priority': 1,
        'longitude': 58.3845,
        'latitude': 23.5895,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 0,
        'event_id': 0,
        'io_elements': {239: '1', 240: '0'} # Ignition ON, Stationary
    }]
    await db.save_telemetry(imei, packet_5)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'idle', f"Expected idle, got {row['status']}"
        logger.info("Passed: Sustained standstill for 31 seconds correctly triggered transition to 'idle'.")

    logger.info("=== 6. Simulating Ignition OFF (Expected: ignition_off instantly, bypassing debounce) ===")
    packet_6 = [{
        'timestamp': base_time + timedelta(seconds=50),
        'priority': 1,
        'longitude': 58.3845,
        'latitude': 23.5895,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 0,
        'event_id': 0,
        'io_elements': {239: '0', 240: '0'} # Ignition OFF
    }]
    await db.save_telemetry(imei, packet_6)
    
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM live_vehicle_status WHERE imei = $1", imei)
        assert row['status'] == 'ignition_off', f"Expected ignition_off, got {row['status']}"
        logger.info("Passed: Ignition OFF instantly bypassed all debounce rules and updated to 'ignition_off'.")

    logger.info("\n=== Stateful Motion Hysteresis Engine Verified! Phase 3 PASSED! ===")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(test_motion_hysteresis())
