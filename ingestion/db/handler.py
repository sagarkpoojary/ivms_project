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

    async def save_telemetry(self, imei, records):
        if not self.pool:
            await self.connect()
            
        async with self.pool.acquire() as conn:
            # 1. Verify if device is registered in the IVMS vehicles table
            vehicle = await conn.fetchrow(
                "SELECT unique_id, status, name FROM vehicles WHERE unique_id = $1",
                str(imei)
            )
            
            # If not found, we still save telemetry to the 'telemetry' table for audit, 
            # but we can flag it or auto-create a 'devices' entry if needed.
            # For this requirement, we ensure a 'devices' entry exists to satisfy FKs.
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
            
            # 4. Trip & Analytics Logic
            # Process the latest record through the analytics engine
            await self.analytics.process_telemetry(imei, {
                **latest,
                "ignition": ignition,
                "rfid": rfid
            })

            status = "moving" if latest['speed'] > 0 else ("online" if ignition else "idle")

            await conn.execute(
                """INSERT INTO live_vehicle_status (imei, device_id, last_timestamp, longitude, latitude, speed, ignition, movement, gsm_signal, external_voltage, battery_voltage, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                   updated_at = NOW()""",
                str(imei), device_id, latest['timestamp'], latest['longitude'], latest['latitude'], 
                latest['speed'], ignition, movement, gsm, ext_v, bat_v, status
            )
            
            # 5. Update Redis Cache (Detailed for Dashboard)
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
                'is_registered': vehicle is not None,
                'vehicle_name': vehicle['vehicle_name'] if vehicle and 'vehicle_name' in vehicle else (vehicle['name'] if vehicle and 'name' in vehicle else "Unassigned Device")
            }
            await self.cache.update_status(str(imei), live_status)
            
            logger.info(f"Processed {len(records)} records for {imei} | Trip: {ignition}")


    async def save_analytics_event(self, imei, event_type, data):
        """Helper for AnalyticsEngine to persist events."""
        if not self.pool: await self.connect()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO analytics_events (imei, event_type, timestamp, latitude, longitude, value) VALUES ($1, $2, $3, $4, $5, $6)",
                str(imei), event_type, data['timestamp'], data.get('latitude'), data.get('longitude'), data.get('speed')
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
                    'status': row['status']
                }
                await self.cache.update_status(row['imei'], status)
                count += 1
            return count
