import os
import json
import requests
from datetime import datetime, timedelta
import pytz
from services.time_service import get_oman_now
from flask import Blueprint, request, jsonify, session, current_app, render_template, redirect, url_for
from auth.utils import role_required, get_filtered_vehicles
from models.database import load_server_config, save_server_config
from extensions import cache
from config import Config, BASE_DIR
from services.telemetry_service import telemetry_service

api_bp = Blueprint('api', __name__)

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, timedelta)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))

def safe_jsonify(data):
    return current_app.response_class(
        json.dumps(data, default=json_serial),
        mimetype='application/json'
    )

@api_bp.route("/api/events")
def proxy_events():
    if not session.get("logged_in"): return jsonify([]), 401
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        
        # Native events
        events = native_report_service.get_analytics_events(None, 'all', start_dt, end_dt)
        return safe_jsonify(events)
    except Exception as e:
        return jsonify([]), 200 # Return empty instead of 500 for UI stability

@api_bp.route("/api/alerts")
def api_alerts():
    if not session.get("logged_in"): return jsonify([]), 401
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        
        # Fetch overspeed events from native analytics
        events = native_report_service.get_analytics_events(None, 'overspeed', start_dt, end_dt)
        if not isinstance(events, list): return jsonify([])
        return safe_jsonify(events)
    except Exception as e:
        return jsonify([])

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
    from auth.utils import get_filtered_vehicles
    return jsonify(get_filtered_vehicles())

@api_bp.route('/api/dashboard/groups')
@role_required('user')
def api_dashboard_groups():
    # Native groups logic (if any) or just return empty for now
    return jsonify([])

@api_bp.route('/api/dashboard/distance')
@role_required('user')
def api_dashboard_distance():
    device_uid = request.args.get('id')
    if not device_uid: return jsonify({'error': 'missing_id'}), 400
    
    from services.report_service import get_period_dates
    from services.native_report_service import native_report_service
    start_dt, end_dt = get_period_dates('Today')
    
    summary = native_report_service.get_fleet_summary([{'unique_id': device_uid}], start_dt, end_dt)
    if summary:
        return jsonify({'distance': summary[0]['total_distance']})
    return jsonify({'distance': 0})

@api_bp.route('/api/dashboard/bulk-sync')
@role_required('user')
def api_dashboard_bulk_sync():
    period = request.args.get('period', 'Today')
    device_uid = request.args.get('uid')
    
    from services.report_service import get_period_dates
    from services.native_report_service import native_report_service
    start_dt, end_dt = get_period_dates(period)
    
    allowed_vehicles = get_filtered_vehicles()
    if device_uid:
        allowed_vehicles = [v for v in allowed_vehicles if str(v.get('unique_id')) == str(device_uid)]

    # Fetch live status from Redis and aggregates from DB
    devices = []
    summaries = {}
    
    for v in allowed_vehicles:
        imei = str(v.get('unique_id'))
        live = telemetry_service.get_live_status(imei)
        
        device_data = {
            "id": imei,
            "uniqueId": imei,
            "name": v.get('name'),
            "status": live.get('status', 'offline') if live else 'offline',
            "position": {
                "latitude": live.get('latitude') if live else None,
                "longitude": live.get('longitude') if live else None,
                "speed": live.get('speed', 0) if live else 0,
                "course": live.get('angle', 0) if live else 0,
                "deviceTime": live.get('timestamp') if live else None,
                "attributes": {
                    "ignition": live.get('ignition', False) if live else False,
                    "gsm": live.get('gsm', 0) if live else 0
                }
            } if live else None
        }
        devices.append(device_data)
        
        # Summaries for cards
        # In a real high-scale scenario, we'd batch this. For now, call the service.
        summary_list = native_report_service.get_fleet_summary([v], start_dt, end_dt)
        if summary_list:
            s = summary_list[0]
            summaries[imei] = {
                'distance': s['total_distance'],
                'engineHours': round(s['total_duration'] / 3600, 1),
                'fuelLiters': s['fuel_liters'],
                'fuelCost': round(s['fuel_liters'] * Config.FUEL_PRICE_OMR, 3)
            }

    return safe_jsonify({
        'devices': devices,
        'summaries': summaries,
        'period': period
    })

@api_bp.route('/api/reports/idle')
@role_required('user')
def api_idle_report():
    from services.report_service import get_period_dates
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
    
    results = []
    
    try:
        from services.native_report_service import native_report_service
        from services.report_service import get_period_dates
        
        start_dt, end_dt = get_period_dates('Custom', from_date, to_date)
        
        # Native Idle
        events = native_report_service.get_analytics_events(uid, 'idle', start_dt, end_dt)
        
        results.append({
            'vehicle_id': uid,
            'vehicle_name': uid, # Fallback
            'total_idle_time': sum(e['value'] for e in events),
            'total_idle_events': len(events),
            'idle_events': events
        })
    except Exception as e:
        current_app.logger.exception("Idle Report Error")
    
    return safe_jsonify(results)

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
        from services.native_report_service import native_report_service
        from services.report_service import get_period_dates
        
        start_dt = datetime.fromisoformat(from_p.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_p.replace('Z', '+00:00'))
        
        # Fetch data natively
        result['trips'] = native_report_service.get_trip_report(device_id, start_dt, end_dt)
        result['events'] = native_report_service.get_analytics_events(device_id, 'all', start_dt, end_dt)
        # Stops are approximated as idle events for now
        result['stops'] = native_report_service.get_analytics_events(device_id, 'idle', start_dt, end_dt)
        
        return safe_jsonify(result)
    except Exception as e:
        current_app.logger.exception("Combined Report Error")
        return safe_jsonify({'trips': [], 'events': [], 'stops': [], 'error': str(e)})

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


@api_bp.route('/api/v2/reports/history/<imei>')
@role_required('user')
def api_history_report(imei):
    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({'error': 'Missing range'}), 400
    
    try:
        from services.native_report_service import native_report_service
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        
        # Native playback data
        records = native_report_service.get_playback_data(imei, start_dt, end_dt, limit=2000)
        
        return safe_jsonify([{
            'latitude': r['latitude'],
            'longitude': r['longitude'],
            'speed': r['speed'],
            'timestamp': r['timestamp']
        } for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/reports/route')
@role_required('user')
def api_report_route():
    unique_id = request.args.get('unique_id')
    from_p = request.args.get('from')
    to_p = request.args.get('to')
    
    if not unique_id or not from_p or not to_p:
        return jsonify({'error': 'Missing parameters'}), 400

    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        
        # Parse ISO strings to Oman datetime
        start_dt = datetime.fromisoformat(from_p.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_p.replace('Z', '+00:00'))
        
        records = native_report_service.get_playback_data(unique_id, start_dt, end_dt)
        
        # Transform to Traccar-compatible format for the frontend JS
        traccar_records = []
        for r in records:
            traccar_records.append({
                "deviceId": r['imei'],
                "fixTime": r['timestamp'],
                "latitude": r['latitude'],
                "longitude": r['longitude'],
                "speed": r['speed'],
                "course": r['angle'],
                "attributes": json.loads(r['io_elements']) if isinstance(r['io_elements'], str) else r['io_elements']
            })
        
        return safe_jsonify(traccar_records)
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500