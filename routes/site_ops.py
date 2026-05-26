import logging
from flask import Blueprint, render_template, session, request, jsonify
from auth.utils import role_required
from services.site_ops_service import (
    get_sites,
    create_site,
    update_site,
    delete_site,
    get_site_visits,
    create_site_visit,
    get_service_tickets,
    create_service_ticket,
    update_service_ticket_status,
    get_site_ops_kpis
)

logger = logging.getLogger(__name__)

site_ops_bp = Blueprint('site_ops', __name__)

def get_tenant_id():
    """
    Utility helper to resolve tenant ID based on role permissions.
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

@site_ops_bp.route('/sites')
@role_required('user')
def site_registry():
    return render_template('site_ops/sites.html')

@site_ops_bp.route('/site-visits')
@role_required('user')
def site_visits():
    return render_template('site_ops/visits.html')

@site_ops_bp.route('/service-tickets')
@role_required('user')
def service_tickets():
    return render_template('site_ops/tickets.html')

# ---------------------------------------------------------------------------
# Site Registry API Endpoints
# ---------------------------------------------------------------------------

@site_ops_bp.route('/api/sites', methods=['GET'])
@site_ops_bp.route('/api/v2/ops/sites', methods=['GET'])
@role_required('user')
def api_get_sites():
    tenant_id = get_tenant_id()
    sites = get_sites(tenant_id)
    
    # Map for frontend: templates/site_ops/sites.html expects site_id
    # We will map 'address' as site_id
    mapped = []
    for s in sites:
        mapped.append({
            "id": s["id"],
            "site_id": s["address"] or f"SITE-{s['id']}",
            "name": s["name"],
            "address": s["address"],
            "latitude": float(s["latitude"]) if s["latitude"] else 0.0,
            "longitude": float(s["longitude"]) if s["longitude"] else 0.0,
            "contact_person": s["contact_person"],
            "contact_phone": s["contact_phone"]
        })
    return jsonify(mapped)

@site_ops_bp.route('/api/sites', methods=['POST'])
@site_ops_bp.route('/api/v2/ops/sites', methods=['POST'])
@role_required('admin')
def api_create_site():
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    if not data or not data.get('name'):
        return jsonify({"error": "Missing Site Name"}), 400

    # Map frontend 'site_id' to address
    if 'site_id' in data and not data.get('address'):
        data['address'] = data['site_id']

    success = create_site(tenant_id, data)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to register Site"}), 500

@site_ops_bp.route('/api/sites/<int:site_id>', methods=['PUT'])
@role_required('admin')
def api_update_site(site_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    success = update_site(tenant_id, site_id, data)
    if success:
        return jsonify({"success": True}), 200
    return jsonify({"error": "Failed to update Site"}), 500

@site_ops_bp.route('/api/sites/<int:site_id>', methods=['DELETE'])
@role_required('admin')
def api_delete_site(site_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    success = delete_site(tenant_id, site_id)
    if success:
        return jsonify({"success": True}), 200
    return jsonify({"error": "Failed to remove Site"}), 500

# ---------------------------------------------------------------------------
# Site Visits API Endpoints
# ---------------------------------------------------------------------------

@site_ops_bp.route('/api/site-visits', methods=['GET'])
@site_ops_bp.route('/api/v2/ops/site-visits', methods=['GET'])
@role_required('user')
def api_get_visits():
    tenant_id = get_tenant_id()
    visits = get_site_visits(tenant_id)
    
    # Map for frontend: templates/site_ops/visits.html expects:
    # vehicle_name, site_name, arrival_time, departure_time, duration_minutes
    mapped = []
    for v in visits:
        dur = None
        if v["arrival_time"] and v["departure_time"]:
            dur = round((v["departure_time"] - v["arrival_time"]).total_seconds() / 60.0)
            
        mapped.append({
            "id": v["id"],
            "vehicle_name": v["vehicle_id"] or v["imei"] or "N/A",
            "imei": v["imei"],
            "site_name": v["site_name"] or f"Site {v['site_id']}",
            "arrival_time": v["arrival_time"].isoformat() if v["arrival_time"] else None,
            "departure_time": v["departure_time"].isoformat() if v["departure_time"] else None,
            "duration_minutes": dur
        })
    return jsonify(mapped)

@site_ops_bp.route('/api/site-visits', methods=['POST'])
@role_required('admin')
def api_create_visit():
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    if not data or not data.get('site_id'):
        return jsonify({"error": "Missing Site ID"}), 400

    success = create_site_visit(tenant_id, data)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to schedule Site Visit"}), 500

# ---------------------------------------------------------------------------
# Service Tickets API Endpoints
# ---------------------------------------------------------------------------

@site_ops_bp.route('/api/service-tickets', methods=['GET'])
@site_ops_bp.route('/api/v2/ops/service-tickets', methods=['GET'])
@role_required('user')
def api_get_tickets():
    tenant_id = get_tenant_id()
    tickets = get_service_tickets(tenant_id)
    
    # Map for frontend: templates/site_ops/tickets.html expects:
    # id, vehicle_name, imei, issue_type, priority, status, created_at
    mapped = []
    for t in tickets:
        mapped.append({
            "id": t["id"],
            "vehicle_name": t["customer_name"] or "N/A",
            "imei": t["customer_phone"] or "N/A",
            "issue_type": t["category"] or "Service Request",
            "priority": t["priority"] or "Low",
            "status": t["status"] or "open",
            "created_at": t["created_at"].isoformat() if t["created_at"] else None
        })
    return jsonify(mapped)

@site_ops_bp.route('/api/service-tickets', methods=['POST'])
@site_ops_bp.route('/api/v2/ops/service-tickets', methods=['POST'])
@role_required('user')
def api_create_ticket():
    tenant_id = get_tenant_id()
    data = request.get_json(force=True)
    
    # Map inputs from newTicketForm: imei, issue_type, priority, description
    if not data or not data.get('imei'):
        return jsonify({"error": "Missing IMEI / Vehicle selection"}), 400

    # Resolve vehicle name for customer_name
    from models.database import get_vehicle_by_uid
    v = get_vehicle_by_uid(data['imei'])
    v_name = v.get('name') if v else "Vehicle"
    
    ticket_payload = {
        "title": f"Issue: {data.get('issue_type', 'Hardware')}",
        "category": data.get('issue_type', 'Hardware Malfunction'),
        "priority": data.get('priority', 'Medium'),
        "description": data.get('description') or '',
        "customer_name": v_name,
        "customer_phone": data['imei']
    }

    success = create_service_ticket(tenant_id, ticket_payload)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to create Service Ticket"}), 500

@site_ops_bp.route('/api/service-tickets/status/<int:ticket_id>', methods=['POST'])
@role_required('admin')
def api_update_ticket_status(ticket_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    status = data.get('status')
    notes = data.get('notes')
    if not status:
        return jsonify({"error": "Missing status value"}), 400

    success = update_service_ticket_status(tenant_id, ticket_id, status, notes=notes)
    if success:
        return jsonify({"success": True}), 200
    return jsonify({"error": "Failed to update Service Ticket"}), 500

# ---------------------------------------------------------------------------
# Site Operations KPIs Endpoints
# ---------------------------------------------------------------------------

@site_ops_bp.route('/api/site-ops/kpis', methods=['GET'])
@role_required('user')
def api_get_site_ops_kpis():
    tenant_id = get_tenant_id()
    kpis = get_site_ops_kpis(tenant_id)
    return jsonify(kpis)
