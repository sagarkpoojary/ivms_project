import json
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
def api_events():
    if not session.get("logged_in"): return safe_jsonify([]), 401
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        
        allowed_vehicles = get_filtered_vehicles()
        allowed_imeis = [str(v.get('unique_id')) for v in allowed_vehicles]
        
        # Native events
        events = native_report_service.get_analytics_events(None, 'all', start_dt, end_dt, allowed_imeis)
        return safe_jsonify(events)
    except Exception as e:
        return safe_jsonify([]), 200

@api_bp.route("/api/alerts")
def api_alerts():
    if not session.get("logged_in"): return safe_jsonify([]), 401
    try:
        from services.report_service import get_period_dates
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates('Today')
        
        allowed_vehicles = get_filtered_vehicles()
        allowed_imeis = [str(v.get('unique_id')) for v in allowed_vehicles]
        
        # Fetch overspeed events from native analytics
        events = native_report_service.get_analytics_events(None, 'overspeed', start_dt, end_dt, allowed_imeis)
        if not isinstance(events, list): return jsonify([])
        return safe_jsonify(events)
    except Exception as e:
        return safe_jsonify([])

@api_bp.route("/api/system-stats")
@role_required('main_admin')
def api_system_stats():
    from models.database import get_system_stats
    return safe_jsonify(get_system_stats())

@api_bp.route('/api/devices')
@role_required('user')
def api_devices():
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
            "driver_name": live.get('driver_name') if live else None,
            "driver_id": live.get('driver_id') if live else None,
            "position": {
                "latitude": live.get('latitude') if live else None,
                "longitude": live.get('longitude') if live else None,
                "speed": live.get('speed', 0) if live else 0,
                "course": live.get('angle', 0) if live else 0,
                "attributes": {
                    "ignition": live.get('ignition', False) if live else False,
                    "bat_v": live.get('bat_v', 0) if live else 0,
                    "rfid": live.get('rfid') if live else None
                }
            } if live else None
        }
        results.append(device_data)
        
    return safe_jsonify(results)

@api_bp.route('/server-settings', methods=['GET', 'POST'])
@role_required('main_admin')
def server_settings():
    cfg = load_server_config()
    if request.method == 'POST':
        new_threshold = request.form.get('stop_threshold', '5').strip()

        if new_threshold.isdigit():
            cfg["stop_threshold"] = int(new_threshold)

        save_server_config(cfg)
        return redirect(url_for('api.server_settings'))
    return render_template('server_settings.html', config=cfg)

