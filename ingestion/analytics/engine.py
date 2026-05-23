import logging
from datetime import datetime, timedelta
import json

class AnalyticsEngine:
    def __init__(self, db_handler, cache):
        self.db = db_handler
        self.cache = cache
        self.logger = logging.getLogger(__name__)
        
        # Configuration thresholds
        self.OVERSPEED_THRESHOLD = 80  # km/h
        self.OVERSPEED_DURATION = 10   # seconds sustained
        self.IDLE_THRESHOLD_SEC = 300      # 5 minutes
        self.HARSH_ACCEL_THRESHOLD = 10 # km/h change per second
        self.HARSH_BRAKE_THRESHOLD = -15 # km/h change per second
        self.DISTANCE_THRESHOLD_KM = 0.05 # 50 meters

    async def process_telemetry(self, imei, data, conn=None):
        """Processes a new telemetry point for trips and analytics."""
        try:
            # 1. Fetch previous state from cache
            prev_state_raw = await self.cache.client.get(f"state:{imei}")
            prev_state = json.loads(prev_state_raw) if prev_state_raw else {}
            
            # 2. Trip Detection
            await self._handle_trip_logic(imei, data, prev_state, conn=conn)
            
            # 3. Violation Detection (Overspeed, Harsh Behavior)
            await self._handle_violations(imei, data, prev_state, conn=conn)
            
            # --- PHASE 5: Trust Hardening (Confidence Scoring) ---
            confidence = self._calculate_confidence(data)
            data['confidence'] = confidence
            # ----------------------------------------------------

            # 4. Update state in Redis
            await self.cache.client.set(f"state:{imei}", json.dumps({
                "last_timestamp": data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp'],
                "last_speed": data.get('speed', 0),
                "last_ignition": data.get('ignition', False),
                "last_lat": data.get('latitude'),
                "last_lng": data.get('longitude'),
                "current_driver_id": data.get('driver_id') or prev_state.get('current_driver_id'),
                "overspeed_start": prev_state.get('overspeed_start'),
                "idle_start": prev_state.get('idle_start'),
                "confidence": confidence
            }))
            
        except Exception as e:
            self.logger.error(f"Analytics engine error for {imei}: {e}")

    async def _handle_trip_logic(self, imei, data, prev_state, conn=None):
        current_ign = data.get('ignition', False)
        prev_ign = prev_state.get('last_ignition', False)
        speed = data.get('speed', 0)
        driver_id = data.get('driver_id') or prev_state.get('current_driver_id')
        
        # 1. Trip Start/End Logic
        if current_ign and not prev_ign:
            await self.db.save_analytics_event(imei, "trip_start", {**data, "driver_id": driver_id}, conn=conn)
            await self.db.save_system_event(imei, 'INFO', 'Movement', 'Ignition ON', "Vehicle engine started.", driver_id=driver_id, latitude=data.get('latitude'), longitude=data.get('longitude'), conn=conn)
            self.logger.info(f"Trip started for {imei} | Driver: {driver_id}")
            
        elif not current_ign and prev_ign:
            await self.db.save_analytics_event(imei, "trip_end", {**data, "driver_id": driver_id}, conn=conn)
            await self.db.save_system_event(imei, 'INFO', 'Movement', 'Ignition OFF', "Vehicle engine stopped.", driver_id=driver_id, latitude=data.get('latitude'), longitude=data.get('longitude'), conn=conn)
            await self._calculate_trip_summary(imei, driver_id, conn=conn)
            self.logger.info(f"Trip ended for {imei}")
 
        # 2. Idle Detection (Phase 5)
        # Condition: Ignition ON AND Speed <= 1
        if current_ign and speed <= 1:
            if not prev_state.get('idle_start'):
                prev_state['idle_start'] = data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp']
            else:
                idle_start = datetime.fromisoformat(prev_state['idle_start'])
                curr_time = data['timestamp'] if isinstance(data['timestamp'], datetime) else datetime.fromisoformat(data['timestamp'])
                duration = (curr_time - idle_start).total_seconds()
                
                if duration >= self.IDLE_THRESHOLD_SEC:
                    # Log/Update idle event
                    await self.db.save_analytics_event(imei, "idle", {
                        **data,
                        "driver_id": driver_id,
                        "value": duration # Store duration in seconds
                    }, conn=conn)
                    # Reset so we only log once per threshold or implement a "heartbeat" for long idle
                    # For now, let's just update the state to prevent spamming
                    # We will log the final idle duration on move or ign off
                    # For now, let's just update the state to prevent spamming
        else:
            # Vehicle moved or engine turned off - close idle state
            if prev_state.get('idle_start'):
                idle_start = datetime.fromisoformat(prev_state['idle_start'])
                curr_time = data['timestamp'] if isinstance(data['timestamp'], datetime) else datetime.fromisoformat(data['timestamp'])
                total_idle = (curr_time - idle_start).total_seconds()
                if total_idle > 60: # Log if > 1 minute
                     await self.db.save_analytics_event(imei, "idle_summary", {**data, "value": total_idle}, conn=conn)
                prev_state['idle_start'] = None
 
    async def _handle_violations(self, imei, data, prev_state, conn=None):
        speed = data.get('speed', 0)
        driver_id = data.get('driver_id') or prev_state.get('current_driver_id')
        
        # 1. Sustained Overspeed Detection
        if speed > self.OVERSPEED_THRESHOLD:
            if not prev_state.get('overspeed_start'):
                # Start timing the overspeed
                prev_state['overspeed_start'] = data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp']
            else:
                # Check duration
                start_time = datetime.fromisoformat(prev_state['overspeed_start'])
                curr_time = data['timestamp'] if isinstance(data['timestamp'], datetime) else datetime.fromisoformat(data['timestamp'])
                duration = (curr_time - start_time).total_seconds()
                
                if duration >= self.OVERSPEED_DURATION:
                    await self.db.save_analytics_event(imei, "overspeed", {
                        **data,
                        "driver_id": driver_id,
                        "details": f"Speed {speed} km/h for {int(duration)}s"
                    }, conn=conn)
                    await self.db.save_system_event(imei, 'WARNING', 'Safety', 'Overspeed', f"Vehicle exceeded {self.OVERSPEED_THRESHOLD} km/h for {int(duration)}s.", driver_id=driver_id, latitude=data.get('latitude'), longitude=data.get('longitude'), raw_payload={"speed": speed, "duration": duration}, conn=conn)
                    # Reset start time so we don't spam every packet
                    prev_state['overspeed_start'] = None 
        else:
            prev_state['overspeed_start'] = None
  
        # 2. Harsh Behavior (Accel/Braking)
        if prev_state:
            prev_speed = prev_state.get('last_speed', 0)
            dv = speed - prev_speed
            if dv > self.HARSH_ACCEL_THRESHOLD:
                await self.db.save_analytics_event(imei, "harsh_accel", {**data, "driver_id": driver_id}, conn=conn)
                await self.db.save_system_event(imei, 'WARNING', 'Safety', 'Harsh Acceleration', f"Sudden acceleration detected: {round(dv, 1)} km/h change.", driver_id=driver_id, latitude=data.get('latitude'), longitude=data.get('longitude'), conn=conn)
            elif dv < self.HARSH_BRAKE_THRESHOLD:
                await self.db.save_analytics_event(imei, "harsh_brake", {**data, "driver_id": driver_id}, conn=conn)
                await self.db.save_system_event(imei, 'WARNING', 'Safety', 'Harsh Braking', f"Sudden braking detected: {round(dv, 1)} km/h change.", driver_id=driver_id, latitude=data.get('latitude'), longitude=data.get('longitude'), conn=conn)
 
    async def _calculate_trip_summary(self, imei, driver_id=None, conn=None):
        """Aggregates the last completed trip metrics."""
        conn_context = None
        if conn is None:
            conn_context = self.db.pool.acquire()
            conn = await conn_context.__aenter__()
            
        try:
            events = await conn.fetch(
                "SELECT * FROM analytics_events WHERE imei = $1 AND event_type IN ('trip_start', 'trip_end') ORDER BY timestamp DESC LIMIT 2",
                imei
            )
            if len(events) == 2 and events[0]['event_type'] == 'trip_end' and events[1]['event_type'] == 'trip_start':
                start_t = events[1]['timestamp']
                end_t = events[0]['timestamp']
                
                # Production Grade Distance Calculation (Phase 11)
                # We use the native Postgres ST_Distance if available, or a manual sum
                # Here we calculate from telemetry points for accuracy
                telemetry = await conn.fetch(
                    "SELECT latitude, longitude, speed FROM telemetry WHERE imei = $1 AND timestamp BETWEEN $2 AND $3 ORDER BY timestamp ASC",
                    imei, start_t, end_t
                )
                
                total_dist = 0.0
                max_speed = 0.0
                avg_speed = 0.0
                if telemetry:
                    from math import radians, cos, sin, asin, sqrt
                    def haversine(lon1, lat1, lon2, lat2):
                        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                        dlon = lon2 - lon1; dlat = lat2 - lat1
                        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                        return 2 * asin(sqrt(a)) * 6371
                    
                    speeds = []
                    for i in range(len(telemetry)-1):
                        p1 = telemetry[i]; p2 = telemetry[i+1]
                        dist = haversine(p1['longitude'], p1['latitude'], p2['longitude'], p2['latitude'])
                        if dist < 5: # Filter out GPS jumps > 5km between points
                            total_dist += dist
                        speeds.append(p1['speed'])
                        max_speed = max(max_speed, p1['speed'])
                    
                    if speeds: avg_speed = sum(speeds) / len(speeds)
 
                duration = (end_t - start_t).total_seconds()
                if duration < 30: return # Ignore ghost trips < 30s
 
                # Query idle duration from analytics_events for this trip window
                idle_sec_row = await conn.fetchrow(
                    "SELECT SUM(value) as idle_sec FROM analytics_events WHERE imei = $1 AND event_type = 'idle' AND timestamp BETWEEN $2 AND $3",
                    imei, start_t, end_t
                )
                idle_sec = int(idle_sec_row['idle_sec'] or 0)
                
                # Check for true sensor-derived fuel consumption in the telemetry records (Teltonika CAN I/O 85)
                # Or compile using Analog calibration
                true_fuel_row = await conn.fetchrow(
                    "SELECT MAX((io_elements->>'85')::double precision) as can_consumed, MAX((io_elements->>'9')::double precision) as analog_val "
                    "FROM telemetry WHERE imei = $1 AND timestamp BETWEEN $2 AND $3",
                    imei, start_t, end_t
                )
                
                true_fuel = None
                if true_fuel_row:
                    if true_fuel_row['can_consumed'] is not None:
                        true_fuel = float(true_fuel_row['can_consumed'])
                    elif true_fuel_row['analog_val'] is not None:
                        # 0-10000 mV maps to 0-60L tank
                        true_fuel = (float(true_fuel_row['analog_val']) / 10000.0) * 60.0
                
                if true_fuel is None:
                    # Calculate estimated fuel consumed: (distance / mileage) + (idle_hours * idle_burn_rate)
                    from config import Config
                    trip_fuel = (total_dist / Config.MILEAGE_KM_PER_LITER) + ((idle_sec / 3600.0) * Config.IDLE_FUEL_LPH)
                else:
                    trip_fuel = true_fuel
                
                trip_fuel = round(trip_fuel, 2)

                await conn.execute(
                    """INSERT INTO trip_summary (imei, driver_id, start_time, end_time, duration_sec, max_speed, avg_speed, distance_km, idle_duration_sec, fuel_consumed)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    imei, driver_id, start_t, end_t, int(duration), max_speed, avg_speed, round(total_dist, 2), idle_sec, trip_fuel
                )
        finally:
            if conn_context is not None:
                await conn_context.__aexit__(None, None, None)

    def _calculate_confidence(self, data):
        """
        Enterprise Confidence Scoring (0.0 to 1.0)
        Based on satellite count and signal quality.
        """
        sats = data.get('satellites', 0)
        if sats >= 8: return 1.0
        if sats >= 4: return 0.7
        if sats > 0: return 0.4
        return 0.1
