import asyncpg
import json
import logging
from datetime import datetime
from config import Config, BASE_DIR
from core.cache import LiveCache
from analytics.engine import AnalyticsEngine

logger = logging.getLogger(__name__)

class DBHandler:
    def __init__(self, dsn):
        self.dsn = dsn
        self.pool = None
        self.cache = LiveCache()
        self.analytics = AnalyticsEngine(self, self.cache)

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(dsn=self.dsn)
            await self.cache.connect()
            logger.info("Successfully connected to PostgreSQL pool and Redis")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    async def is_imei_registered(self, imei):
        """Checks if the device is whitelisted in the vehicles table."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 FROM vehicles WHERE unique_id = $1", str(imei))
            return row is not None

    async def log_alert(self, severity, component, message, imei=None):
        """Logs a system-level alert or critical failure."""
        if not self.pool:
            try: await self.connect()
            except: return # Fail silently if DB is completely unreachable
            
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO system_alerts (severity, component, message, affected_imei) VALUES ($1, $2, $3, $4)",
                    severity, component, message, str(imei) if imei else None
                )
                # Also log to centralized system_events
                await self.save_system_event(imei, severity, 'System', component, message)
        except Exception as e:
            logger.error(f"Failed to write to system_alerts: {e}")

    async def save_system_event(self, imei, severity, category, title, description, raw_payload=None, latitude=None, longitude=None, driver_id=None):
        """Centralized method to log enterprise events and queue notifications."""
        if not self.pool: await self.connect()
        try:
            async with self.pool.acquire() as conn:
                # 1. Get tenant_id (parent_email) and vehicle name
                vehicle = await conn.fetchrow("SELECT parent_email, name FROM vehicles WHERE unique_id = $1", str(imei))
                tenant_id = vehicle['parent_email'] if vehicle else None
                
                # 2. Save Event
                event_row = await conn.fetchrow(
                    """INSERT INTO system_events (tenant_id, vehicle_id, imei, driver_id, severity, category, title, description, raw_payload, latitude, longitude)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id""",
                    tenant_id, vehicle['name'] if vehicle else None, str(imei), driver_id, severity, category, title, description, 
                    json.dumps(raw_payload) if raw_payload else None, latitude, longitude
                )
                event_id = event_row['id']

                # 3. Queue Notification for relevant severities
                if severity in ['CRITICAL', 'WARNING', 'SECURITY', 'MAINTENANCE']:
                    # We queue for the tenant (Main Admin/Admin)
                    await conn.execute(
                        """INSERT INTO notification_queue (tenant_id, event_id, severity, title, message)
                           VALUES ($1, $2, $3, $4, $5)""",
                        tenant_id, event_id, severity, title, description
                    )

                # 4. Notify via Redis Pub/Sub for real-time WebSocket broadcast
                event_msg = {
                    "type": "notification",
                    "id": event_id,
                    "imei": str(imei),
                    "severity": severity,
                    "category": category,
                    "title": title,
                    "message": description,
                    "created_at": datetime.now().isoformat()
                }
                await self.cache.client.publish("live_updates", json.dumps(event_msg))

        except Exception as e:
            logger.error(f"Failed to save system event: {e}")

    async def save_telemetry(self, imei, records):
        if not self.pool:
            await self.connect()
            
        async with self.pool.acquire() as conn:
            # 1. Verify if device is registered in the IVMS vehicles table
            vehicle = await conn.fetchrow(
                "SELECT unique_id, name FROM vehicles WHERE unique_id = $1",
                str(imei)
            )
            
            if not vehicle:
                # IMPORTANT: In production, we reject telemetry from unregistered devices
                # to prevent demo/mock/ghost data from polluting the native dashboard.
                logger.warning(f"REJECTED: Telemetry received for UNREGISTERED device {imei}")
                await self.log_alert('WARNING', 'Security', f"Unauthorized telemetry attempt from unregistered device {imei}", imei)
                return

            # 2. Ensure a record exists in 'devices' table (primary tracking)
            # This is still needed for FK consistency if the system uses 'devices' table elsewhere.
            device = await conn.fetchrow(
                "INSERT INTO devices (imei) VALUES ($1) ON CONFLICT (imei) DO UPDATE SET last_connected = NOW() RETURNING id",
                str(imei)
            )
            device_id = device['id']
            
            # 2. Batch insert telemetry
            telemetry_data = []
            for r in records:
                telemetry_data.append((
                    device_id,
                    str(imei),
                    r['timestamp'],
                    r['priority'],
                    r['longitude'],
                    r['latitude'],
                    r['altitude'],
                    r['angle'],
                    r['satellites'],
                    r['speed'],
                    r['event_id'],
                    json.dumps(r['io_elements'])
                ))
            
            await conn.executemany(
                """INSERT INTO telemetry (device_id, imei, timestamp, priority, longitude, latitude, altitude, angle, satellites, speed, event_id, io_elements)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                   ON CONFLICT (imei, timestamp) DO NOTHING""",
                telemetry_data
            )
            
            # 3. Update live status (latest record only)
            latest = records[-1]
            io = latest['io_elements']
            
            # Teltonika standard IO IDs
            ignition = str(io.get(239, io.get(1, '0'))) == '1'
            movement = str(io.get(240, '0')) == '1'
            gsm = int(io.get(21, 0))
            ext_v = float(io.get(66, 0)) / 1000.0
            bat_v = float(io.get(67, 0)) / 1000.0
            rfid = str(io.get(78, '')) # iButton/RFID
            
            # 4. RFID & Driver Mapping
            driver_id = None
            driver_name = None
            
            if rfid and rfid != '0':
                # Lookup driver by RFID
                driver = await conn.fetchrow(
                    "SELECT driver_id, name FROM drivers WHERE rfid_tag = $1",
                    str(rfid)
                )
                
                if driver:
                    driver_id = driver['driver_id']
                    driver_name = driver['name']
                    
                    # Log RFID Swipe Event
                    await conn.execute(
                        """INSERT INTO rfid_events (imei, driver_id, rfid_tag, event_type, timestamp, latitude, longitude, ignition)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        str(imei), driver_id, str(rfid), 'swipe', latest['timestamp'], 
                        latest['latitude'], latest['longitude'], ignition
                    )

                    # Manage Driver Session
                    await self.sync_driver_session(conn, imei, driver_id, latest['timestamp'], ignition)
                else:
                    # Log Unknown Tag Event
                    await conn.execute(
                        """INSERT INTO rfid_events (imei, rfid_tag, event_type, timestamp, latitude, longitude, ignition)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        str(imei), str(rfid), 'unknown_tag', latest['timestamp'],
                        latest['latitude'], latest['longitude'], ignition
                    )

            # 5. Trip & Analytics Logic
            # Process the latest record through the analytics engine
            await self.analytics.process_telemetry(imei, {
                **latest,
                "ignition": ignition,
                "rfid": rfid,
                "driver_id": driver_id,
                "driver_name": driver_name
            })

            # Status Standardization for Frontend (Phase 14)
            speed = latest.get('speed', 0)
            if speed > 2:
                status = "moving"
            elif ignition:
                status = "idle"
            else:
                status = "online" # Engine off but communicating

            # 6. Update Live Status (Database)
            await conn.execute(
                """INSERT INTO live_vehicle_status (
                    imei, device_id, last_timestamp, longitude, latitude, speed, 
                    ignition, movement, gsm_signal, external_voltage, battery_voltage, status,
                    current_driver_id, current_driver_name
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (imei) DO UPDATE SET
                    last_timestamp = EXCLUDED.last_timestamp,
                    longitude = EXCLUDED.longitude,
                    latitude = EXCLUDED.latitude,
                    speed = EXCLUDED.speed,
                    ignition = EXCLUDED.ignition,
                    movement = EXCLUDED.movement,
                    gsm_signal = EXCLUDED.gsm_signal,
                    external_voltage = EXCLUDED.external_voltage,
                    battery_voltage = EXCLUDED.battery_voltage,
                    status = EXCLUDED.status,
                    current_driver_id = EXCLUDED.current_driver_id,
                    current_driver_name = EXCLUDED.current_driver_name,
                    updated_at = NOW()""",
                str(imei), device_id, latest['timestamp'], latest['longitude'], latest['latitude'], 
                latest['speed'], ignition, movement, gsm, ext_v, bat_v, status,
                driver_id, driver_name
            )
            
            # 7. Update Redis Cache (Detailed for Dashboard)
            live_status = {
                'imei': str(imei),
                'timestamp': latest['timestamp'].isoformat(),
                'longitude': latest['longitude'],
                'latitude': latest['latitude'],
                'speed': latest['speed'],
                'ignition': ignition,
                'movement': movement,
                'gsm': gsm,
                'ext_v': ext_v,
                'bat_v': bat_v,
                'rfid': rfid,
                'driver_id': driver_id,
                'driver_name': driver_name or ("Unknown Tag" if (rfid and rfid != '0') else "No Driver"),
                'is_registered': vehicle is not None,
                'vehicle_name': vehicle['vehicle_name'] if vehicle and 'vehicle_name' in vehicle else (vehicle['name'] if vehicle and 'name' in vehicle else "Unassigned Device")
            }
            await self.cache.update_status(str(imei), live_status)
            
            logger.info(f"Processed {len(records)} records for {imei} | Driver: {driver_name or 'None'}")


    async def save_analytics_event(self, imei, event_type, data):
        """Helper for AnalyticsEngine to persist events."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO analytics_events (imei, event_type, timestamp, latitude, longitude, value) VALUES ($1, $2, $3, $4, $5, $6)",
                str(imei), event_type, data['timestamp'], data.get('latitude'), data.get('longitude'), data.get('speed')
            )

    async def sync_driver_session(self, conn, imei, driver_id, timestamp, ignition):
        """Manages driver login/logout lifecycle in the database."""
        # 1. Check for current active session on this device
        active = await conn.fetchrow(
            "SELECT id, driver_id FROM driver_sessions WHERE imei = $1 AND logout_time IS NULL",
            str(imei)
        )
        
        if active:
            if active['driver_id'] == driver_id:
                # Same driver, just continue session (could update ignition state if needed)
                return
            else:
                # Different driver! Close previous session
                await conn.execute(
                    "UPDATE driver_sessions SET logout_time = $1 WHERE id = $2",
                    timestamp, active['id']
                )
                
                # Close previous driver's RFID events with 'logout'
                await conn.execute(
                    "INSERT INTO rfid_events (imei, driver_id, event_type, timestamp) VALUES ($1, $2, $3, $4)",
                    str(imei), active['driver_id'], 'logout', timestamp
                )

        # 2. Start new session
        await conn.execute(
            "INSERT INTO driver_sessions (driver_id, imei, login_time, ignition_state) VALUES ($1, $2, $3, $4)",
            driver_id, str(imei), timestamp, ignition
        )
        
        # Log login event
        await conn.execute(
            "INSERT INTO rfid_events (imei, driver_id, event_type, timestamp) VALUES ($1, $2, $3, $4)",
            str(imei), driver_id, 'login', timestamp
        )

    async def rebuild_cache_from_db(self):
        """Fetches all live status records and repopulates Redis."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM live_vehicle_status")
            count = 0
            for row in rows:
                status = {
                    'imei': row['imei'],
                    'timestamp': row['last_timestamp'].isoformat() if row['last_timestamp'] else None,
                    'longitude': float(row['longitude']) if row['longitude'] else 0,
                    'latitude': float(row['latitude']) if row['latitude'] else 0,
                    'speed': row['speed'],
                    'ignition': row['ignition'],
                    'status': row['status'],
                    'driver_id': row['current_driver_id'],
                    'driver_name': row['current_driver_name']
                }
                await self.cache.update_status(row['imei'], status)
                count += 1
            return count

    async def reconcile_offline_devices(self, timeout_seconds):
        """Finds devices that haven't sent data within the timeout and marks them offline."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            # Find devices that are not already offline but their last timestamp is older than timeout
            query = """
                SELECT imei, last_timestamp
                FROM live_vehicle_status 
                WHERE status != 'offline' AND last_timestamp < NOW() - INTERVAL '1 second' * $1
            """
            offline_devices = await conn.fetch(query, timeout_seconds)
            
            if not offline_devices:
                return 0

            count = 0
            for row in offline_devices:
                imei = row['imei']
                
                # Update DB to offline
                await conn.execute(
                    "UPDATE live_vehicle_status SET status = 'offline', updated_at = NOW() WHERE imei = $1",
                    imei
                )
                
                # Update Redis
                existing_cache = await self.cache.get_status(imei)
                if existing_cache:
                    existing_cache['status'] = 'offline'
                    await self.cache.update_status(imei, existing_cache)
                else:
                    # Fallback if not in cache but in DB
                    live_status = {
                        'imei': imei,
                        'timestamp': row['last_timestamp'].isoformat() if row['last_timestamp'] else None,
                        'status': 'offline'
                    }
                    await self.cache.update_status(imei, live_status)
                
                count += 1
                logger.info(f"Marked device {imei} as OFFLINE (No data for > {timeout_seconds}s)")
                await self.log_alert('WARNING', 'Connection', f"Device {imei} went offline (Timeout: {timeout_seconds}s)", imei)
                
            return count

