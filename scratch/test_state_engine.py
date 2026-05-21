import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.db.handler import DBHandler
from services.telemetry_service import telemetry_service
from config import Config

async def run_simulation():
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    handler = DBHandler(db_url)
    await handler.connect()

    test_imei = "864275071228707" # Valid registered test IMEI
    print(f"=== Starting live vehicle state engine simulation for IMEI {test_imei} ===")

    # Setup database connection
    async with handler.pool.acquire() as conn:
        # Check if device is registered in vehicles
        is_reg = await handler.is_imei_registered(test_imei)
        if not is_reg:
            print("ERROR: Test device must be registered in the vehicles table first!")
            return

        # Clean up any existing state
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", test_imei)
        await conn.execute("UPDATE live_vehicle_status SET status = 'offline', ignition = FALSE, speed = 0, last_timestamp = NOW() - INTERVAL '1 day', updated_at = NOW() - INTERVAL '1 hour' WHERE imei = $1", test_imei)
        await handler.cache.client.delete(f"live:{test_imei}")
        await handler.cache.client.delete(f"motion_state:{test_imei}")

        # ----------------------------------------------------
        # Scenario 1: Ignition ON with no movement (Idle status)
        # ----------------------------------------------------
        print("\n--- 1. Simulating Ignition ON, Speed = 0 (Idle) ---")
        base_time = datetime.now(timezone.utc)
        records = [{
            'timestamp': base_time,
            'priority': 1,
            'longitude': 58.12345,
            'latitude': 23.54321,
            'altitude': 100,
            'angle': 0,
            'satellites': 12,
            'speed': 0,
            'event_id': 0,
            'io_elements': {239: 1, 240: 0, 21: 5, 66: 12000, 67: 4200} # Ignition ON, Movement OFF
        }]
        await handler.save_telemetry(test_imei, records)
        
        # Verify DB
        row = await conn.fetchrow("SELECT status, current_status, ignition, speed, packet_age_seconds FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row: status={row['status']}, current_status={row['current_status']}, ignition={row['ignition']}, speed={row['speed']}, packet_age={row['packet_age_seconds']}s")
        assert row['status'] == 'idle', "Failed: status should be idle"

        # Verify Redis Cache
        live = telemetry_service.get_live_status(test_imei)
        print(f"Redis Cache: status={live['status']}, ignition={live['ignition']}, speed={live['speed']}")
        assert live['status'] == 'idle', "Failed Redis status"

        # ----------------------------------------------------
        # Scenario 2: Ignition ON with movement (Moving status)
        # ----------------------------------------------------
        print("\n--- 2. Simulating Ignition ON, Speed = 15 km/h (Moving) ---")
        records[0]['speed'] = 15
        records[0]['io_elements'][240] = 1 # Movement ON
        
        # Send initial moving packet to trigger pending state
        records[0]['timestamp'] = base_time + timedelta(seconds=5)
        await handler.save_telemetry(test_imei, records)
        
        # Send second moving packet 11 seconds later to trigger sustained transition
        records[0]['timestamp'] = base_time + timedelta(seconds=16)
        await handler.save_telemetry(test_imei, records)

        row = await conn.fetchrow("SELECT status, current_status, ignition, speed FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row: status={row['status']}, ignition={row['ignition']}, speed={row['speed']}")
        assert row['status'] == 'moving', "Failed: status should be moving"

        # ----------------------------------------------------
        # Scenario 3: Ignition OFF (Ignition Off / Parked status)
        # ----------------------------------------------------
        print("\n--- 3. Simulating Ignition OFF (ignition_off) ---")
        records[0]['speed'] = 0
        records[0]['io_elements'][239] = 0 # Ignition OFF
        records[0]['io_elements'][240] = 0
        records[0]['timestamp'] = base_time + timedelta(seconds=20)
        await handler.save_telemetry(test_imei, records)

        row = await conn.fetchrow("SELECT status, current_status, ignition, speed FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row: status={row['status']}, ignition={row['ignition']}, speed={row['speed']}")
        assert row['status'] == 'ignition_off', "Failed: status should be ignition_off"

        # ----------------------------------------------------
        # Scenario 4: Sleep mode / Delayed packets / Dynamic Timeout
        # ----------------------------------------------------
        print("\n--- 4. Simulating Dynamic Offline timeouts ---")
        
        # Test 4.a: Ignition is OFF (Parked/Sleeping). Device reported 10 mins ago.
        # It should STILL be classified as ignition_off (NOT offline) because off-timeout is 30 mins (1800s).
        print("Test 4.a: Ignition OFF, last updated 10 minutes ago...")
        await conn.execute("UPDATE live_vehicle_status SET updated_at = NOW() - INTERVAL '10 minutes' WHERE imei = $1", test_imei)
        
        # Run reconcile with (3 mins, 30 mins)
        reconciled = await handler.reconcile_offline_devices(180, 1800)
        print(f"Reconciled count: {reconciled}")
        
        row = await conn.fetchrow("SELECT status, current_status FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row (Should remain ignition_off): status={row['status']}, current_status={row['current_status']}")
        assert row['status'] == 'ignition_off', "Failed: should stay online/ignition_off"

        # Test 4.b: Ignition is OFF, last updated 35 minutes ago...
        # It should now be marked OFFLINE.
        print("Test 4.b: Ignition OFF, last updated 35 minutes ago...")
        await conn.execute("UPDATE live_vehicle_status SET updated_at = NOW() - INTERVAL '35 minutes' WHERE imei = $1", test_imei)
        
        # We need to set last_timestamp in the past to prevent reconcile logic from keeping online
        await conn.execute("UPDATE live_vehicle_status SET last_timestamp = NOW() - INTERVAL '35 minutes' WHERE imei = $1", test_imei)

        reconciled = await handler.reconcile_offline_devices(180, 1800)
        print(f"Reconciled count: {reconciled}")
        
        row = await conn.fetchrow("SELECT status, current_status FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row (Should be offline): status={row['status']}")
        assert row['status'] == 'offline', "Failed: should be offline"

        # Test 4.c: Ignition is ON (Active), last updated 4 minutes ago...
        # It should be marked OFFLINE immediately because ignition ON timeout is 3 mins (180s).
        print("Test 4.c: Ignition ON, last updated 4 minutes ago...")
        await conn.execute("UPDATE live_vehicle_status SET status = 'idle', ignition = TRUE, updated_at = NOW() - INTERVAL '4 minutes', last_timestamp = NOW() - INTERVAL '4 minutes' WHERE imei = $1", test_imei)
        
        reconciled = await handler.reconcile_offline_devices(180, 1800)
        print(f"Reconciled count: {reconciled}")
        
        row = await conn.fetchrow("SELECT status, current_status FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row (Should be offline): status={row['status']}")
        assert row['status'] == 'offline', "Failed: should be offline"

        # ----------------------------------------------------
        # Scenario 5: Reconnect behavior
        # ----------------------------------------------------
        print("\n--- 5. Simulating Reconnect (New packet after offline) ---")
        records[0]['timestamp'] = base_time + timedelta(seconds=30)
        await handler.save_telemetry(test_imei, records)

        row = await conn.fetchrow("SELECT status, current_status FROM live_vehicle_status WHERE imei = $1", test_imei)
        print(f"DB Row (Should be ignition_off): status={row['status']}")
        assert row['status'] == 'ignition_off', "Failed: should reconnect to ignition_off"

        print("\n=== State Engine Simulation completed successfully! All assertions PASSED! ===")

if __name__ == '__main__':
    asyncio.run(run_simulation())
