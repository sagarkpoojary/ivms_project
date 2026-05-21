import psycopg2
import psycopg2.extras
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from config import Config
from models.database import get_conn

# Match ingestion/analytics/engine.py GPS jump filter (km between consecutive fixes)
_GPS_SEGMENT_MAX_KM = 5.0


def _haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in km; 0 if coordinates missing."""
    if lon1 is None or lat1 is None or lon2 is None or lat2 is None:
        return 0.0
    try:
        lon1, lat1, lon2, lat2 = map(
            radians,
            [float(lon1), float(lat1), float(lon2), float(lat2)],
        )
    except (TypeError, ValueError):
        return 0.0
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * asin(sqrt(min(1.0, a))) * 6371


class NativeReportService:
    @staticmethod
    def get_trip_report(imei, start_dt, end_dt):
        """Fetch trips from trip_summary table."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT * FROM trip_summary 
                WHERE imei = %s AND start_time BETWEEN %s AND %s
                ORDER BY start_time ASC
            """, (str(imei), start_dt, end_dt))
            trips = cur.fetchall()
            return [dict(t) for t in trips]
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_analytics_events(imei, event_type, start_dt, end_dt, allowed_imeis: list = None):
        """Fetch overspeed, harsh driving, or idle events, filtered by tenant."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            sql = "SELECT * FROM analytics_events WHERE timestamp BETWEEN %s AND %s"
            params = [start_dt, end_dt]
            
            if imei:
                sql += " AND imei = %s"
                params.append(str(imei))
            elif allowed_imeis is not None:
                sql += " AND imei = ANY(%s)"
                params.append(allowed_imeis)
                
            if event_type != 'all':
                sql += " AND event_type = %s"
                params.append(event_type)
            
            sql += " ORDER BY timestamp DESC LIMIT 200"
            cur.execute(sql, tuple(params))
            events = cur.fetchall()
            return [dict(e) for e in events]
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_playback_data(imei, start_dt, end_dt, limit=1000):
        """Fetch raw telemetry for map playback."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Simple downsampling
            cur.execute("SELECT COUNT(*) FROM telemetry WHERE imei = %s AND timestamp BETWEEN %s AND %s", (str(imei), start_dt, end_dt))
            row = cur.fetchone()
            count = row['count'] if row else 0
            
            step = max(1, count // limit)
            
            cur.execute("""
                SELECT * FROM (
                    SELECT *, row_number() OVER (ORDER BY timestamp) as rn
                    FROM telemetry 
                    WHERE imei = %s AND timestamp BETWEEN %s AND %s
                ) t
                WHERE rn %% %s = 0
                ORDER BY timestamp ASC
            """, (str(imei), start_dt, end_dt, step))
            
            records = cur.fetchall()
            return [dict(r) for r in records]
        finally:
            cur.close(); conn.close()

    @staticmethod
    def _telemetry_stats_for_period(imeis, start_dt, end_dt, cur):
        """
        Distance / speeds / moving time from raw telemetry in [start_dt, end_dt].

        trip_summary is only written when ignition turns OFF, so open trips and
        same-day driving otherwise miss from completed-trip rollups alone.
        """
        if not imeis:
            return {}
        cur.execute(
            """
            SELECT imei, timestamp, longitude, latitude, speed
            FROM telemetry
            WHERE imei = ANY(%s) AND timestamp BETWEEN %s AND %s
            ORDER BY imei ASC, timestamp ASC
            """,
            (imeis, start_dt, end_dt),
        )
        rows = cur.fetchall()
        by_imei = defaultdict(list)
        for r in rows:
            by_imei[str(r["imei"])].append(r)

        speed_thr = float(Config.SPEED_THRESHOLD_KMH)
        out = {}
        for imei, pts in by_imei.items():
            if not pts:
                continue
            if len(pts) == 1:
                sp = float(pts[0].get("speed") or 0)
                out[imei] = {
                    "total_distance": 0.0,
                    "max_speed": sp,
                    "avg_speed": sp,
                    "moving_sec": 0,
                }
                continue

            total_dist = 0.0
            max_spd = 0.0
            speed_samples = []
            moving_sec = 0

            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                sp1 = float(p1.get("speed") or 0)
                sp2 = float(p2.get("speed") or 0)
                max_spd = max(max_spd, sp1, sp2)
                if sp1 > 0:
                    speed_samples.append(sp1)

                seg_km = _haversine_km(
                    p1.get("longitude"),
                    p1.get("latitude"),
                    p2.get("longitude"),
                    p2.get("latitude"),
                )
                if 0 < seg_km < _GPS_SEGMENT_MAX_KM:
                    total_dist += seg_km

                dt = (p2["timestamp"] - p1["timestamp"]).total_seconds()
                if not (0 < dt <= 7200):
                    continue
                # Moving: GNSS displacement (~20 m+) or speed above threshold (slow traffic)
                if seg_km >= 0.02 or sp1 > speed_thr:
                    moving_sec += int(dt)

            sp_last = float(pts[-1].get("speed") or 0)
            max_spd = max(max_spd, sp_last)
            if sp_last > 0:
                speed_samples.append(sp_last)

            avg_spd = (
                sum(speed_samples) / len(speed_samples) if speed_samples else 0.0
            )
            out[imei] = {
                "total_distance": round(total_dist, 2),
                "max_speed": round(max_spd, 2),
                "avg_speed": round(avg_spd, 2),
                "moving_sec": moving_sec,
            }
        return out

    @staticmethod
    def get_fleet_summary(vehicles, start_dt, end_dt):
        """Generate summary metrics for a list of vehicles in a single query (Phase 10)."""
        if not vehicles: return []
        
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            imeis = [str(v.get('unique_id')) for v in vehicles]
            
            # Completed trips (ignition-off); used as fallback when telemetry is empty
            cur.execute("""
                SELECT 
                    imei,
                    SUM(distance_km) as total_distance,
                    SUM(duration_sec) as total_duration,
                    MAX(max_speed) as max_speed,
                    AVG(avg_speed) as avg_speed,
                    SUM(fuel_consumed) as total_fuel
                FROM trip_summary 
                WHERE imei = ANY(%s) AND start_time BETWEEN %s AND %s
                GROUP BY imei
            """, (imeis, start_dt, end_dt))
            trip_stats = {str(r['imei']): r for r in cur.fetchall()}

            tele_stats = NativeReportService._telemetry_stats_for_period(
                imeis, start_dt, end_dt, cur
            )
            
            # Single query for idle time
            cur.execute("""
                SELECT imei, SUM(value) as total_idle_sec
                FROM analytics_events
                WHERE imei = ANY(%s) AND event_type = 'idle' AND timestamp BETWEEN %s AND %s
                GROUP BY imei
            """, (imeis, start_dt, end_dt))
            idle_stats = {str(r['imei']): r['total_idle_sec'] for r in cur.fetchall()}
            
            total_period_sec = (end_dt - start_dt).total_seconds()
            
            results = []
            for v in vehicles:
                imei = str(v.get('unique_id'))
                s = trip_stats.get(imei, {})
                t = tele_stats.get(imei, {})

                trip_dist = round(float(s.get("total_distance") or 0), 2)
                tele_dist = float(t.get("total_distance") or 0)
                # Telemetry reflects all fixes in the window (in-progress trips). trip_summary
                # only exists after ignition OFF. Use the larger of the two to limit under-count.
                total_dist = round(max(tele_dist, trip_dist), 2)

                if tele_dist >= trip_dist:
                    max_spd = float(t.get("max_speed") or 0)
                    avg_spd = float(t.get("avg_speed") or 0)
                else:
                    max_spd = float(s.get("max_speed") or 0)
                    avg_spd = float(s.get("avg_speed") or 0)

                total_fuel = round((s.get('total_fuel') or 0), 2)
                idle_sec = int(idle_stats.get(imei) or 0)
                moving_sec = int(t.get("moving_sec") or 0)
                trip_dur = int(s.get("total_duration") or 0)
                if tele_dist >= trip_dist:
                    if moving_sec == 0:
                        moving_sec = trip_dur
                else:
                    moving_sec = trip_dur
                
                # Off duration is time neither moving nor idling
                off_sec = max(0, total_period_sec - moving_sec - idle_sec)
                
                # Simple insight logic
                status = "Active"
                insight = "Normal operations"
                
                if total_dist == 0:
                    status = "No Movement"
                    insight = "No distance recorded in this period"
                elif total_dist < 5:
                    status = "Low Usage"
                    insight = "Very low activity detected"
                
                if max_spd > 100: # Example threshold
                    status = "Possible Overspeed"
                    insight = f"High speed of {max_spd} km/h detected"

                results.append({
                    "name": v.get('name'),
                    "unique_id": imei,
                    "company_name": v.get('company_name'),
                    "total_distance": round(float(total_dist), 2),
                    "total_duration": moving_sec,
                    "max_speed": round(float(max_spd), 2),
                    "average_speed": round(float(avg_spd), 2),
                    "idle_duration": idle_sec * 1000, # to ms for template
                    "off_duration": off_sec * 1000, # to ms for template
                    "fuel_liters": total_fuel,
                    "fuel_cost": round(total_fuel * Config.FUEL_PRICE_OMR, 3),
                    "engine_hours": round((moving_sec + idle_sec) / 3600.0, 2),
                    "status": status,
                    "insight": insight
                })
            return results
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_driver_attendance(start_dt, end_dt, allowed_imeis: list = None):
        """Fetch driver login/logout sessions, filtered by tenant."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            sql = """
                SELECT s.*, d.name as driver_name, d.rfid_tag, v.name as vehicle_name
                FROM driver_sessions s
                JOIN drivers d ON s.driver_id = d.driver_id
                LEFT JOIN vehicles v ON s.imei = v.unique_id
                WHERE s.login_time BETWEEN %s AND %s
            """
            params = [start_dt, end_dt]
            if allowed_imeis is not None:
                sql += " AND s.imei = ANY(%s)"
                params.append(allowed_imeis)
            
            sql += " ORDER BY s.login_time DESC"
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_rfid_timeline(imei, start_dt, end_dt, allowed_imeis: list = None):
        """Fetch all RFID events for a vehicle, or fleet-wide filtered by tenant."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            sql = """
                SELECT e.*, d.name as driver_name
                FROM rfid_events e
                LEFT JOIN drivers d ON e.driver_id = d.driver_id
                WHERE e.timestamp BETWEEN %s AND %s
            """
            params = [start_dt, end_dt]
            
            if imei:
                sql += " AND e.imei = %s"
                params.append(str(imei))
            elif allowed_imeis is not None:
                sql += " AND e.imei = ANY(%s)"
                params.append(allowed_imeis)
                
            sql += " ORDER BY e.timestamp DESC LIMIT 200"
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close(); conn.close()

native_report_service = NativeReportService()