@api_bp.route("/api/device-models")
def device_models():
    """Returns supported device models list from local config."""
    from pathlib import Path
    import json
    try:
        data_path = Path(BASE_DIR) / 'static' / 'data' / 'device_models.json'
        if data_path.exists():
            with open(data_path, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({"models": ["Teltonika FMC130", "Teltonika FMB120", "Teltonika FMB920"]})
    except Exception as e: return jsonify({"error": str(e)}), 500

@api_bp.route('/api/dashboard/devices')
@role_required('user')
def api_dashboard_devices():
    from auth.utils import get_filtered_vehicles
    return safe_jsonify(get_filtered_vehicles())

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
    
    allowed_vehicles = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(device_uid) for v in allowed_vehicles):
        return jsonify({'error': 'access_denied'}), 403
        
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
            "driver_name": live.get('driver_name') if live else None,
            "driver_id": live.get('driver_id') if live else None,
            "position": {
                "latitude": live.get('latitude') if live else None,
                "longitude": live.get('longitude') if live else None,
                "speed": live.get('speed', 0) if live else 0,
                "course": live.get('angle', 0) if live else 0,
                "deviceTime": live.get('timestamp') if live else None,
                "attributes": {
                    "ignition": live.get('ignition', False) if live else False,
                    "gsm": live.get('gsm', 0) if live else 0,
                    "rfid": live.get('rfid') if live else None
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
    from services.native_report_service import native_report_service
    
    uid = request.args.get('vehicle_id')
    from_date = request.args.get('start_date')
    to_date = request.args.get('end_date')
    
    allowed_vehicles = get_filtered_vehicles()
    if uid and not any(str(v.get('unique_id')) == str(uid) for v in allowed_vehicles):
         return jsonify({'error': 'access_denied'}), 403
    
    # Date range parsed natively
    start_dt, end_dt = get_period_dates('Custom', from_date, to_date)
    
    results = []
    try:
        # Native Idle
        events = native_report_service.get_analytics_events(uid, 'idle', start_dt, end_dt, [str(v.get('unique_id')) for v in allowed_vehicles] if not uid else None)
        
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
    
    allowed_vehicles = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(device_id) for v in allowed_vehicles):
         return jsonify({'error': 'access_denied'}), 403

    from_p = request.args.get('from')
    to_p = request.args.get('to')
    if not from_p or not to_p: return jsonify({'error': 'missing_range'}), 400
    
    result = {'trips': [], 'events': [], 'stops': []}
    try:
        from services.native_report_service import native_report_service
        start_dt = datetime.fromisoformat(from_p.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_p.replace('Z', '+00:00'))
        
        # Fetch data natively
        result['trips'] = native_report_service.get_trip_report(device_id, start_dt, end_dt)
        result['events'] = native_report_service.get_analytics_events(device_id, 'all', start_dt, end_dt)
        result['stops'] = native_report_service.get_analytics_events(device_id, 'idle', start_dt, end_dt)
        return safe_jsonify(result)
    except Exception as e:
        current_app.logger.exception("Combined Report Error")
        return safe_jsonify({'trips': [], 'events': [], 'stops': [], 'error': str(e)})

@api_bp.route('/api/debug/device/<uid>')
@role_required('admin')
def debug_device(uid):
    """Native debugging for a device."""
    from services.telemetry_service import telemetry_service
    live = telemetry_service.get_live_status(uid)
    return jsonify({
        'uid': uid, 
        'source': 'native_redis',
        'live_status': live,
        'timestamp': datetime.now().isoformat()
    })


@api_bp.route('/api/v2/reports/history/<imei>')
@role_required('user')
def api_history_report(imei):
    allowed_vehicles = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(imei) for v in allowed_vehicles):
         return jsonify({'error': 'access_denied'}), 403

    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return safe_jsonify({'error': 'Missing range'}), 400
    
    try:
        from services.native_report_service import native_report_service
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        
        records = native_report_service.get_playback_data(imei, start_dt, end_dt, limit=2000)
        return safe_jsonify([{
            'latitude': r['latitude'],
            'longitude': r['longitude'],
            'speed': r['speed'],
            'timestamp': r['timestamp']
        } for r in records])
    except Exception as e:
        return safe_jsonify({'error': str(e)}), 500

@api_bp.route('/api/reports/route')
@role_required('user')
def api_report_route():
    unique_id = request.args.get('unique_id')
    from_p = request.args.get('from')
    to_p = request.args.get('to')
    
    if not unique_id or not from_p or not to_p:
        return jsonify({'error': 'Missing parameters'}), 400

    allowed_vehicles = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(unique_id) for v in allowed_vehicles):
         return jsonify({'error': 'access_denied'}), 403

    try:
        from services.native_report_service import native_report_service
        start_dt = datetime.fromisoformat(from_p.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_p.replace('Z', '+00:00'))
        
        records = native_report_service.get_playback_data(unique_id, start_dt, end_dt)
        
        native_records = []
        for r in records:
            native_records.append({
                "deviceId": r['imei'],
                "fixTime": r['timestamp'],
                "latitude": r['latitude'],
                "longitude": r['longitude'],
                "speed": r['speed'],
                "course": r['angle'],
                "attributes": json.loads(r['io_elements']) if isinstance(r['io_elements'], str) else r['io_elements']
            })
        return safe_jsonify(native_records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@api_bp.route('/api/reports/driver-attendance')
@role_required('user')
def api_driver_attendance():
    from services.report_service import get_period_dates
    from services.native_report_service import native_report_service
    
    period = request.args.get('period', 'Today')
    start_dt, end_dt = get_period_dates(period)
    
    allowed_vehicles = get_filtered_vehicles()
    allowed_imeis = [str(v.get('unique_id')) for v in allowed_vehicles]
    
    data = native_report_service.get_driver_attendance(start_dt, end_dt, allowed_imeis)
    return safe_jsonify(data)

@api_bp.route('/api/reports/rfid-timeline')
@role_required('user')
def api_rfid_timeline():
    from services.report_service import get_period_dates
    from services.native_report_service import native_report_service
    
    imei = request.args.get('imei')
    period = request.args.get('period', 'Today')
    start_dt, end_dt = get_period_dates(period)
    
    allowed_vehicles = get_filtered_vehicles()
    allowed_imeis = [str(v.get('unique_id')) for v in allowed_vehicles]
    
    if imei and imei not in allowed_imeis:
         return jsonify({'error': 'access_denied'}), 403

    data = native_report_service.get_rfid_timeline(imei, start_dt, end_dt, allowed_imeis)
    return safe_jsonify(data)
