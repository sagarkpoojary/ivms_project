import logging
from flask import Blueprint, render_template, session, request, jsonify, make_response
from auth.utils import role_required
from services.driver_service import (
    get_drivers,
    create_driver,
    update_driver,
    delete_driver,
    get_rfid_tags,
    create_rfid_tag,
    get_driver_attendance,
    get_driver_sessions,
    generate_drivers_csv
)

logger = logging.getLogger(__name__)

drivers_bp = Blueprint('drivers', __name__)

def get_tenant_id():
    """
    Helper to resolve user tenant ID from Flask session details.
    """
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin':
        tenant_id = None
    return tenant_id

# ---------------------------------------------------------------------------
# UI Page Routes
# ---------------------------------------------------------------------------

@drivers_bp.route('/drivers')
@role_required('user')
def driver_registry():
    return render_template('drivers/registry.html')

@drivers_bp.route('/rfid-assignments')
@role_required('user')
def rfid_assignments():
    return render_template('drivers/rfid_assignments.html')

@drivers_bp.route('/driver-attendance')
@role_required('user')
def driver_attendance():
    return render_template('drivers/attendance.html')

@drivers_bp.route('/driver-sessions')
@role_required('user')
def driver_sessions():
    return render_template('drivers/sessions.html')

# ---------------------------------------------------------------------------
# API CRUD Endpoints (Aligned with both original & frontend v2 URLs)
# ---------------------------------------------------------------------------

@drivers_bp.route('/api/drivers', methods=['GET'])
@drivers_bp.route('/api/v2/ops/drivers', methods=['GET'])
@role_required('user')
def api_get_drivers():
    tenant_id = get_tenant_id()
    search = request.args.get('search')
    status = request.args.get('status')
    drivers = get_drivers(tenant_id, search_query=search, status=status)
    return jsonify(drivers)

@drivers_bp.route('/api/drivers', methods=['POST'])
@drivers_bp.route('/api/v2/ops/drivers', methods=['POST'])
@role_required('admin')
def api_create_driver():
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    if not data or not data.get('name'):
        return jsonify({"error": "Missing driver name"}), 400

    success = create_driver(tenant_id, data)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to register driver"}), 500

@drivers_bp.route('/api/drivers/<driver_id>', methods=['PUT'])
@role_required('admin')
def api_update_driver(driver_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    success = update_driver(tenant_id, driver_id, data)
    if success:
        return jsonify({"success": True}), 200
    return jsonify({"error": "Failed to update driver details"}), 500

@drivers_bp.route('/api/drivers/<driver_id>', methods=['DELETE'])
@role_required('admin')
def api_delete_driver(driver_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    success = delete_driver(tenant_id, driver_id)
    if success:
        return jsonify({"success": True}), 200
    return jsonify({"error": "Failed to remove driver"}), 500

# ---------------------------------------------------------------------------
# RFID Management Endpoints
# ---------------------------------------------------------------------------

@drivers_bp.route('/api/rfid-tags', methods=['GET'])
@role_required('user')
def api_get_rfid_tags():
    tenant_id = get_tenant_id()
    tags = get_rfid_tags(tenant_id)
    return jsonify(tags)

@drivers_bp.route('/api/rfid-tags', methods=['POST'])
@role_required('admin')
def api_create_rfid_tag():
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    tag_id = data.get('tag_id')
    if not tag_id:
        return jsonify({"error": "Missing Tag ID"}), 400
        
    success = create_rfid_tag(tenant_id, tag_id)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to register RFID tag"}), 500

# ---------------------------------------------------------------------------
# Attendance & Sessions Endpoints (Aligned with v2 URLs)
# ---------------------------------------------------------------------------

@drivers_bp.route('/api/driver-attendance', methods=['GET'])
@drivers_bp.route('/api/v2/ops/driver-attendance', methods=['GET'])
@role_required('user')
def api_get_attendance():
    tenant_id = get_tenant_id()
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    
    # Map the custom parameters if present
    records = get_driver_attendance(tenant_id, start_date=start, end_date=end)
    
    # For UI compatibility with templates/drivers/attendance.html:
    # Expects login_time, logout_time, driver_name, driver_id, vehicle_name
    # Since our database fields are first_checkin and last_checkout, let's map them
    mapped = []
    for r in records:
        mapped.append({
            "id": r["id"],
            "driver_id": r["driver_id"],
            "driver_name": r["driver_name"],
            "vehicle_name": r.get("vehicle_name", "N/A"),
            "login_time": r["first_checkin"].isoformat() if r["first_checkin"] else None,
            "logout_time": r["last_checkout"].isoformat() if r["last_checkout"] else None,
            "total_hours": float(r["total_hours"] or 0.0)
        })
    return jsonify(mapped)

@drivers_bp.route('/api/driver-sessions', methods=['GET'])
@drivers_bp.route('/api/v2/ops/rfid-timeline', methods=['GET'])
@role_required('user')
def api_get_sessions():
    tenant_id = get_tenant_id()
    sessions = get_driver_sessions(tenant_id)
    
    # sessions.html expects: timestamp, driver_name, driver_id, imei, event_type, latitude, longitude
    # Let's map our session records
    mapped = []
    for s in sessions:
        # Default fallback values for coordinates
        mapped.append({
            "timestamp": s["login_time"].isoformat() if s["login_time"] else s["created_at"].isoformat(),
            "driver_id": s["driver_id"],
            "driver_name": s["driver_name"],
            "imei": s["imei"],
            "event_type": "login" if s["ignition_state"] else "logout",
            "latitude": 23.58,  # system fallback center
            "longitude": 58.4
        })
    return jsonify(mapped)

# ---------------------------------------------------------------------------
# CSV Exporter Endpoints
# ---------------------------------------------------------------------------

@drivers_bp.route('/api/drivers/export', methods=['GET'])
@role_required('user')
def api_export_drivers():
    tenant_id = get_tenant_id()
    csv_data = generate_drivers_csv(tenant_id)
    
    response = make_response(csv_data)
    response.headers['Content-Disposition'] = 'attachment; filename=drivers_export.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response
