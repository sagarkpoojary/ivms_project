import os
import requests
from datetime import datetime, timedelta
import pytz
from services.time_service import get_oman_now
from flask import Blueprint, request, jsonify, session, current_app, render_template, redirect, url_for
from auth.utils import role_required, get_filtered_vehicles
from services.traccar_service import full_traccar_host, try_traccar_get
from models.database import load_server_config, save_server_config
from extensions import cache
from config import Config, BASE_DIR
from services.telemetry_service import telemetry_service

api_bp = Blueprint('api', __name__)

@api_bp.route("/api/events")
def proxy_events():
    if not session.get("logged_in"): return jsonify([]), 401
    try:
        now = get_oman_now()
        start = now - timedelta(hours=24)
        # Traccar expects UTC
        params = {
            "from": start.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "to": now.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        r, _ = try_traccar_get("api/events", params=params, timeout=10)
        return jsonify(r.json()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@api_bp.route("/api/alerts")
def api_alerts():
    if not session.get("logged_in"): return jsonify([]), 401
    try:
        from services.report_service import get_period_dates
        start_dt, end_dt = get_period_dates('Today')
        # Convert to UTC as required by Traccar
        from pytz import utc
        tr_from = start_dt.astimezone(utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        tr_to = end_dt.astimezone(utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        r, _ = try_traccar_get("api/reports/events", params={
            "type": "deviceOverspeed", 
            "from": tr_from,
            "to": tr_to
        }, timeout=10)
        if r.status_code != 200:
            log_path = os.path.join(BASE_DIR, "api_errors.log")
            with open(log_path, "a") as f:
                f.write(f"Alerts Error: Status {r.status_code}, Body: {r.text}\n")
        return jsonify(r.json())
    except Exception as e:
        import traceback
        log_path = os.path.join(BASE_DIR, "api_errors.log")
        with open(log_path, "a") as f:
            f.write(f"Alerts Exception: {str(e)}\n{traceback.format_exc()}\n")
        return jsonify({"error": str(e)}), 500

@api_bp.route("/api/system-stats")
@role_required('user')
def api_system_stats():
    from models.database import get_system_stats
    return jsonify(get_system_stats())

@api_bp.route('/api/devices')
@role_required('user')
def devices_proxy():
    uid = request.args.get("uid")
    from auth.utils import get_filtered_vehicles
    from services.telemetry_service import telemetry_service
    
    v_list = get_filtered_vehicles()
    if uid:
        v_list = [v for v in v_list if str(v.get('unique_id')) == str(uid)]
    
    results = []
    for v in v_list:
        imei = str(v.get('unique_id'))
        live = telemetry_service.get_live_status(imei)
        
        device_data = {
            "id": imei,
            "uniqueId": imei,
            "name": v.get('name'),
            "status": live.get('status', 'offline') if live else "offline",
            "lastUpdate": live.get('timestamp') if live else "-",
            "position": {
                "latitude": live.get('latitude') if live else None,
                "longitude": live.get('longitude') if live else None,
                "speed": live.get('speed', 0) if live else 0,
                "course": live.get('angle', 0) if live else 0,
                "attributes": {
                    "ignition": live.get('ignition', False) if live else False,
                    "bat_v": live.get('bat_v', 0) if live else 0
                }
            } if live else None
        }
        results.append(device_data)
        
    return jsonify(results)

@api_bp.route('/server-settings', methods=['GET', 'POST'])
@role_required('main_admin')
def server_settings():
    cfg = load_server_config()
    if request.method == 'POST':
        new_ip = request.form.get('server_ip', '').strip()
        new_threshold = request.form.get('stop_threshold', '5').strip()
        admin_email = request.form.get('admin_email', '').strip()
        admin_pass = request.form.get('admin_pass', '').strip()

        if new_ip:
            if new_ip.startswith("http://") or new_ip.startswith("https://"):
                new_ip = new_ip.split("://", 1)[1]
            servers = cfg.get("servers", [])
            if new_ip not in servers: servers.append(new_ip)
            cfg["servers"] = servers
            cfg["active_ip"] = new_ip

        if new_threshold.isdigit():
            cfg["stop_threshold"] = int(new_threshold)

        if admin_email:
            cfg['admin_email'] = admin_email
        if admin_pass:
            cfg['admin_pass'] = admin_pass

        save_server_config(cfg)
        return redirect(url_for('api.server_settings'))
    return render_template('server_settings.html', config=cfg)

@api_bp.route("/api/device-models")
def device_models():
    try:
        r = requests.get("https://www.traccar.org/devices/", timeout=5)
        return jsonify({"html": r.text})
    except Exception as e: return jsonify({"error": str(e)}), 500

@api_bp.route('/api/dashboard/devices')
@role_required('user')
def api_dashboard_devices():
    try:
        r, _ = try_traccar_get("api/devices", timeout=10)
        if r.status_code != 200: return jsonify({'error': 'bad_status'}), 500
        allowed_uids = {str(v.get('unique_id')) for v in get_filtered_vehicles()}
        return jsonify([d for d in r.json() if str(d.get('uniqueId')) in allowed_uids])
    except Exception as e: return jsonify({'error': str(e)}), 500

@api_bp.route('/api/dashboard/groups')
@role_required('user')
@cache.cached(timeout=600) 
def api_dashboard_groups():
    try:
        r, _ = try_traccar_get("api/groups", timeout=10)
        if r.status_code == 200: return jsonify(r.json())
    except: pass
    return jsonify([])

@api_bp.route('/api/dashboard/distance')
@role_required('user')
def api_dashboard_distance():
    device_id = request.args.get('id')
    if not device_id: return jsonify({'error': 'missing_id'}), 400
    from_p = request.args.get('from'); to_p = request.args.get('to')
    if not from_p or not to_p:
        now = get_oman_now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Convert to UTC for Traccar
        from_p = start.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        to_p = now.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        r, _ = try_traccar_get("api/reports/summary", params={"deviceId": device_id, "from": from_p, "to": to_p}, timeout=12)
        if r.status_code == 200 and r.json():
            return jsonify({'distance': round(r.json()[0].get('distance', 0) / 1000, 2)})
    except Exception as e: pass
    return jsonify({'distance': 0})

@api_bp.route('/api/dashboard/bulk-sync')
@role_required('user')
def api_dashboard_bulk_sync():
    period = request.args.get('period', 'Today')
    device_uid = request.args.get('uid')
    email = session.get('email')
    
    cache_key = f"bulk_sync_{email}_{period}_{device_uid}"
    cached = cache.get(cache_key)
    if cached is not None: return jsonify(cached)

    # 1. Fetch Traccar Host
    host = full_traccar_host()
    if not host: return jsonify({'error': 'no_host'}), 500
    
    # 2. Identify allowed vehicles
    from auth.utils import get_filtered_vehicles
    allowed_vehicles = get_filtered_vehicles()
    if not allowed_vehicles:
        return jsonify({'devices': [], 'summaries': {}})
    
    allowed_uids = {str(v.get('unique_id')) for v in allowed_vehicles}
    
    # Filter by specific UID if requested
    if device_uid:
        if device_uid not in allowed_uids:
            return jsonify({'devices': [], 'summaries': {}})
        allowed_uids = {device_uid}

    try:
        # 3. Fetch all devices from Traccar (one call)
        r_dev, _ = try_traccar_get("api/devices", timeout=10)
        if r_dev.status_code != 200: return jsonify({'error': 'traccar_error'}), 500
        
        all_traccar_devices = r_dev.json()
        my_devices = [d for d in all_traccar_devices if str(d.get('uniqueId')) in allowed_uids]
        
        if not my_devices:
            return jsonify({'devices': [], 'summaries': {}})

        # 4. Fetch positions for these devices in one call
        # Fetching all positions is more reliable than passing a list of IDs which can be dropped by some servers/providers
        device_ids = [d['id'] for d in my_devices]
        pos_r, _ = try_traccar_get("api/positions", timeout=10)
        pos_map = {}
        if pos_r.status_code == 200:
            for p in pos_r.json():
                pos_map[p['deviceId']] = p
        
        for d in my_devices:
            imei = str(d.get('uniqueId'))
            local_status = telemetry_service.get_live_status(imei)
            
            if local_status:
                d['status'] = 'online'
                d['position'] = {
                    "deviceId": d['id'],
                    "latitude": local_status["latitude"],
                    "longitude": local_status["longitude"],
                    "speed": local_status["speed"],
                    "course": local_status["angle"],
                    "altitude": local_status["altitude"],
                    "deviceTime": local_status["timestamp"],
                    "attributes": {
                        "sat": local_status["satellites"],
                        "batteryLevel": int(local_status.get("bat_v", 0) * 10)
                    }
                }
            else:
                d['position'] = pos_map.get(d['id'])

        # 5. Fetch distances for all devices in one call (or small batch)
        # We need date range
        from services.report_service import get_period_dates
        import pytz
        start_dt, end_dt = get_period_dates(period)
        
        # Correctly convert Oman time (from get_period_dates) to UTC for Traccar
        tr_from = start_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        tr_to = end_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        sum_r, _ = try_traccar_get("api/reports/summary", params={
            "deviceId": device_ids,
            "from": tr_from,
            "to": tr_to
        }, timeout=30)
        
        summary_map = {}
        if sum_r.status_code == 200:
            for s in sum_r.json():
                dist_km = round(s.get('distance', 0) / 1000, 2)
                engine_on_ms = s.get('engineHours', 0)
                engine_on_h = engine_on_ms / 3600000
                
                avg_spd = (s.get('averageSpeed', 0) or 0) * 1.852 # kn to kmh
                moving_h = 0
                if avg_spd > 5:
                    moving_h = dist_km / avg_spd
                
                if engine_on_h > 0:
                    idle_h = max(0, engine_on_h - moving_h)
                    fuel_liters = (dist_km / Config.MILEAGE_KM_PER_LITER) + (idle_h * Config.IDLE_FUEL_LPH)
                else:
                    fuel_liters = dist_km / Config.MILEAGE_KM_PER_LITER
                
                fuel_liters = round(fuel_liters, 2)
                fuel_cost = round(fuel_liters * Config.FUEL_PRICE_OMR, 3)
                
                summary_map[s['deviceId']] = {
                    'distance': dist_km,
                    'engineHours': round(engine_on_h, 1),
                    'fuelLiters': fuel_liters,
                    'fuelCost': fuel_cost
                }

        result = {
            'devices': my_devices,
            'summaries': summary_map,
            'period': period
        }
        cache.set(cache_key, result, timeout=20)
        return jsonify(result)

    except Exception as e:
        import traceback
        with open("api_errors.log", "a") as f:
            f.write(f"Bulk Sync Exception: {str(e)}\n{traceback.format_exc()}\n")
        current_app.logger.error(f"Bulk sync error: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/reports/idle')
@role_required('user')
def api_idle_report():
    from services.report_service import get_idle_events, get_period_dates
    from services.traccar_service import full_traccar_host, get_traccar_session
    from pytz import utc
    
    uid = request.args.get('vehicle_id')
    from_date = request.args.get('start_date')
    to_date = request.args.get('end_date')
    try:
        min_idle = int(request.args.get('min_idle_time', 5))
    except:
        min_idle = 5

    # Get Date Range
    start_dt, end_dt = get_period_dates('Custom', from_date, to_date)
    traccar_from = start_dt.astimezone(utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    traccar_to = end_dt.astimezone(utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    vehicles = get_filtered_vehicles()
    if uid:
        vehicles = [v for v in vehicles if str(v.get('unique_id')) == str(uid)]
    
    s = get_traccar_session()
    traccar = full_traccar_host()
    
    device_map = {}
    try:
        r_dev = s.get(f"{traccar}/api/devices", timeout=10)
        if r_dev.status_code == 200:
            for d in r_dev.json():
                device_map[str(d.get("uniqueId"))] = d.get("id")
    except: pass

    results = []
    for v in vehicles:
        iid = device_map.get(str(v.get('unique_id')))
        if iid:
            res = get_idle_events(v, traccar_from, traccar_to, min_idle, traccar, s, internal_id=iid)
            results.append({
                'vehicle_id': v.get('unique_id'),
                'vehicle_name': v.get('name'),
                'total_idle_time': res.get('summary', {}).get('total_idle_time', 0),
                'total_idle_events': res.get('summary', {}).get('total_idle_events', 0),
                'idle_events': res.get('events', [])
            })
    
    return jsonify(results)

@api_bp.route('/api/dashboard/combined-report')
@role_required('user')
def api_combined_report():
    device_id = request.args.get('deviceId')
    if not device_id: return jsonify({'error': 'no_id'}), 400
    from_p = request.args.get('from')
    to_p = request.args.get('to')
    if not from_p or not to_p: return jsonify({'error': 'missing_range'}), 400
    
    result = {'trips': [], 'events': [], 'stops': []}
    
    try:
        # Fetch trips
        trips_r, _ = try_traccar_get("api/reports/trips", params={"deviceId": device_id, "from": from_p, "to": to_p}, timeout=15)
        if trips_r.status_code == 200:
            result['trips'] = trips_r.json()
        
        # Fetch events with position data
        events_r, _ = try_traccar_get("api/reports/events", params={"deviceId": device_id, "from": from_p, "to": to_p}, timeout=15)
        if events_r.status_code == 200:
            events = events_r.json()
            # Fetch positions for each event to get address
            for event in events:
                if event.get('positionId'):
                    try:
                        pos_r, _ = try_traccar_get(f"api/positions", params={"id": event['positionId']}, timeout=5)
                        if pos_r.status_code == 200:
                            positions = pos_r.json()
                            if positions:
                                event['position'] = positions[0]
                    except:
                        pass
            result['events'] = events
        
        # Fetch stops
        stops_r, _ = try_traccar_get("api/reports/stops", params={"deviceId": device_id, "from": from_p, "to": to_p}, timeout=15)
        if stops_r.status_code == 200:
            result['stops'] = stops_r.json()
            
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Combined report error: {e}")
        return jsonify({'trips': [], 'events': [], 'stops': [], 'error': str(e)})

@api_bp.route('/api/debug/device/<uid>')
@role_required('admin')
def debug_device(uid):
    result = {'uid': uid, 'traccar_host': full_traccar_host(), 'device_data': None, 'position_data': None, 'errors': []}
    try:
        r, tr = try_traccar_get("api/devices", timeout=10)
        result['traccar_host'] = tr
        if r.status_code == 200:
            device = next((d for d in r.json() if str(d.get("uniqueId")) == str(uid)), None)
            if device:
                result['device_data'] = device
                pos_r, _ = try_traccar_get("api/positions", params={"deviceId": device.get('id')}, timeout=10)
                if pos_r.status_code == 200: result['position_data'] = pos_r.json()
    except Exception as e: result['errors'].append(str(e))
    return jsonify(result)


@api_bp.route('/api/debug/traccar')
@role_required('admin')
def debug_traccar():
    """Return Traccar host, credentials presence and a session check for debugging."""
    cfg = load_server_config()
    tr = full_traccar_host()
    email = cfg.get('admin_email') or None
    has_creds = bool(email or ("TRACCAR_ADMIN_EMAIL" in (os.environ if 'os' in globals() else {})))

    result = {'traccar_host': tr, 'has_master_credentials': has_creds, 'session_ok': False, 'detail': None}
    if not tr:
        result['detail'] = 'No active Traccar host configured (active_ip)'
        return jsonify(result), 200

    try:
        from services.traccar_service import get_traccar_session, ensure_admin_login
        s = get_traccar_session()
        ok = ensure_admin_login(s)
        result['session_ok'] = bool(ok)
    except Exception as e:
        result['detail'] = str(e)

    return jsonify(result)

@api_bp.route('/api/reports/route')
@role_required('user')
def api_report_route():
    unique_id = request.args.get('unique_id')
    from_p = request.args.get('from')
    to_p = request.args.get('to')
    
    # Log parameters to app logger
    current_app.logger.info(f"API Route Request: unique_id={unique_id}, from={from_p}, to={to_p}")

    if not unique_id or not from_p or not to_p:
        return jsonify({'error': 'Missing parameters'}), 400

    try:
        # Resolve internal device ID
        # Traccar api/devices with uniqueId returns a list [Device] or []
        current_app.logger.info(f"Route API: Fetching device info for unique_id={unique_id}")
        r_dev, _ = try_traccar_get("api/devices", params={"uniqueId": unique_id}, timeout=10)
        
        if r_dev.status_code != 200:
            current_app.logger.error(f"Device fetch failed: status={r_dev.status_code}, body={r_dev.text[:500]}")
            return jsonify({'error': f'Failed to resolve device (Status: {r_dev.status_code})', 'details': r_dev.text[:500]}), r_dev.status_code
            
        try:
            devices = r_dev.json()
        except Exception as je:
            current_app.logger.error(f"Error parsing device JSON. Status: {r_dev.status_code}, Body: {r_dev.text[:500]}")
            return jsonify({'error': 'Invalid JSON response from device API', 'details': r_dev.text[:500]}), 500

        if not devices:
            current_app.logger.error(f"Device not found for unique_id={unique_id}")
            return jsonify({'error': 'Device not found in Traccar'}), 404
        
        internal_id = devices[0]['id']
        current_app.logger.info(f"Resolved unique_id={unique_id} to internal_id={internal_id}")
        
        # Fetch route
        current_app.logger.info(f"Route API: Fetching route for internal_id={internal_id} from {from_p} to {to_p}")
        r_route, _ = try_traccar_get("api/reports/route", params={
            "deviceId": internal_id,
            "from": from_p,
            "to": to_p
        }, timeout=30, headers={'Accept': 'application/json'})
        
        if r_route.status_code == 200:
            try:
                return jsonify(r_route.json())
            except Exception as je:
                current_app.logger.error(f"Error parsing route JSON. Body starts with: {r_route.text[:500]}")
                return jsonify({'error': 'Invalid JSON response from route API', 'details': r_route.text[:500]}), 500
        else:
            current_app.logger.error(f"Route fetch failed: status={r_route.status_code}, type={r_route.headers.get('Content-Type')}, body={r_route.text[:500]}")
            return jsonify({
                'error': 'Failed to fetch route from Traccar', 
                'upstream_status': r_route.status_code, 
                'upstream_body': r_route.text[:500]
            }), r_route.status_code
            
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"Route API Critical Exception: {e}\n{tb}")
        return jsonify({'error': str(e)}), 500