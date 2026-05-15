import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from config import Config
from models.database import get_conn
from services.time_service import get_oman_now, SYSTEM_TZ
import pytz

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
    def get_fleet_summary(vehicles, start_dt, end_dt):
        """Generate summary metrics for a list of vehicles in a single query (Phase 10)."""
        if not vehicles: return []
        
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            imeis = [str(v.get('unique_id')) for v in vehicles]
            
            # Single query for trips
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
            trip_stats = {r['imei']: r for r in cur.fetchall()}
            
            # Single query for idle time
            cur.execute("""
                SELECT imei, SUM(value) as total_idle_sec
                FROM analytics_events
                WHERE imei = ANY(%s) AND event_type = 'idle' AND timestamp BETWEEN %s AND %s
                GROUP BY imei
            """, (imeis, start_dt, end_dt))
            idle_stats = {r['imei']: r['total_idle_sec'] for r in cur.fetchall()}
            
            total_period_sec = (end_dt - start_dt).total_seconds()
            
            results = []
            for v in vehicles:
                imei = str(v.get('unique_id'))
                s = trip_stats.get(imei, {})
                
                total_dist = round((s.get('total_distance') or 0), 2)
                max_spd = round((s.get('max_speed') or 0), 2)
                avg_spd = round((s.get('avg_speed') or 0), 2)
                total_fuel = round((s.get('total_fuel') or 0), 2)
                idle_sec = int(idle_stats.get(imei) or 0)
                moving_sec = int(s.get('total_duration') or 0)
                
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
                    "total_distance": total_dist,
                    "total_duration": moving_sec,
                    "max_speed": max_spd,
                    "average_speed": avg_spd,
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
