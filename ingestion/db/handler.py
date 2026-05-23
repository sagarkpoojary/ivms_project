import asyncpg
import json
import logging
from datetime import datetime, timezone
from config import Config, BASE_DIR
from core.cache import LiveCache
from core.reconciliation import LivePositionReconciliationEngine
from ingestion.analytics.engine import AnalyticsEngine

logger = logging.getLogger(__name__)

class DBHandler:
    def __init__(self, dsn):
        self.dsn = dsn
        self.pool = None
        self.cache = LiveCache()
        self.analytics = AnalyticsEngine(self, self.cache)
        self.hysteresis = None
        self.reconciliation_engine = None  # Initialized on connect

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(dsn=self.dsn)
            await self.cache.connect()
            
            # Initialize reconciliation engine with Redis client
            self.reconciliation_engine = LivePositionReconciliationEngine(
                db_pool=self.pool,
                redis_client=self.cache.client
            )
            
            # Rebuild Redis cache from DB on startup
            try:
                count = await self.reconciliation_engine.rebuild_redis_cache_from_db()
                logger.info(f"[STARTUP] Redis cache initialized with {count} live positions")
            except Exception as e:
                logger.warning(f"[STARTUP] Redis cache rebuild failed (non-critical): {e}")
            
            from ingestion.hysteresis import MotionHysteresisEngine
            self.hysteresis = MotionHysteresisEngine(self.cache.client)
            logger.info("Successfully connected to PostgreSQL pool, Redis, and initialized reconciliation engine")
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

    async def log_alert(self, severity, component, message, imei=None, conn=None):
        """Logs a system-level alert or critical failure."""
        if not self.pool:
            try: await self.connect()
            except: return # Fail silently if DB is completely unreachable
            
        conn_context = None
        if conn is None:
            conn_context = self.pool.acquire()
            conn = await conn_context.__aenter__()
            
        try:
            await conn.execute(
                "INSERT INTO system_alerts (severity, component, message, affected_imei) VALUES ($1, $2, $3, $4)",
                severity, component, message, str(imei) if imei else None
            )
            # Also log to centralized system_events
            await self.save_system_event(imei, severity, 'System', component, message, conn=conn)
        except Exception as e:
            logger.error(f"Failed to write to system_alerts: {e}")
        finally:
            if conn_context is not None:
                await conn_context.__aexit__(None, None, None)

    async def save_system_event(self, imei, severity, category, title, description, raw_payload=None, latitude=None, longitude=None, driver_id=None, conn=None):
        """Centralized method to log enterprise events with Storm Control (Deduplication)."""
        if not self.pool: await self.connect()
        
        # --- PHASE 2: Event Storm Control (Deduplication & Escalation) ---
        cooldown_key = f"event_cooldown:{imei}:{category}"
        count_key = f"event_count:{imei}:{category}"
        
        if await self.cache.client.get(cooldown_key):
            count = await self.cache.client.incr(count_key)
            await self.cache.client.expire(count_key, 600) # 10 minute window
            
            if count >= 3 and severity == 'WARNING':
                severity = 'CRITICAL' # Escalate persistent warnings
            elif count >= 5:
                return # Suppress persistent spam
            else:
                return # Normal suppression
        
        # Set cooldown for this event type
        await self.cache.client.setex(cooldown_key, 300, "1") # 5 minute cooldown
        # ---------------------------------------------------

        conn_context = None
        if conn is None:
            conn_context = self.pool.acquire()
            conn = await conn_context.__aenter__()

        try:
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
            # Priority classes: CRITICAL, SECURITY, WARNING, MAINTENANCE, INFO
            if severity in ['CRITICAL', 'WARNING', 'SECURITY']:
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
        finally:
            if conn_context is not None:
                await conn_context.__aexit__(None, None, None)

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
                await self.log_alert('WARNING', 'Security', f"Unauthorized telemetry attempt from unregistered device {imei}", imei, conn=conn)
                return

            # Sort records chronologically by their device timestamp to enforce correct sequencing
            records = sorted(records, key=lambda r: r['timestamp'])

            # 2. Ensure a record exists in 'devices' table (primary tracking)
            # This is still needed for FK consistency if the system uses 'devices' table elsewhere.
            device = await conn.fetchrow(
                "INSERT INTO devices (imei) VALUES ($1) ON CONFLICT (imei) DO UPDATE SET last_connected = NOW() RETURNING id",
                str(imei)
            )
            device_id = device['id']
            
            # 2. Batch insert telemetry  - also capture the telemetry IDs
            latest_telemetry_id = None
            for r in records:
                # Insert each record individually to get the ID back
                try:
                    row = await conn.fetchrow(
                        """INSERT INTO telemetry 
                           (device_id, imei, timestamp, priority, longitude, latitude, altitude, 
                            angle, satellites, speed, event_id, io_elements) 
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) 
                           ON CONFLICT (imei, timestamp) DO NOTHING
                           RETURNING id""",
                        device_id, str(imei), r['timestamp'], r['priority'],
                        r['longitude'], r['latitude'], r['altitude'], r['angle'],
                        r['satellites'], r['speed'], r['event_id'],
                        json.dumps(r['io_elements'])
                    )
                    if row:
                        latest_telemetry_id = row['id']
                except Exception as e:
                    logger.error(f"Failed to insert telemetry for {imei}: {e}")
                    continue
            
            latest = records[-1]
            
            # Ensure timestamp is UTC-aware
            if latest['timestamp'].tzinfo is None:
                latest['timestamp'] = latest['timestamp'].replace(tzinfo=timezone.utc)
            
            logger.debug(f"[TELEMETRY_INSERTED] {imei}: Latest packet from device at {latest['timestamp'].isoformat()}, DB telemetry_id={latest_telemetry_id}")
            
            io = latest['io_elements']
            
            # Parse IO elements
            ignition = str(io.get(239, io.get(1, '0'))) == '1'
            movement = str(io.get(240, '0')) == '1'
            gsm = int(io.get(21, 0))
            ext_v = float(io.get(66, 0)) / 1000.0
            bat_v = float(io.get(67, 0)) / 1000.0
            rfid = str(io.get(78, '')) # iButton/RFID
            
            # Parse True Sensor-Derived Fuel (Teltonika CAN or Analog fuel sensors)
            # IO 84: CAN Fuel Level (%)
            # IO 85: CAN Fuel Consumed (Liters)
            # IO 9: Analog Input 1 (mV) - Calibrated to liters
            can_fuel_pct = float(io.get(84)) if io.get(84) is not None else None
            can_fuel_consumed = float(io.get(85)) if io.get(85) is not None else None
            analog_fuel_mv = float(io.get(9)) if io.get(9) is not None else None
            
            true_fuel = None
            if can_fuel_consumed is not None:
                true_fuel = can_fuel_consumed
            elif can_fuel_pct is not None:
                true_fuel = (can_fuel_pct / 100.0) * 60.0
            elif analog_fuel_mv is not None:
                true_fuel = (analog_fuel_mv / 10000.0) * 60.0
            
            # 3. RFID & Driver Mapping (Always done, even for historical packets)
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
                        "INSERT INTO rfid_events (imei, driver_id, rfid_tag, event_type, timestamp, latitude, longitude, ignition) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                        str(imei), driver_id, str(rfid), 'swipe', latest['timestamp'], 
                        latest['latitude'], latest['longitude'], ignition
                    )

                    # Manage Driver Session - Only if NOT through reconciliation engine
                    # (Reconciliation engine handles this internally)
                    try:
                        await self.sync_driver_session(conn, imei, driver_id, latest['timestamp'], ignition)
                    except Exception as e:
                        logger.warning(f"Driver session sync failed for {imei}: {e}")
                else:
                    # Log Unknown Tag Event
                    await conn.execute(
                        "INSERT INTO rfid_events (imei, rfid_tag, event_type, timestamp, latitude, longitude, ignition) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        str(imei), str(rfid), 'unknown_tag', latest['timestamp'],
                        latest['latitude'], latest['longitude'], ignition
                    )

            # 4. POSITION RECONCILIATION: Authoritative live position engine
            # This handles:
            # - Chronological validation
            # - Live status DB update
            # - Redis cache update
            # - Websocket emission
            # - Audit trail logging
            logger.debug(f"[RECONCILIATION_START] {imei}: telemetry_id={latest_telemetry_id}, timestamp={latest['timestamp'].isoformat()}")
            
            try:
                # Evaluate state only if reconciliation engine approves (not stale)
                # We do this BEFORE reconciliation to capture state asynchronously
                speed = latest.get('speed', 0)
                status = await self.hysteresis.evaluate_state(
                    imei=str(imei),
                    speed=speed,
                    ignition=ignition,
                    timestamp=latest['timestamp']
                )
                
                # Process analytics
                try:
                    await self.analytics.process_telemetry(imei, {
                        **latest,
                        "ignition": ignition,
                        "rfid": rfid,
                        "driver_id": driver_id,
                        "driver_name": driver_name,
                        "satellites": latest.get('satellites', 0)
                    }, conn=conn)
                except Exception as e:
                    logger.warning(f"Analytics processing failed for {imei}: {e}")
                
                # ATOMIC RECONCILIATION: This is where stale/live determination happens
                reconcile_result = await self.reconciliation_engine.reconcile_position(
                    imei=str(imei),
                    device_id=device_id,
                    telemetry_id=latest_telemetry_id,
                    timestamp=latest['timestamp'],
                    longitude=latest['longitude'],
                    latitude=latest['latitude'],
                    speed=speed,
                    ignition=ignition,
                    movement=movement,
                    conn=conn,
                    # Extra fields for Redis
                    gsm=gsm,
                    ext_v=ext_v,
                    bat_v=bat_v,
                    rfid=rfid,
                    driver_id=driver_id,
                    driver_name=driver_name or ("Unknown Tag" if rfid and rfid != '0' else "No Driver"),
                    status=status,
                    true_fuel=true_fuel
                )
                
                if reconcile_result['reconciled']:
                    logger.info(
                        f"[LIVE_UPDATED] {imei}: Position reconciled | "
                        f"t_id={latest_telemetry_id} ts={latest['timestamp'].isoformat()} "
                        f"ws={reconcile_result['websocket_notified']} "
                        f"redis={reconcile_result['redis_updated']} "
                        f"latency={reconcile_result['latency_ms']}ms"
                    )
                else:
                    logger.info(
                        f"[STALE_PRESERVED] {imei}: Historical packet preserved | "
                        f"reason={reconcile_result['reason']} "
                        f"previous_id={reconcile_result['previous_id']} "
                        f"latency={reconcile_result['latency_ms']}ms"
                    )
                
            except Exception as e:
                logger.error(f"[RECONCILIATION_ERROR] {imei}: Position reconciliation failed: {e}", exc_info=True)
                # Fail gracefully - still mark telemetry as processed
                # Live state update will be skipped for this packet
                
            logger.info(f"[BATCH_COMPLETE] Processed {len(records)} records for {imei}")



    async def save_analytics_event(self, imei, event_type, data, conn=None):
        """Helper for AnalyticsEngine to persist events."""
        if not self.pool: await self.connect()
        
        conn_context = None
        if conn is None:
            conn_context = self.pool.acquire()
            conn = await conn_context.__aenter__()
            
        try:
            await conn.execute(
                "INSERT INTO analytics_events (imei, event_type, timestamp, latitude, longitude, value) VALUES ($1, $2, $3, $4, $5, $6)",
                str(imei), event_type, data['timestamp'], data.get('latitude'), data.get('longitude'), data.get('speed')
            )
        finally:
            if conn_context is not None:
                await conn_context.__aexit__(None, None, None)

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

    async def mark_device_offline(self, imei):
        """Atomically marks a device as offline in database and Redis cache, resetting active states."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            # 1. Update Database
            await conn.execute(
                """UPDATE live_vehicle_status 
                   SET status = 'offline', 
                       current_status = 'offline',
                       speed = 0,
                       ignition = FALSE,
                       movement = FALSE,
                       last_update = NOW(),
                       packet_age_seconds = EXTRACT(EPOCH FROM (NOW() - last_timestamp)),
                       updated_at = NOW() 
                   WHERE imei = $1""",
                str(imei)
            )
            
            # 2. Update Redis status cache
            existing_cache = await self.cache.get_status(imei)
            if existing_cache:
                existing_cache['status'] = 'offline'
                existing_cache['speed'] = 0
                existing_cache['ignition'] = False
                existing_cache['movement'] = False
                await self.cache.update_status(imei, existing_cache)
            else:
                live_status = {
                    'imei': imei,
                    'status': 'offline',
                    'speed': 0,
                    'ignition': False,
                    'movement': False
                }
                await self.cache.update_status(imei, live_status)
                
            # 3. Reset motion hysteresis cache to prevent stale transitions
            key = f"motion_state:{imei}"
            try:
                state_dict = {
                    "state": "offline",
                    "pending_state": None,
                    "pending_since": None
                }
                await self.cache.client.setex(key, 604800, json.dumps(state_dict))
            except Exception as e:
                logger.warning(f"Failed to reset motion state for {imei}: {e}")
                
            logger.info(f"Successfully marked device {imei} as OFFLINE on physical TCP disconnect")
            await self.log_alert('INFO', 'Connection', f"Device {imei} physically disconnected TCP session", imei, conn=conn)

    async def reconcile_offline_devices(self, ignition_on_timeout=180, ignition_off_timeout=1800):
        """Finds devices that haven't sent data within dynamic timeouts and marks them offline."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            # Dynamic offline query:
            # - ignition = True (ON) timeout is ignition_on_timeout
            # - ignition = False (OFF) timeout is ignition_off_timeout (also used as default if NULL)
            query = """
                SELECT imei, last_timestamp, ignition
                FROM live_vehicle_status 
                WHERE status != 'offline' AND (
                    (ignition = TRUE AND updated_at < NOW() - INTERVAL '1 second' * $1)
                    OR
                    (COALESCE(ignition, FALSE) = FALSE AND updated_at < NOW() - INTERVAL '1 second' * $2)
                )
            """
            offline_devices = await conn.fetch(query, ignition_on_timeout, ignition_off_timeout)
            
            if not offline_devices:
                return 0
 
            count = 0
            for row in offline_devices:
                imei = row['imei']
                is_ign = row['ignition']
                timeout = ignition_on_timeout if is_ign else ignition_off_timeout
                
                # Update DB to offline, resetting active parameters
                await conn.execute(
                    """UPDATE live_vehicle_status 
                       SET status = 'offline', 
                           current_status = 'offline',
                           speed = 0,
                           ignition = FALSE,
                           movement = FALSE,
                           last_update = NOW(),
                           packet_age_seconds = EXTRACT(EPOCH FROM (NOW() - last_timestamp)),
                           updated_at = NOW() 
                       WHERE imei = $1""",
                    imei
                )
                
                # Update Redis cache
                existing_cache = await self.cache.get_status(imei)
                if existing_cache:
                    existing_cache['status'] = 'offline'
                    existing_cache['speed'] = 0
                    existing_cache['ignition'] = False
                    existing_cache['movement'] = False
                    await self.cache.update_status(imei, existing_cache)
                else:
                    live_status = {
                        'imei': imei,
                        'timestamp': row['last_timestamp'].isoformat() if row['last_timestamp'] else None,
                        'status': 'offline',
                        'speed': 0,
                        'ignition': False,
                        'movement': False
                    }
                    await self.cache.update_status(imei, live_status)
                
                # Reset motion hysteresis cache to prevent stale transitions
                key = f"motion_state:{imei}"
                try:
                    state_dict = {
                        "state": "offline",
                        "pending_state": None,
                        "pending_since": None
                    }
                    await self.cache.client.setex(key, 604800, json.dumps(state_dict))
                except Exception as e:
                    logger.warning(f"Failed to reset motion state for {imei} in offline reconciliation: {e}")
                
                count += 1
                logger.info(f"Marked device {imei} as OFFLINE (No data for > {timeout}s | Ignition: {is_ign})")
                await self.log_alert('WARNING', 'Connection', f"Device {imei} went offline (Timeout: {timeout}s | Ignition: {is_ign})", imei)
                
            return count

