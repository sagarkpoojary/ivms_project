import psycopg2
import psycopg2.extras
from datetime import datetime, time
from models.database import get_conn
from config import Config

class AnalyticsService:
    @staticmethod
    def get_fleet_efficiency(vehicles, start_dt, end_dt):
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            imeis = [str(v.get('unique_id')) for v in vehicles if v.get('unique_id')]
            if not imeis:
                return {"total_distance": 0, "active_trips": 0, "idle_duration": 0, "fuel_consumed": 0, "efficiency_score": 0}

            cur.execute("""
                SELECT 
                    SUM(distance_km) as total_distance,
                    COUNT(id) as active_trips,
                    SUM(idle_duration_sec) as idle_duration,
                    SUM(fuel_consumed) as fuel_consumed,
                    SUM(duration_sec) as total_duration
                FROM trip_summary 
                WHERE imei = ANY(%s) AND start_time BETWEEN %s AND %s
            """, (imeis, start_dt, end_dt))
            summary = cur.fetchone()
            
            total_dist = float(summary['total_distance'] or 0)
            active_trips = int(summary['active_trips'] or 0)
            idle_dur = int(summary['idle_duration'] or 0)
            total_dur = int(summary['total_duration'] or 0)
            
            # Fuel Analytics (Phase 2)
            # If fuel_consumed is missing or 0, estimate it
            fuel = float(summary['fuel_consumed'] or 0)
            if fuel == 0 and total_dist > 0:
                # Estimate: (distance / mileage) + (idle_hours * idle_lph)
                est_drive_fuel = total_dist / Config.MILEAGE_KM_PER_LITER
                est_idle_fuel = (idle_dur / 3600.0) * Config.IDLE_FUEL_LPH
                fuel = est_drive_fuel + est_idle_fuel
            
            # Utilization % (Total duration / available hours in range)
            # Production Fix (Phase 3): For "Today", use elapsed hours, not full 24h
            now = datetime.now()
            effective_end = min(end_dt, now)
            range_hours = (effective_end - start_dt).total_seconds() / 3600.0
            range_hours = max(0.1, range_hours) # Avoid division by zero
            
            available_hours = range_hours * len(imeis)
            utilization = (total_dur / 3600.0 / available_hours * 100) if available_hours > 0 else 0
            
            # Revenue per KM (Assume 0.5 OMR per KM for fleet business model)
            revenue_per_km = 0.5 
            total_revenue = total_dist * revenue_per_km
            
            # Fleet Health Score
            # Penalize idle time and low utilization
            idle_ratio = (idle_dur / total_dur) if total_dur > 0 else 0
            score = 100 - (idle_ratio * 100) - (max(0, 15 - utilization))
            score = max(0, min(100, score))

            return {
                "total_distance": round(total_dist, 2),
                "active_trips": active_trips,
                "idle_duration_hours": round(idle_dur / 3600, 2),
                "fuel_consumed_liters": round(fuel, 2),
                "fuel_cost": round(fuel * Config.FUEL_PRICE_OMR, 2),
                "total_revenue": round(total_revenue, 2),
                "revenue_per_km": revenue_per_km,
                "utilization": round(utilization, 1),
                "efficiency_score": round(score, 1)
            }
        finally:
            cur.close(); conn.close()

    @staticmethod
    def get_driver_profiles(start_dt, end_dt, allowed_imeis=None):
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Fetch drivers with base stats
            sql = """
                SELECT 
                    d.driver_id, d.name, d.rfid_tag,
                    COUNT(t.id) as trip_count,
                    SUM(t.distance_km) as total_distance,
                    SUM(t.fuel_consumed) as fuel_consumed,
                    SUM(t.idle_duration_sec) as idle_duration,
                    SUM(CASE WHEN EXTRACT(HOUR FROM t.start_time AT TIME ZONE 'Asia/Muscat') < 5 OR EXTRACT(HOUR FROM t.start_time AT TIME ZONE 'Asia/Muscat') > 22 THEN 1 ELSE 0 END) as after_hours_trips,
                    SUM(CASE WHEN t.duration_sec > 14400 THEN 1 ELSE 0 END) as fatigue_trips
                FROM drivers d
                LEFT JOIN trip_summary t ON d.driver_id = t.driver_id AND t.start_time BETWEEN %s AND %s
            """
            params = [start_dt, end_dt]
            if allowed_imeis:
                sql += " AND t.imei = ANY(%s)"
                params.append(allowed_imeis)
                
            sql += " GROUP BY d.driver_id, d.name, d.rfid_tag"
            cur.execute(sql, tuple(params))
            drivers = cur.fetchall()

            # Fetch events
            sql_events = """
                SELECT driver_id, event_type, COUNT(*) as count
                FROM rfid_events 
                WHERE timestamp BETWEEN %s AND %s AND event_type IN ('overspeed', 'harsh_braking', 'harsh_acceleration')
            """
            params_events = [start_dt, end_dt]
            if allowed_imeis:
                sql_events += " AND imei = ANY(%s)"
                params_events.append(allowed_imeis)
            sql_events += " GROUP BY driver_id, event_type"
            cur.execute(sql_events, tuple(params_events))
            events = cur.fetchall()

            event_map = {}
            for e in events:
                did = e['driver_id']
                if did not in event_map:
                    event_map[did] = {'overspeed': 0, 'harsh_braking': 0, 'harsh_acceleration': 0}
                event_map[did][e['event_type']] = e['count']

            results = []
            for d in drivers:
                did = d['driver_id']
                em = event_map.get(did, {'overspeed': 0, 'harsh_braking': 0, 'harsh_acceleration': 0})
                
                # Refined Driver Score (Phase 4)
                score = 100
                score -= em['overspeed'] * 4
                score -= em['harsh_braking'] * 5
                score -= em['harsh_acceleration'] * 5
                score -= int(d['after_hours_trips'] or 0) * 10 # Phase 4 requirement
                score -= int(d['fatigue_trips'] or 0) * 15 # Fatigue penalty (trips > 4h)
                
                dist = float(d['total_distance'] or 0)
                fuel = float(d['fuel_consumed'] or 0)
                if fuel == 0 and dist > 0:
                    fuel = dist / Config.MILEAGE_KM_PER_LITER
                
                idle_hrs = float(d['idle_duration'] or 0) / 3600.0
                score -= min(15, idle_hrs * 3) # 3 pts per hour idle
                
                score = max(0, min(100, score))
                
                results.append({
                    "driver_id": did,
                    "name": d['name'] or 'Unknown Driver',
                    "rfid_tag": d['rfid_tag'] or 'N/A',
                    "trip_count": d['trip_count'] or 0,
                    "total_distance": round(dist, 2),
                    "fuel_consumed": round(fuel, 2),
                    "idle_duration_hours": round(idle_hrs, 2),
                    "overspeed_count": em['overspeed'],
                    "harsh_braking": em['harsh_braking'],
                    "harsh_acceleration": em['harsh_acceleration'],
                    "after_hours_usage": int(d['after_hours_trips'] or 0),
                    "score": round(score, 1)
                })
            
            return sorted(results, key=lambda x: x['score'], reverse=True)
        finally:
            cur.close(); conn.close()

analytics_service = AnalyticsService()
