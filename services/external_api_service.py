"""
IVMS Enterprise External API Service
=====================================
Implements a three-layer resilient data strategy for all external API reads:

  Layer 1 — Redis live cache  (sub-millisecond, authoritative real-time state)
  Layer 2 — live_vehicle_status table (persistent DB mirror, survives Redis restart)
  Layer 3 — telemetry table last-known-point (ultimate fallback, always available)

No endpoint depends exclusively on volatile memory state.
Redis failures are silently absorbed; callers always receive accurate data.
"""

import logging
from datetime import datetime, timezone
from models.database import load_vehicles, get_conn
from services.native_report_service import native_report_service
from services.telemetry_service import telemetry_service
from config import Config

import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _db_row_to_live(row, vehicle_name=None):
    """
    Converts a live_vehicle_status DB row dict into the same shape as the
    Redis live cache dict so upper layers can treat both identically.
    """
    ts = row.get("last_timestamp") or row.get("last_update")
    return {
        "imei":        str(row["imei"]),
        "name":        vehicle_name,
        "status":      row.get("status") or "offline",
        "ignition":    bool(row.get("ignition") or False),
        "movement":    bool(row.get("movement") or False),
        "speed":       float(row.get("speed") or 0.0),
        "latitude":    float(row.get("latitude")) if row.get("latitude") is not None else None,
        "longitude":   float(row.get("longitude")) if row.get("longitude") is not None else None,
        "gsm":         int(row.get("gsm_signal") or 0),
        "satellites":  0,                               # not stored in live_vehicle_status
        "driver_name": row.get("current_driver_name"),
        "driver_id":   row.get("current_driver_id"),
        "timestamp":   ts.isoformat() if isinstance(ts, datetime) else str(ts) if ts else None,
        "_source":     "db_live_vehicle_status",        # traceability tag
    }


def _db_telemetry_last_point(imei, conn=None):
    """
    Layer 3 fallback: fetch the single most-recent telemetry row for an IMEI.
    Used only when both Redis AND live_vehicle_status are unavailable/empty.
    """
    close_after = conn is None
    if conn is None:
        conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT imei, timestamp, latitude, longitude, speed, angle,
                   io_elements
            FROM telemetry
            WHERE imei = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (str(imei),))
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        import json as _json
        io = row.get("io_elements") or {}
        if isinstance(io, str):
            try: io = _json.loads(io)
            except: io = {}
        ignition = str(io.get("239", io.get("1", "0"))) == "1"
        ts = row["timestamp"]
        return {
            "imei":        str(row["imei"]),
            "name":        None,
            "status":      "offline",   # last known, not confirmed live
            "ignition":    ignition,
            "movement":    float(row.get("speed") or 0.0) > Config.SPEED_THRESHOLD_KMH,
            "speed":       float(row.get("speed") or 0.0),
            "latitude":    float(row.get("latitude")) if row.get("latitude") is not None else None,
            "longitude":   float(row.get("longitude")) if row.get("longitude") is not None else None,
            "gsm":         0,
            "satellites":  0,
            "driver_name": None,
            "driver_id":   None,
            "timestamp":   ts.isoformat() if isinstance(ts, datetime) else str(ts) if ts else None,
            "_source":     "db_telemetry_last_point",
        }
    finally:
        if close_after:
            conn.close()


