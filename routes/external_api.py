from flask import Blueprint, request, jsonify
from middleware.api_auth import api_token_required
from services.external_api_service import (
    get_filtered_fleet, fetch_vehicle_summary, fetch_live_status,
    fetch_trips, fetch_fuel_summary, fetch_dashboard_summary
)
from serializers.odoo_serializer import (
    serialize_vehicle_summary, serialize_live_status,
    serialize_trips, serialize_fuel_summary
)
from services.time_service import SYSTEM_TZ, get_period_dates
from datetime import datetime

external_api_bp = Blueprint('external_api', __name__)

def parse_date_range(default_period='Today'):
    """
    Utility to parse from_date and to_date query parameters into localized system datetimes.
    Supports YYYY-MM-DD boundaries or falls back to preset periods.
    """
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    
    if from_date and to_date:
        try:
            # Parse daily start boundary (00:00:00)
            start_dt = datetime.strptime(from_date, '%Y-%m-%d')
            start_dt = SYSTEM_TZ.localize(start_dt.replace(hour=0, minute=0, second=0, microsecond=0))
            
            # Parse daily end boundary (23:59:59)
            end_dt = datetime.strptime(to_date, '%Y-%m-%d')
            end_dt = SYSTEM_TZ.localize(end_dt.replace(hour=23, minute=59, second=59, microsecond=999999))
            
            return start_dt, end_dt, None
        except ValueError:
            return None, None, "Invalid date format. Use YYYY-MM-DD."
            
    # Fallback to period helper
    start_dt, end_dt = get_period_dates(default_period)
    return start_dt, end_dt, None

@external_api_bp.route('/api/v1/reports/fleet-summary', methods=['GET'])
@api_token_required
def vehicle_summary():
    company_id = request.args.get('company_id')
    device_id = request.args.get('device_id')
    compatibility = request.args.get('compatibility')
    
    start_dt, end_dt, error = parse_date_range()
    if error:
        return jsonify({"status": "error", "message": error}), 400
        
    vehicles = get_filtered_fleet(company_id=company_id, device_id=device_id)
    if device_id and not vehicles:
        return jsonify({"status": "error", "message": f"Vehicle with device_id {device_id} not found."}), 404
        
    data = fetch_vehicle_summary(vehicles, start_dt, end_dt)
    serialized = serialize_vehicle_summary(data, compatibility)
    return jsonify(serialized)

@external_api_bp.route('/api/v1/reports/live-status', methods=['GET'])
@api_token_required
def live_status():
    company_id = request.args.get('company_id')
    device_id = request.args.get('device_id')
    compatibility = request.args.get('compatibility')
    
    vehicles = get_filtered_fleet(company_id=company_id, device_id=device_id)
    if device_id and not vehicles:
        return jsonify({"status": "error", "message": f"Vehicle with device_id {device_id} not found."}), 404
        
    data = fetch_live_status(vehicles)
    serialized = serialize_live_status(data, compatibility)
    return jsonify(serialized)

@external_api_bp.route('/api/v1/reports/trips', methods=['GET'])
@api_token_required
def trips():
    device_id = request.args.get('device_id')
    compatibility = request.args.get('compatibility')
    
    if not device_id:
        return jsonify({"status": "error", "message": "Missing mandatory parameter: device_id"}), 400
        
    start_dt, end_dt, error = parse_date_range()
    if error:
        return jsonify({"status": "error", "message": error}), 400
        
    vehicles = get_filtered_fleet(device_id=device_id)
    if not vehicles:
        return jsonify({"status": "error", "message": f"Vehicle with device_id {device_id} not found."}), 404
        
    data = fetch_trips(device_id, start_dt, end_dt)
    serialized = serialize_trips(data, compatibility)
    return jsonify(serialized)

@external_api_bp.route('/api/v1/reports/fuel-summary', methods=['GET'])
@api_token_required
def fuel_summary():
    company_id = request.args.get('company_id')
    device_id = request.args.get('device_id')
    compatibility = request.args.get('compatibility')
    
    start_dt, end_dt, error = parse_date_range()
    if error:
        return jsonify({"status": "error", "message": error}), 400
        
    vehicles = get_filtered_fleet(company_id=company_id, device_id=device_id)
    if device_id and not vehicles:
        return jsonify({"status": "error", "message": f"Vehicle with device_id {device_id} not found."}), 404
        
    data = fetch_fuel_summary(vehicles, start_dt, end_dt)
    serialized = serialize_fuel_summary(data, compatibility)
    return jsonify(serialized)

@external_api_bp.route('/api/v1/dashboard/summary', methods=['GET'])
@api_token_required
def dashboard_summary():
    company_id = request.args.get('company_id')
    device_id = request.args.get('device_id')
    
    start_dt, end_dt, error = parse_date_range()
    if error:
        return jsonify({"status": "error", "message": error}), 400
        
    vehicles = get_filtered_fleet(company_id=company_id, device_id=device_id)
    data = fetch_dashboard_summary(vehicles, start_dt, end_dt)
    return jsonify(data)
