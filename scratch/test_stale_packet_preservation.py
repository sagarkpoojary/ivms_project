import asyncio
import logging
import time
import os
from datetime import datetime, timedelta
from ingestion.db.handler import DBHandler
from services.native_report_service import NativeReportService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestStalePacketPreservation")

async def test_stale_packet_preservation():
    logger.info("=== Starting Live vs Historical Telemetry Separation Verification ===")
    
    db_user = os.getenv('DB_USER', 'ivmsuser')
    db_pass = os.getenv('DB_PASS', 'ivms_secure_2026')
    db_host = os.getenv('DB_HOST', 'db')
    db_name = os.getenv('DB_NAME', 'ivmsdb')
    dsn = f"postgres://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
    
    handler = DBHandler(dsn)
    await handler.connect()
    
    imei = "864275071228707"
    
    # Check if vehicle exists
    async with handler.pool.acquire() as conn:
        vehicle = await conn.fetchrow("SELECT 1 FROM vehicles WHERE unique_id = $1", imei)
        if not vehicle:
            # Seed a whitelist vehicle for verification
            await conn.execute("INSERT INTO vehicles (unique_id, name, status) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", imei, "E2E Verification Vehicle", "active")
            logger.info(f"Seeded vehicle whitelist for IMEI {imei}")
            
        # Clean previous telemetry for this imei to make verification clean
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", imei)
        await conn.execute("DELETE FROM live_vehicle_status WHERE imei = $1", imei)
        logger.info(f"Cleaned historical tables for clean verification run.")

    from datetime import timezone
    now = datetime.now(timezone.utc)
    t_live = now
    t_stale = now - timedelta(minutes=15)
    
    # 1. Send LIVE packet (T_live)
    logger.info("--- Step 1: Sending LIVE Packet (T_live = Now) ---")
    live_records = [{
        'timestamp': t_live,
        'priority': 1,
        'longitude': 58.12345,
        'latitude': 23.12345,
        'altitude': 100,
        'angle': 90,
        'satellites': 10,
        'speed': 50,
        'event_id': 0,
        'io_elements': {239: 1} # Ignition ON
    }]
    await handler.save_telemetry(imei, live_records)
    
    # Verify live_vehicle_status updated
    async with handler.pool.acquire() as conn:
        live_status = await conn.fetchrow("SELECT last_timestamp, speed, status FROM live_vehicle_status WHERE imei = $1", imei)
        assert live_status is not None, "Error: Live vehicle status was not created!"
        assert abs((live_status['last_timestamp'] - t_live).total_seconds()) < 1.0, f"Error: Live timestamp mismatch! Got {live_status['last_timestamp']}, expected {t_live}"
        logger.info("Passed: LIVE status created successfully in live_vehicle_status table.")

    # 2. Send STALE packet (T_stale = Now - 15 minutes)
    logger.info("--- Step 2: Sending STALE Packet (T_stale = Now - 15 minutes) ---")
    stale_records = [{
        'timestamp': t_stale,
        'priority': 1,
        'longitude': 58.55555,
        'latitude': 23.55555,
        'altitude': 120,
        'angle': 180,
        'satellites': 8,
        'speed': 30, # Different speed
        'event_id': 0,
        'io_elements': {239: 1}
    }]
    await handler.save_telemetry(imei, stale_records)
    
    # Verify live_vehicle_status is NOT updated by stale packet (retains T_live)
    async with handler.pool.acquire() as conn:
        live_status_after = await conn.fetchrow("SELECT last_timestamp, speed FROM live_vehicle_status WHERE imei = $1", imei)
        assert abs((live_status_after['last_timestamp'] - t_live).total_seconds()) < 1.0, "Error: Live status was overwritten by stale packet!"
        logger.info(f"Passed: Live status protected! Live status timestamp remains {live_status_after['last_timestamp']} (did not roll back to stale packet at {t_stale}).")

    # 3. Verify BOTH live and stale packets exist in raw historical telemetry
    logger.info("--- Step 3: Verifying Raw Telemetry Table Persistence ---")
    async with handler.pool.acquire() as conn:
        telemetry_rows = await conn.fetch("SELECT timestamp, speed FROM telemetry WHERE imei = $1 ORDER BY timestamp ASC", imei)
        assert len(telemetry_rows) == 2, f"Error: Expected 2 rows in telemetry table, got {len(telemetry_rows)}"
        logger.info(f"Passed: All {len(telemetry_rows)} packets successfully preserved in historical telemetry table.")

    # 4. Verify Report Engine query retrieves both packets
    logger.info("--- Step 4: Verifying Report Engine Integration ---")
    start_dt = now - timedelta(hours=1)
    end_dt = now + timedelta(hours=1)
    playback_data = NativeReportService.get_playback_data(imei, start_dt, end_dt)
    
    assert len(playback_data) == 2, f"Error: Report service playback data returned {len(playback_data)} records instead of 2!"
    logger.info("Passed: Report engine query successfully retrieves both live and stale packets from historical tables.")

    # Clean up test records
    async with handler.pool.acquire() as conn:
        await conn.execute("DELETE FROM telemetry WHERE imei = $1", imei)
        await conn.execute("DELETE FROM live_vehicle_status WHERE imei = $1", imei)
        logger.info("Cleaned up database verifications.")

    await handler.disconnect()
    logger.info("\n=== Live vs Historical Telemetry Separation PASSED! ===")

if __name__ == "__main__":
    asyncio.run(test_stale_packet_preservation())