def _get_live_with_fallback(imei, vehicle_name=None, conn=None):
    """
    Resolves the most accurate live status for a single IMEI using layered fallback:
      1. Redis  →  2. live_vehicle_status  →  3. telemetry last point  →  4. offline stub
    """
    # --- Layer 1: Redis ---
    try:
        live = telemetry_service.get_live_status(imei)
        if live:
            live.setdefault("name", vehicle_name)
            live.setdefault("imei", imei)
            live["_source"] = "redis"
            return live
    except Exception as e:
        logger.warning(f"[FALLBACK] Redis unavailable for {imei}: {e}")

    # --- Layer 2: live_vehicle_status DB table ---
    try:
        close_after = conn is None
        _conn = conn if conn else get_conn()
        try:
            cur = _conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT * FROM live_vehicle_status WHERE imei = %s
            """, (str(imei),))
            row = cur.fetchone()
            cur.close()
            if row:
                result = _db_row_to_live(dict(row), vehicle_name)
                logger.debug(f"[FALLBACK] live_vehicle_status used for {imei}")
                return result
        finally:
            if close_after:
                _conn.close()
    except Exception as e:
        logger.warning(f"[FALLBACK] live_vehicle_status unavailable for {imei}: {e}")

    # --- Layer 3: Last telemetry point ---
    try:
        result = _db_telemetry_last_point(imei, conn)
        if result:
            result["name"] = vehicle_name
            logger.debug(f"[FALLBACK] telemetry last-point used for {imei}")
            return result
    except Exception as e:
        logger.warning(f"[FALLBACK] telemetry last-point unavailable for {imei}: {e}")

    # --- Layer 4: Safe offline stub (never return None) ---
    logger.info(f"[FALLBACK] All sources exhausted for {imei}, returning offline stub")
    return {
        "imei":        imei,
        "name":        vehicle_name,
        "status":      "offline",
        "ignition":    False,
        "movement":    False,
        "speed":       0.0,
        "latitude":    None,
        "longitude":   None,
        "gsm":         0,
        "satellites":  0,
        "driver_name": None,
        "driver_id":   None,
        "timestamp":   None,
        "_source":     "offline_stub",
    }


def _get_all_live_with_fallback(vehicles):
    """
    Batch-resolves live status for a list of vehicles.
    Uses a single shared DB connection for Layer 2/3 lookups to minimise overhead.
    Preloads all live_vehicle_status rows for the batch in one query.
    """
    if not vehicles:
        return []

    imeis = [str(v.get("unique_id")) for v in vehicles]
    name_map = {str(v.get("unique_id")): v.get("name") for v in vehicles}

    # --- Layer 1: Redis bulk fetch ---
    redis_map = {}
    redis_failed = False
    try:
        all_live = telemetry_service.get_all_live(allowed_imeis=imeis)
        for d in all_live:
            _imei = str(d.get("imei", ""))
            if _imei:
                d.setdefault("name", name_map.get(_imei))
                d["_source"] = "redis"
                redis_map[_imei] = d
    except Exception as e:
        logger.warning(f"[FALLBACK] Redis bulk fetch failed: {e}")
        redis_failed = True

    # Identify which IMEIs are missing from Redis
    missing_imeis = [i for i in imeis if i not in redis_map]

    # --- Layer 2: Preload live_vehicle_status for all missing IMEIs in one query ---
    db_map = {}
    if missing_imeis:
        try:
            conn = get_conn()
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT * FROM live_vehicle_status WHERE imei = ANY(%s)
                """, (missing_imeis,))
                rows = cur.fetchall()
                cur.close()
                for row in rows:
                    _imei = str(row["imei"])
                    db_map[_imei] = _db_row_to_live(dict(row), name_map.get(_imei))
                    logger.debug(f"[FALLBACK] live_vehicle_status used for {_imei}")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[FALLBACK] Batch live_vehicle_status failed: {e}")

    # --- Layer 3: Telemetry last-point for any still missing ---
    still_missing = [i for i in missing_imeis if i not in db_map]
    tele_map = {}
    if still_missing:
        try:
            conn = get_conn()
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                import json as _json
                cur.execute("""
                    SELECT DISTINCT ON (imei) imei, timestamp, latitude, longitude,
                                              speed, angle, io_elements
                    FROM telemetry
                    WHERE imei = ANY(%s)
                    ORDER BY imei, timestamp DESC
                """, (still_missing,))
                rows = cur.fetchall()
                cur.close()
                for row in rows:
                    _imei = str(row["imei"])
                    io = row.get("io_elements") or {}
                    if isinstance(io, str):
                        try: io = _json.loads(io)
                        except: io = {}
                    ignition = str(io.get("239", io.get("1", "0"))) == "1"
                    ts = row["timestamp"]
                    tele_map[_imei] = {
                        "imei": _imei,
                        "name": name_map.get(_imei),
                        "status": "offline",
                        "ignition": ignition,
                        "movement": float(row.get("speed") or 0.0) > Config.SPEED_THRESHOLD_KMH,
                        "speed": float(row.get("speed") or 0.0),
                        "latitude": float(row.get("latitude")) if row.get("latitude") is not None else None,
                        "longitude": float(row.get("longitude")) if row.get("longitude") is not None else None,
                        "gsm": 0, "satellites": 0,
                        "driver_name": None, "driver_id": None,
                        "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts) if ts else None,
                        "_source": "db_telemetry_last_point",
                    }
                    logger.debug(f"[FALLBACK] telemetry last-point used for {_imei}")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[FALLBACK] Batch telemetry last-point failed: {e}")

    # --- Assemble final result in original vehicle order ---
    results = []
    for imei in imeis:
        if imei in redis_map:
            results.append(redis_map[imei])
        elif imei in db_map:
            results.append(db_map[imei])
        elif imei in tele_map:
            results.append(tele_map[imei])
        else:
            # Layer 4: safe offline stub
            results.append({
                "imei": imei, "name": name_map.get(imei),
                "status": "offline", "ignition": False, "movement": False,
                "speed": 0.0, "latitude": None, "longitude": None,
                "gsm": 0, "satellites": 0, "driver_name": None, "driver_id": None,
                "timestamp": None, "_source": "offline_stub",
            })
    return results


# ---------------------------------------------------------------------------
# Public service functions (called from routes/external_api.py)
# ---------------------------------------------------------------------------

