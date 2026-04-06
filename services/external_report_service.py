import pytz
from datetime import datetime, timedelta
from services.traccar_service import try_traccar_get
from services.time_service import OMAN_TZ, parse_traccar_to_oman_str

from flask import current_app

def get_vehicle_summary_report(vehicle_uid, from_date_str, to_date_str):

    """
    Calculates daily vehicle summary for a given vehicle and date range.
    
    Args:
        vehicle_uid (str): The unique ID of the vehicle (IMEI/Serial).
        from_date_str (str): Start date (YYYY-MM-DD).
        to_date_str (str): End date (YYYY-MM-DD).
        
    Returns:
        list: A list of daily report dictionaries.
    """
    try:
        headers = {'Accept': 'application/json'}
        # 1. Resolve internal device ID
        r_dev, _ = try_traccar_get("api/devices", params={"uniqueId": vehicle_uid}, timeout=10, headers=headers)
        if r_dev.status_code != 200:
            return None, f"Failed to fetch device info (Status: {r_dev.status_code})"
        
        try:
            devices = r_dev.json()
        except Exception:
            current_app.logger.error(f"External Report: JSON Parse Error for device {vehicle_uid}")
            return None, "Invalid JSON from device API"

        if not devices:
            return None, "Device not found"
        
        internal_id = devices[0]['id']
        
        # 2. Parse dates
        start_date = datetime.strptime(from_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(to_date_str, '%Y-%m-%d')
        
        report_data = []
        current_date = start_date
        
        while current_date <= end_date:
            day_str = current_date.strftime('%Y-%m-%d')
            
            # Define period for the day in Oman time
            day_start = OMAN_TZ.localize(current_date.replace(hour=0, minute=0, second=0, microsecond=0))
            day_end = OMAN_TZ.localize(current_date.replace(hour=23, minute=59, second=59, microsecond=999999))
            
            # Convert to UTC for Traccar
            traccar_from = day_start.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            traccar_to = day_end.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Fetch Trips and Summary for this day
            params = {
                "deviceId": internal_id,
                "from": traccar_from,
                "to": traccar_to
            }
            
            daily_stats = {
                "vehicle": vehicle_uid,
                "date": day_str,
                "first_engine_on": None,
                "last_engine_off": None,
                "total_distance_km": 0.0,
                "average_speed_kmph": 0.0,
                "max_speed_kmph": 0.0
            }
            
            # Fetch Summary
            r_sum, _ = try_traccar_get("api/reports/summary", params=params, timeout=15, headers=headers)
            if r_sum.status_code == 200:
                try:
                    res_sum = r_sum.json()
                    if res_sum:
                        s_data = res_sum[0]
                        daily_stats["total_distance_km"] = round(float(s_data.get("distance", 0)) / 1000, 2)
                        daily_stats["max_speed_kmph"] = round(float(s_data.get("maxSpeed", 0)) * 1.852, 2)
                        
                        engine_on_ms = float(s_data.get("engineHours", 0))
                        
                        # Safety: Avoid division by zero
                        if engine_on_ms > 0:
                            hours = engine_on_ms / 3600000
                            daily_stats["average_speed_kmph"] = round(daily_stats["total_distance_km"] / hours, 2)
                        else:
                            daily_stats["average_speed_kmph"] = 0.0
                            if daily_stats["total_distance_km"] > 0:
                                current_app.logger.warning(f"External Report: Vehicle {vehicle_uid} has distance > 0 but engineHours = 0 on {day_str}")
                except Exception as e:
                    current_app.logger.error(f"External Report: Summary Parse Error for {vehicle_uid} on {day_str}: {e}")
            
            # Fetch Trips for Engine On/Off events
            r_trips, _ = try_traccar_get("api/reports/trips", params=params, timeout=15, headers=headers)
            if r_trips.status_code == 200:
                try:
                    trips = r_trips.json()
                    if trips:
                        # Ignition logic: Traccar trips define engine-on periods
                        trips.sort(key=lambda x: x.get('startTime', ''))
                        
                        # First ignition of the day = startTime of the first trip
                        first_on = trips[0].get('startTime')
                        if first_on:
                            daily_stats["first_engine_on"] = format_traccar_time_to_str(first_on)
                        
                        # Last ignition off of the day = endTime of the last trip
                        last_off = trips[-1].get('endTime')
                        if last_off:
                            daily_stats["last_engine_off"] = format_traccar_time_to_str(last_off)
                    else:
                        current_app.logger.info(f"External Report: No trips found for {vehicle_uid} on {day_str}")
                except Exception as e:
                    current_app.logger.error(f"External Report: Trips Parse Error for {vehicle_uid} on {day_str}: {e}")
            
            report_data.append(daily_stats)
            current_date += timedelta(days=1)
            
        return report_data, None
        
    except Exception as e:
        return None, str(e)

def format_traccar_time_to_str(traccar_time_str):
    """Converts Traccar UTC time string to Oman local time string (YYYY-MM-DD HH:mm:ss)."""
    if not traccar_time_str:
        return None
    try:
        # Use existing helper if possible, or manual parse
        # parse_traccar_to_oman_str returns 'YYYY-MM-DD HH:MM' usually
        # The user wants 'YYYY-MM-DD HH:mm:ss'
        
        # Manually parse to ensure seconds are included
        dt_utc = datetime.fromisoformat(traccar_time_str.replace('Z', '+00:00'))
        dt_oman = dt_utc.astimezone(OMAN_TZ)
        return dt_oman.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return None
