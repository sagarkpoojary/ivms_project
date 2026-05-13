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
                WHERE imei = %s AND start_time >= %s AND end_time <= %s
                ORDER BY start_time ASC
            """, (str(imei), start_dt, end_dt))
            trips = cur.fetchall()
            return [dict(t) for t in trips]
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_analytics_events(imei, event_type, start_dt, end_dt):
        """Fetch overspeed, harsh driving, or idle events."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT * FROM analytics_events 
                WHERE imei = %s AND event_type = %s AND timestamp BETWEEN %s AND %s
                ORDER BY timestamp ASC
            """, (str(imei), event_type, start_dt, end_dt))
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
        """Generate summary metrics for a list of vehicles."""
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            results = []
            for v in vehicles:
                imei = str(v.get('unique_id'))
                
                # Fetch aggregates from trip_summary
                cur.execute("""
                    SELECT 
                        SUM(distance_km) as total_distance,
                        SUM(duration_sec) as total_duration,
                        MAX(max_speed) as max_speed,
                        AVG(avg_speed) as avg_speed,
                        SUM(fuel_consumed) as total_fuel
                    FROM trip_summary 
                    WHERE imei = %s AND start_time >= %s AND end_time <= %s
                """, (imei, start_dt, end_dt))
                summary = cur.fetchone()
                
                # Fetch idle time from analytics_events
                cur.execute("""
                    SELECT SUM(value) as total_idle_sec
                    FROM analytics_events
                    WHERE imei = %s AND event_type = 'idle' AND timestamp BETWEEN %s AND %s
                """, (imei, start_dt, end_dt))
                idle = cur.fetchone()
                
                results.append({
                    "name": v.get('name'),
                    "unique_id": imei,
                    "total_distance": round(summary['total_distance'] or 0, 2),
                    "total_duration": int(summary['total_duration'] or 0),
                    "max_speed": round(summary['max_speed'] or 0, 2),
                    "average_speed": round(summary['avg_speed'] or 0, 2),
                    "idle_duration": int((idle['total_idle_sec'] or 0) * 1000), # to ms
                    "fuel_liters": round(summary['total_fuel'] or 0, 2),
                    "status": "active"
                })
            return results
        finally:
            cur.close(); conn.close()

native_report_service = NativeReportService()