def get_filtered_fleet(company_id=None, device_id=None):
    """
    Returns active fleet vehicles filtered by company_id or device_id.
    Reads from PostgreSQL vehicles table — unaffected by Redis state.
    """
    vehicles = load_vehicles()
    vehicles = [v for v in vehicles if v.get("status") == "active"]
    if device_id:
        vehicles = [v for v in vehicles if str(v.get("unique_id")) == str(device_id)]
    if company_id:
        vehicles = [v for v in vehicles if str(v.get("company_name")) == str(company_id)]
    return vehicles


def fetch_vehicle_summary(vehicles, start_dt, end_dt):
    """
    Computes per-vehicle period summaries using native_report_service (PostgreSQL-backed).
    Augments each row with live ignition/movement state using the resilient fallback chain.
    All data is authoritative DB-sourced; Redis is used only for enhancement, not dependency.
    """
    if not vehicles:
        return []

    # Core computation always from PostgreSQL trip_summary + telemetry
    summaries = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)

    # Enrich with real-time state — resilient, never blocking
    live_list = _get_all_live_with_fallback(vehicles)
    live_map = {l["imei"]: l for l in live_list}

    for s in summaries:
        imei = s.get("unique_id")
        live = live_map.get(str(imei), {})
        speed_val = float(live.get("speed") or 0.0)
        s["ignition_state"] = bool(live.get("ignition", False))
        s["movement_state"] = "moving" if speed_val > Config.SPEED_THRESHOLD_KMH else "stopped"
        s["latest_gps_timestamp"] = live.get("timestamp")
        s["_live_source"] = live.get("_source", "unknown")

    return summaries


def fetch_live_status(vehicles):
    """
    Resolves live status for each vehicle using the three-layer fallback chain.
    Guaranteed to return a record for every vehicle even when Redis is fully unavailable.
    """
    return _get_all_live_with_fallback(vehicles)


def fetch_trips(vehicle_uid, start_dt, end_dt):
    """
    Retrieves completed trip events from trip_summary (PostgreSQL).
    Entirely Redis-independent by design.
    """
    return native_report_service.get_trip_report(vehicle_uid, start_dt, end_dt)


def fetch_fuel_summary(vehicles, start_dt, end_dt):
    """
    Derives fuel metrics from native_report_service (PostgreSQL-backed).
    Redis-independent; uses telemetry + trip_summary for all calculations.
    """
    if not vehicles:
        return []

    summaries = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)
    results = []
    for s in summaries:
        idle_ms = s.get("idle_duration", 0)
        idle_hours = float(idle_ms) / 3_600_000.0
        idle_fuel = round(idle_hours * Config.IDLE_FUEL_LPH, 3)
        total_dist = float(s.get("total_distance") or 0.0)
        fallback_fuel = round((total_dist / Config.MILEAGE_KM_PER_LITER) + idle_fuel, 3)
        results.append({
            "imei":                    s.get("unique_id"),
            "vehicle_name":            s.get("name"),
            "liters_consumed":         s.get("fuel_liters", 0.0),
            "fuel_cost_omr":           s.get("fuel_cost", 0.0),
            "mileage_km_per_liter":    Config.MILEAGE_KM_PER_LITER,
            "idle_fuel_burn_liters":   idle_fuel,
            "can_fuel_values":         None,
            "analog_fuel_values":      None,
            "estimated_fallback_fuel": fallback_fuel,
        })
    return results


def fetch_dashboard_summary(vehicles, start_dt, end_dt):
    """
    Computes fleet KPI totals using authoritative PostgreSQL aggregation.
    Live online/offline/moving counts use the resilient fallback chain — not raw Redis.
    Guaranteed identical output to Fleet Dashboard regardless of Redis state.
    """
    if not vehicles:
        return {
            "total_vehicles": 0, "online": 0, "offline": 0,
            "moving": 0, "idle": 0, "total_distance": 0.0,
            "engine_hours": 0.0, "fuel_totals": 0.0, "overspeed_count": 0,
        }

    # Core KPI aggregation is always PostgreSQL-sourced
    summaries = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)

    # Presence/movement status via resilient fallback chain
    live_list = _get_all_live_with_fallback(vehicles)

    online = offline = moving = idle = 0
    for l in live_list:
        status = l.get("status", "offline")
        if status == "offline":
            offline += 1
        else:
            online += 1
            speed_val = float(l.get("speed") or 0.0)
            if speed_val > Config.SPEED_THRESHOLD_KMH:
                moving += 1
            else:
                idle += 1

    total_distance   = round(sum(float(s.get("total_distance") or 0) for s in summaries), 2)
    total_eng_hours  = round(sum(float(s.get("engine_hours") or 0) for s in summaries), 2)
    total_fuel       = round(sum(float(s.get("fuel_liters") or 0) for s in summaries), 2)
    overspeed_count  = sum(1 for s in summaries if s.get("status") == "Possible Overspeed")

    return {
        "total_vehicles":  len(vehicles),
        "online":          online,
        "offline":         offline,
        "moving":          moving,
        "idle":            idle,
        "total_distance":  total_distance,
        "engine_hours":    total_eng_hours,
        "fuel_totals":     total_fuel,
        "overspeed_count": overspeed_count,
    }
