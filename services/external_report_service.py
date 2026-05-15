import pytz
from datetime import datetime, timedelta
from services.time_service import SYSTEM_TZ
from services.native_report_service import native_report_service
from flask import current_app

def get_vehicle_summary_report(vehicle_uid, from_date_str, to_date_str):
    """
    Calculates daily vehicle summary for a given vehicle and date range using native telemetry.
    """
    try:
        # 1. Parse dates
        start_date = datetime.strptime(from_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(to_date_str, '%Y-%m-%d')
        
        # We need to find the vehicle to get its name
        from models.database import get_vehicle_by_uid
        vehicle = get_vehicle_by_uid(vehicle_uid)
        if not vehicle:
            return None, "Vehicle not found"

        report_data = []
        current_date = start_date
        
        while current_date <= end_date:
            day_str = current_date.strftime('%Y-%m-%d')
            
            # Define period for the day in Oman time
            day_start = SYSTEM_TZ.localize(current_date.replace(hour=0, minute=0, second=0, microsecond=0))
            day_end = SYSTEM_TZ.localize(current_date.replace(hour=23, minute=59, second=59, microsecond=999999))
            
            # Fetch Summary from Native Service
            summary_list = native_report_service.get_fleet_summary([vehicle], day_start, day_end)
            
            daily_stats = {
                "vehicle": vehicle_uid,
                "date": day_str,
                "first_engine_on": None, # Native trips have start_time
                "last_engine_off": None, # Native trips have end_time
                "total_distance_km": 0.0,
                "average_speed_kmph": 0.0,
                "max_speed_kmph": 0.0
            }

            if summary_list:
                s = summary_list[0]
                daily_stats["total_distance_km"] = s["total_distance"]
                daily_stats["max_speed_kmph"] = s["max_speed"]
                daily_stats["average_speed_kmph"] = s["average_speed"]

                # Fetch first and last trip for engine on/off
                trips = native_report_service.get_trip_report(vehicle_uid, day_start, day_end)
                if trips:
                    daily_stats["first_engine_on"] = trips[0]["start_time"].strftime('%Y-%m-%d %H:%M:%S')
                    daily_stats["last_engine_off"] = trips[-1]["end_time"].strftime('%Y-%m-%d %H:%M:%S')

            report_data.append(daily_stats)
            current_date += timedelta(days=1)
            
        return report_data, None
        
    except Exception as e:
        current_app.logger.error(f"External Report Error: {e}")
        return None, str(e)
