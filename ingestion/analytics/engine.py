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
        self.IDLE_THRESHOLD = 300      # 5 minutes
        self.HARSH_ACCEL_THRESHOLD = 10 # km/h change per second
        self.HARSH_BRAKE_THRESHOLD = -15 # km/h change per second

    async def process_telemetry(self, imei, data):
        """Processes a new telemetry point for trips and analytics."""
        try:
            # 1. Fetch previous state from cache
            prev_state_raw = await self.cache.client.get(f"state:{imei}")
            prev_state = json.loads(prev_state_raw) if prev_state_raw else None
            
            # 2. Trip Detection
            await self._handle_trip_logic(imei, data, prev_state)
            
            # 3. Violation Detection (Overspeed, Harsh Behavior)
            await self._handle_violations(imei, data, prev_state)
            
            # 4. Update state in Redis
            await self.cache.client.set(f"state:{imei}", json.dumps({
                "last_timestamp": data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp'],
                "last_speed": data.get('speed', 0),
                "last_ignition": data.get('ignition', False),
                "overspeed_start": prev_state.get('overspeed_start') if prev_state else None
            }))
            
        except Exception as e:
            self.logger.error(f"Analytics engine error for {imei}: {e}")

    async def _handle_trip_logic(self, imei, data, prev_state):
        current_ign = data.get('ignition', False)
        prev_ign = prev_state.get('last_ignition', False) if prev_state else False
        
        # Trip Start: Ignition OFF -> ON
        if current_ign and not prev_ign:
            await self.db.save_analytics_event(imei, "trip_start", data)
            self.logger.info(f"Trip started for {imei}")
            
        # Trip End: Ignition ON -> OFF
        elif not current_ign and prev_ign:
            await self.db.save_analytics_event(imei, "trip_end", data)
            # Calculate summary (this could be async/deferred)
            await self._calculate_trip_summary(imei)
            self.logger.info(f"Trip ended for {imei}")

    async def _handle_violations(self, imei, data, prev_state):
        speed = data.get('speed', 0)
        
        # 1. Sustained Overspeed Detection
        if speed > self.OVERSPEED_THRESHOLD:
            if prev_state and not prev_state.get('overspeed_start'):
                # Start timing the overspeed
                prev_state['overspeed_start'] = data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp']
            elif prev_state and prev_state.get('overspeed_start'):
                # Check duration
                start_time = datetime.fromisoformat(prev_state['overspeed_start'])
                curr_time = data['timestamp'] if isinstance(data['timestamp'], datetime) else datetime.fromisoformat(data['timestamp'])
                duration = (curr_time - start_time).total_seconds()
                
                if duration >= self.OVERSPEED_DURATION:
                    await self.db.save_analytics_event(imei, "overspeed", {
                        **data,
                        "details": f"Speed {speed} km/h for {int(duration)}s"
                    })
                    # Reset start time so we don't spam every packet
                    prev_state['overspeed_start'] = None 
        else:
            if prev_state:
                prev_state['overspeed_start'] = None

        # 2. Harsh Behavior (Accel/Braking)
        if prev_state:
            prev_speed = prev_state.get('last_speed', 0)
            dv = speed - prev_speed
            # Note: This assumes ~1s interval between packets. 
            # In production, we'd divide by (t - t_prev)
            if dv > self.HARSH_ACCEL_THRESHOLD:
                await self.db.save_analytics_event(imei, "harsh_accel", data)
            elif dv < self.HARSH_BRAKE_THRESHOLD:
                await self.db.save_analytics_event(imei, "harsh_brake", data)

    async def _calculate_trip_summary(self, imei):
        """Aggregates the last completed trip metrics."""
        # Find the last trip_start and trip_end
        async with self.db.pool.acquire() as conn:
            # Simple logic: get last two events for this imei
            events = await conn.fetch(
                "SELECT * FROM analytics_events WHERE imei = $1 ORDER BY timestamp DESC LIMIT 2",
                imei
            )
            if len(events) == 2 and events[0]['event_type'] == 'trip_end' and events[1]['event_type'] == 'trip_start':
                start_t = events[1]['timestamp']
                end_t = events[0]['timestamp']
                
                # Aggregate metrics from telemetry
                stats = await conn.fetchrow(
                    """SELECT 
                        MAX(speed) as max_speed, 
                        AVG(speed) as avg_speed,
                        COUNT(*) as point_count
                       FROM telemetry 
                       WHERE imei = $1 AND timestamp BETWEEN $2 AND $3""",
                    imei, start_t, end_t
                )
                
                # Mock distance for now (would use geospatial sum in prod)
                duration = (end_t - start_t).total_seconds() / 60 # minutes
                
                await conn.execute(
                    """INSERT INTO trip_summary (imei, start_time, end_time, duration_min, max_speed, avg_speed)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    imei, start_t, end_t, duration, stats['max_speed'] or 0, stats['avg_speed'] or 0
                )

