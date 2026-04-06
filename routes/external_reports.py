from flask import Blueprint, request, jsonify
from services.external_report_service import get_vehicle_summary_report
import functools

external_reports_bp = Blueprint('external_reports', __name__)

import os

# STATIC TOKEN FOR ODOO INTEGRATION (Env var or fallback)
ODOO_REPORT_STATIC_TOKEN = os.environ.get("ODOO_REPORT_TOKEN", "ivms_odoo_secure_token_2024")

def token_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"status": "error", "message": "Missing Authorization Header"}), 401
        
        try:
            # Expecting "Bearer <token>"
            token_type, token = auth_header.split(None, 1)
            if token_type.lower() != 'bearer' or token != ODOO_REPORT_STATIC_TOKEN:
                return jsonify({"status": "error", "message": "Invalid Token"}), 403
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid Authorization Header Format"}), 401
            
        return f(*args, **kwargs)
    return decorated

@external_reports_bp.route("/api/v1/reports/vehicle-summary", methods=['GET'])
@token_required
def vehicle_summary():
    vehicle_id = request.args.get('vehicle_id')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    if not all([vehicle_id, from_date, to_date]):
        return jsonify({
            "status": "error",
            "message": "Missing mandatory parameters: vehicle_id, from_date, to_date"
        }), 400

    # Basic date validation
    try:
        from datetime import datetime
        datetime.strptime(from_date, '%Y-%m-%d')
        datetime.strptime(to_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Invalid date format. Use YYYY-MM-DD."
        }), 400

    data, error = get_vehicle_summary_report(vehicle_id, from_date, to_date)
    
    if error:
        return jsonify({
            "status": "error",
            "message": error
        }), 404 if "not found" in error.lower() else 500

    return jsonify({
        "status": "success",
        "data": data
    })

@external_reports_bp.route("/api/v1/vehicles", methods=['GET'])
@token_required
def list_external_vehicles():
    """
    Returns the list of active vehicles for report discovery.
    Fulfills the 'black box' requirement for external automation.
    """
    from models.database import load_vehicles
    vehicles = load_vehicles()
    
    # Return active vehicles only
    active_vehicles = [
        {
            "vehicle_id": v.get("unique_id"),
            "name": v.get("name"),
            "company": v.get("company_name"),
            "status": v.get("status")
        }
        for v in vehicles if v.get("status") == "active"
    ]
    
    return jsonify({
        "status": "success",
        "data": active_vehicles
    })
