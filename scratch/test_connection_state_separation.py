import asyncio
import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from ingestion.db.handler import DBHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestConnectionStateSeparation")

async def test_disconnect():
    load_dotenv()
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    handler = DBHandler(db_url)
    await handler.connect()
    
    test_imei = "864275071228707" # Valid registered test IMEI
    logger.info(f"=== Starting Connection-State Separation Integration Test for IMEI {test_imei} ===")

    async with handler.pool.acquire() as conn:
        # Clean up existing state
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", test_imei)
        await conn.execute("DELETE FROM live_vehicle_status WHERE imei = $1", test_imei)
        await handler.cache.client.delete(f"live:{test_imei}")
        await handler.cache.client.delete(f"motion_state:{test_imei}")

        # 1. Simulate an active vehicle packet (Moving at 60 km/h with Ignition ON)
        logger.info("Step 1: Simulating active vehicle moving packet...")
        base_time = datetime.now(timezone.utc)
        records = [{
            'timestamp': base_time,
            'priority': 1,
            'longitude': 58.12345,
            'latitude': 23.54321,
            'altitude': 100,
            'angle': 90,
            'satellites': 12,
            'speed': 60,
            'event_id': 0,
            'io_elements': {239: 1, 240: 1, 21: 5, 66: 12000, 67: 4200} # Ignition ON, Movement ON
        }]
        
        # Save telemetry to transition to moving (note: hysteresis needs multiple points or ignition on)
        # We'll save twice to trigger hysteresis moving state
        await handler.save_telemetry(test_imei, records)
        # Direct insert to ensure moving state
        await conn.execute(
            """UPDATE live_vehicle_status 
               SET status = 'moving', speed = 60, ignition = TRUE, movement = TRUE 
               WHERE imei = $1""",
            test_imei
        )
        # Seed cache
        await handler.cache.update_status(test_imei, {
            "imei": test_imei,
            "status": "moving",
            "speed": 60,
            "ignition": True,
            "movement": True,
            "timestamp": base_time.isoformat()
        })
        # Seed hysteresis
        await handler.cache.client.set(f"motion_state:{test_imei}", json.dumps({
            "state": "moving",
            "pending_state": None,
            "pending_since": None
        }))

        # Verify initial active states
        db_row = await conn.fetchrow("SELECT status, speed, ignition, movement FROM live_vehicle_status WHERE imei = $1", test_imei)
        logger.info(f"Initial DB: status={db_row['status']}, speed={db_row['speed']}, ignition={db_row['ignition']}, movement={db_row['movement']}")
        assert db_row['status'] == 'moving', "Initial status must be moving"
        assert db_row['speed'] == 60, "Initial speed must be 60"
        assert db_row['ignition'] is True, "Initial ignition must be True"

        cache_val = await handler.cache.get_status(test_imei)
        logger.info(f"Initial Redis: status={cache_val['status']}, speed={cache_val['speed']}, ignition={cache_val['ignition']}, movement={cache_val['movement']}")
        assert cache_val['status'] == 'moving', "Initial Redis status must be moving"

        # 2. Simulate Active TCP Disconnect (calls mark_device_offline)
        logger.info("Step 2: Simulating active physical TCP disconnect...")
        await handler.mark_device_offline(test_imei)

        # 3. Verify Offline Transition and State Reset
        logger.info("Step 3: Verifying offline transition and state resets in DB and Redis...")
        
        # Verify DB
        db_row_after = await conn.fetchrow("SELECT status, speed, ignition, movement FROM live_vehicle_status WHERE imei = $1", test_imei)
        logger.info(f"Post-Disconnect DB: status={db_row_after['status']}, speed={db_row_after['speed']}, ignition={db_row_after['ignition']}, movement={db_row_after['movement']}")
        assert db_row_after['status'] == 'offline', "Status should be offline"
        assert db_row_after['speed'] == 0, "Speed should be reset to 0"
        assert db_row_after['ignition'] is False, "Ignition should be reset to False"
        assert db_row_after['movement'] is False, "Movement should be reset to False"

        # Verify Redis Live Cache
        cache_val_after = await handler.cache.get_status(test_imei)
        logger.info(f"Post-Disconnect Redis: status={cache_val_after['status']}, speed={cache_val_after['speed']}, ignition={cache_val_after['ignition']}, movement={cache_val_after['movement']}")
        assert cache_val_after['status'] == 'offline', "Redis status should be offline"
        assert cache_val_after['speed'] == 0, "Redis speed should be reset to 0"
        assert cache_val_after['ignition'] is False, "Redis ignition should be reset to False"

        # Verify Redis Motion State Reset
        motion_state = json.loads(await handler.cache.client.get(f"motion_state:{test_imei}"))
        logger.info(f"Post-Disconnect Hysteresis State: {motion_state}")
        assert motion_state['state'] == 'offline', "Hysteresis state should be reset to offline"

        logger.info("\n=== SUCCESS: Connection-State Separation Integration Test PASSED! ===")

    await handler.disconnect()

if __name__ == '__main__':
    asyncio.run(test_disconnect())
