from datetime import datetime, timezone

def format_datetime(dt):
    """Encodes naive or aware datetime objects to standard UTC ISO 8601 strings with 'Z' suffix."""
    if not dt:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return str(dt)

def safe_float(val, fallback=0.0):
    try:
        return float(val) if val is not None else fallback
    except (ValueError, TypeError):
        return fallback

def safe_int(val, fallback=0):
    try:
        return int(val) if val is not None else fallback
    except (ValueError, TypeError):
        return fallback

def serialize_vehicle_summary(summary_data, compatibility=None):
    """
    Serializes daily fleet metrics.
    If compatibility == 'traccar', converts to previous Traccar summary report format.
    """
    if compatibility == 'traccar':
        results = []
        for s in summary_data:
            results.append({
                "deviceId": s.get("unique_id"),
                "deviceName": s.get("name"),
                "distance": safe_float(s.get("total_distance")),
                "averageSpeed": safe_float(s.get("average_speed")),
                "maxSpeed": safe_float(s.get("max_speed")),
                "spentFuel": safe_float(s.get("fuel_liters")),
                "engineHours": int(safe_float(s.get("engine_hours")) * 3600 * 1000) # milliseconds
            })
        return results
        
    # Standard native Odoo-ready format
    return [
        {
            "vehicle_name": s.get("name"),
            "imei": s.get("unique_id"),
            "total_distance_km": safe_float(s.get("total_distance")),
            "fuel_consumed_liters": safe_float(s.get("fuel_liters")),
            "fuel_cost_omr": safe_float(s.get("fuel_cost")),
            "engine_hours": safe_float(s.get("engine_hours")),
            "max_speed_kmph": safe_float(s.get("max_speed")),
            "avg_speed_kmph": safe_float(s.get("average_speed")),
            "idle_duration_sec": int(safe_float(s.get("idle_duration")) / 1000),
            "parked_duration_sec": int(safe_float(s.get("off_duration")) / 1000),
            "ignition_state": bool(s.get("ignition_state")),
            "movement_state": s.get("movement_state", "stopped"),
            "latest_gps_timestamp": format_datetime(s.get("latest_gps_timestamp"))
        }
        for s in summary_data
    ]

def serialize_live_status(live_data, compatibility=None):
    """
    Serializes real-time status of vehicles.
    If compatibility == 'traccar', returns a structure mapping to standard Traccar /api/devices items.
    """
    if compatibility == 'traccar':
        results = []
        for l in live_data:
            speed = safe_float(l.get("speed"))
            course = safe_float(l.get("course") or l.get("angle"))
            results.append({
                "id": l.get("imei"),
                "uniqueId": l.get("imei"),
                "name": l.get("name"),
                "status": l.get("status", "offline"),
                "lastUpdate": format_datetime(l.get("timestamp")),
                "position": {
                    "latitude": l.get("latitude"),
                    "longitude": l.get("longitude"),
                    "speed": speed,
                    "course": course,
                    "attributes": {
                        "ignition": bool(l.get("ignition")),
                        "gsm": safe_int(l.get("gsm")),
                        "satellites": safe_int(l.get("satellites")),
                        "rfid": l.get("rfid")
                    }
                } if l.get("latitude") is not None else None
            })
        return results
        
    return [
        {
            "imei": l.get("imei"),
            "vehicle_name": l.get("name"),
            "online_state": l.get("status", "offline"),
            "movement_state": "moving" if safe_float(l.get("speed")) > 2.0 else "stopped",
            "ignition_state": bool(l.get("ignition")),
            "gsm_signal": safe_int(l.get("gsm")),
            "satellites_count": safe_int(l.get("satellites")),
            "current_speed_kmph": safe_float(l.get("speed")),
            "latitude": l.get("latitude"),
            "longitude": l.get("longitude"),
            "last_update": format_datetime(l.get("timestamp")),
            "driver_name": l.get("driver_name"),
            "driver_id": l.get("driver_id")
        }
        for l in live_data
    ]

def serialize_trips(trips_data, compatibility=None):
    """Serializes a collection of trip reports."""
    if compatibility == 'traccar':
        return [
            {
                "deviceId": t.get("imei"),
                "deviceName": t.get("imei"),
                "distance": safe_float(t.get("distance_km")),
                "averageSpeed": safe_float(t.get("avg_speed")),
                "maxSpeed": safe_float(t.get("max_speed")),
                "spentFuel": safe_float(t.get("fuel_consumed")),
                "startTime": format_datetime(t.get("start_time")),
                "endTime": format_datetime(t.get("end_time")),
                "duration": safe_int(t.get("duration_sec")) * 1000, # ms
                "startAddress": t.get("start_address", "N/A"),
                "endAddress": t.get("end_address", "N/A")
            }
            for t in trips_data
        ]
        
    return [
        {
            "trip_start": format_datetime(t.get("start_time")),
            "trip_end": format_datetime(t.get("end_time")),
            "distance_km": safe_float(t.get("distance_km")),
            "duration_sec": safe_int(t.get("duration_sec")),
            "fuel_liters": safe_float(t.get("fuel_consumed")),
            "idle_duration_sec": safe_int(t.get("idle_duration_sec")),
            "route_point_count": safe_int(t.get("route_point_count"))
        }
        for t in trips_data
    ]

def serialize_fuel_summary(fuel_data, compatibility=None):
    """Serializes daily fuel logs."""
    if compatibility == 'traccar':
        return [
            {
                "deviceId": f.get("imei"),
                "deviceName": f.get("vehicle_name"),
                "spentFuel": safe_float(f.get("liters_consumed")),
                "fuelCost": safe_float(f.get("fuel_cost_omr")),
                "mileage": safe_float(f.get("mileage_km_per_liter")),
                "idleFuel": safe_float(f.get("idle_fuel_burn_liters")),
                "fallbackFuel": safe_float(f.get("estimated_fallback_fuel"))
            }
            for f in fuel_data
        ]
        
    return fuel_data
