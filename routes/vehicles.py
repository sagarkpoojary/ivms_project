import requests
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session
from auth.utils import role_required, get_filtered_vehicles, get_current_user_data
from models.database import load_vehicles, add_vehicle_db, delete_vehicle_db, update_vehicle_db
from services.traccar_service import try_traccar_get
from services.limit_validator import validate_vehicle_registration_limit, validate_draft_approval_limit, get_usage_stats

vehicles_bp = Blueprint('vehicles', __name__)

@vehicles_bp.route('/vehicle/add', methods=['GET'])
@role_required('admin')
def vehicle_form():
    user_info, current_data = get_current_user_data()
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    current_email = session.get('email')
    usage = get_usage_stats(current_email)
    
    vehicles = get_filtered_vehicles(include_all=True)
    company_summary = []
    if current_data['role'] == 'main_admin':
        summary_map = {}
        for v in vehicles:
            c = v.get('company_name', 'N/A')
            if c not in summary_map:
                summary_map[c] = {'name': c, 'total': 0, 'active': 0, 'draft': 0, 'declined': 0}
            summary_map[c]['total'] += 1
            status = v.get('status', 'draft')
            if status in summary_map[c]:
                summary_map[c][status] += 1
        company_summary = list(summary_map.values())

    return render_template('vehicle_form.html', 
                           vehicles=vehicles,
                           company_summary=company_summary,
                           role=current_data['role'],
                           usage=usage)

@vehicles_bp.route('/vehicle/add', methods=['POST'])
@role_required('admin')
def register_vehicle():
    user_info, current_data = get_current_user_data()
    role = current_data.get('role')
    
    name = request.form.get('name', '').strip()
    unique_id = request.form.get('unique_id', '').strip()
    device_model = request.form.get('device_model', '').strip()
    driver_name = request.form.get('driver_name', '').strip()

    if not name or not unique_id:
        return render_template('vehicle_form.html', error="Please enter Name and Unique ID.", vehicles=get_filtered_vehicles(), role=role)

    current = load_vehicles()
    existing = next((v for v in current if str(v.get('unique_id')) == unique_id), None)
    if existing:
        if existing.get('status') == 'declined':
             # Allow re-submission of declined vehicles
             delete_vehicle_db(unique_id)
        else:
             return render_template('vehicle_form.html', error="Vehicle already registered or pending!", vehicles=get_filtered_vehicles(include_all=True), role=role)

    v_parent = session.get('parent_email') if role == 'user' else session.get('email')

    # Backend enforcement of vehicle limits
    current_email = session.get('email')
    can_register, current_count, limit_error = validate_vehicle_registration_limit(
        current_email, 
        role, 
        current_data.get('vehicle_limit')
    )
    
    if not can_register:
        usage = get_usage_stats(current_email)
        return render_template('vehicle_form.html', 
                               error=limit_error, 
                               vehicles=get_filtered_vehicles(include_all=True), 
                               role=role,
                               usage=usage)

    # DRAFT LOGIC for Company Admin ('admin' role)
    # They can submit details even if the device isn't in Traccar yet.
    if role == 'admin':
        new_vehicle = {
            "name": name, 
            "unique_id": unique_id, 
            "device_model": device_model,
            "driver_name": driver_name,
            "parent_email": v_parent,
            "company_name": current_data.get('company_name'),
            "status": "draft",
            "created_at": str(datetime.now())
        }
        add_vehicle_db(new_vehicle)
        return render_template('vehicle_form.html', success="Vehicle submitted as DRAFT. Please contact Main Admin for approval and registration.", vehicles=get_filtered_vehicles(include_all=True), role=role)

    # DIRECT REGISTRATION/SYNC for Main Admin / Super Admin (Requires Traccar Check)
    from services.traccar_service import check_device_exists
    traccar_device = check_device_exists(unique_id)
    
    if not traccar_device:
        from config import Config
        return render_template('vehicle_form.html', 
                               error=f"Vehicle not found in Traccar server. For direct registration, please add it to Traccar ({Config.TRACCAR_IP}) first.", 
                               vehicles=get_filtered_vehicles(include_all=True), 
                               role=role)

    try:
        new_vehicle = {
            "name": name, 
            "unique_id": unique_id, 
            "device_model": device_model,
            "driver_name": driver_name,
            "parent_email": v_parent,
            "company_name": current_data.get('company_name'),
            "status": "active"
        }
        add_vehicle_db(new_vehicle)
        return render_template('vehicle_form.html', success="Vehicle synced and registered successfully.", vehicles=get_filtered_vehicles(include_all=True), role=role)
    except Exception as e:
        return render_template('vehicle_form.html', error=f"Sync error: {str(e)}", vehicles=get_filtered_vehicles(include_all=True), role=role)

@vehicles_bp.route('/manage-drafts')
@role_required('main_admin')
def manage_drafts():
    from auth.utils import get_pending_drafts
    drafts = get_pending_drafts()
    
    # Also fetch recently approved for visual confirmation
    all_v = load_vehicles()
    recent_approved = [v for v in all_v if v.get('status') == 'active' and v.get('approval_date')]
    # Sort by approval date descending
    recent_approved.sort(key=lambda x: x.get('approval_date', ''), reverse=True)
    recent_approved = recent_approved[:10] # show last 10
    
    return render_template('manage_drafts.html', drafts=drafts, recent_approved=recent_approved)

@vehicles_bp.route('/approve-draft/<unique_id>', methods=['POST'])
@role_required('main_admin')
def approve_draft(unique_id):
    current = load_vehicles()
    v = next((v for v in current if str(v.get('unique_id')) == str(unique_id) and v.get('status') == 'draft'), None)
    
    if not v:
        return redirect(url_for('vehicles.manage_drafts', error="Draft not found."))

    # Strict backend limit enforcement during approval
    can_approve, limit_error = validate_draft_approval_limit(v.get('parent_email'))
    if not can_approve:
        return redirect(url_for('vehicles.manage_drafts', error=limit_error))

    try:
        from services.traccar_service import get_admin_traccar_session, full_traccar_host, ensure_admin_login, check_device_exists
        traccar = full_traccar_host()
        s = get_admin_traccar_session()
        
        # Ensure we have a valid session (refreshes if needed)
        if not ensure_admin_login(s):
             return redirect(url_for('vehicles.manage_drafts', error="Traccar Admin Login Failed. Please check server logs."))

        # 1. Check if device already exists in Traccar
        existing_device = check_device_exists(v['unique_id'])
        if existing_device:
            v['status'] = 'active'
            v['approval_date'] = str(datetime.now())
            update_vehicle_db(unique_id, v)
            return redirect(url_for('vehicles.manage_drafts', success=f"Vehicle {v['name']} found in Traccar. Approved/Synced successfully."))

        # 2. If not found, Manual Registration in Traccar
        payload = {"name": v['name'], "uniqueId": str(v['unique_id']), "model": v.get('device_model', '')}
        r = s.post(f"{traccar}/api/devices", json=payload, timeout=10)
        
        if r.status_code in [200, 201] or "Unique index or primary key violation" in r.text or "unique index" in r.text.lower():
            v['status'] = 'active'
            v['approval_date'] = str(datetime.now())
            update_vehicle_db(unique_id, v)
            return redirect(url_for('vehicles.manage_drafts', success=f"Vehicle {v['name']} registered in Traccar and approved."))
        else:
            # Truncate error message to avoid 414 Request-URI Too Large
            error_msg = r.text[:200] + "..." if len(r.text) > 200 else r.text
            return redirect(url_for('vehicles.manage_drafts', error=f"Traccar registration failed: {error_msg}"))
    except Exception as e:
        error_msg = str(e)[:200] + "..." if len(str(e)) > 200 else str(e)
        return redirect(url_for('vehicles.manage_drafts', error=f"Approval error: {error_msg}"))

@vehicles_bp.route('/decline-draft/<unique_id>', methods=['POST'])
@role_required('main_admin')
def decline_draft(unique_id):
    reason = request.form.get('reason', '').strip()
    current = load_vehicles()
    v = next((v for v in current if str(v.get('unique_id')) == str(unique_id) and v.get('status') == 'draft'), None)
    
    if not v:
        return redirect(url_for('vehicles.manage_drafts', error="Draft not found."))

    v['status'] = 'declined'
    v['rejection_reason'] = reason
    v['declined_at'] = str(datetime.now())
    update_vehicle_db(unique_id, v)
    return redirect(url_for('vehicles.manage_drafts', success=f"Vehicle {v['name']} has been declined."))

@vehicles_bp.route('/vehicle/delete/<unique_id>')
@role_required('admin')
def delete_vehicle(unique_id):
    # Support deleting both active and drafts (if visible)
    all_v = load_vehicles()
    v = next((v for v in all_v if str(v.get('unique_id')) == str(unique_id)), None)
    
    if not v: return redirect(url_for('vehicles.vehicle_form', error="Not found"))
    
    # Permission check (already handled by get_filtered_vehicles for active, 
    # but we need to check if user owns it)
    email = session.get('email')
    role = session.get('role')
    if role != 'super_admin' and v.get('parent_email') != email:
        # Check if it's in their subtree (for main_admin)
        if role == 'main_admin':
            from auth.utils import get_pending_drafts
            allowed_drafts = get_pending_drafts()
            if not any(str(vd.get('unique_id')) == str(unique_id) for vd in allowed_drafts):
                 return render_template('login.html', error="Access denied.")
        else:
            return render_template('login.html', error="Access denied.")

    delete_vehicle_db(unique_id)
    return redirect(request.referrer or url_for('vehicles.vehicle_form'))

@vehicles_bp.route('/vehicle/update/<unique_id>', methods=['POST'])
@role_required('admin')
def update_vehicle(unique_id):
    user_info, current_data = get_current_user_data()
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    allowed = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(unique_id) for v in allowed):
        return render_template('login.html', error="Access denied to this vehicle.")
        
    name = request.form.get('name', '').strip()
    device_model = request.form.get('device_model', '').strip()
    driver_name = request.form.get('driver_name', '').strip()
    
    if not name:
        return redirect(url_for('vehicles.vehicle_form', error="Name is required"))

    current = load_vehicles()
    found_vehicle = next((v for v in current if str(v.get('unique_id')) == str(unique_id)), None)
            
    if found_vehicle:
        found_vehicle['name'] = name
        found_vehicle['device_model'] = device_model
        found_vehicle['driver_name'] = driver_name
        update_vehicle_db(unique_id, found_vehicle)
        return redirect(url_for('vehicles.vehicle_form', success="Vehicle updated successfully"))
    else:
        return redirect(url_for('vehicles.vehicle_form', error="Vehicle not found"))

@vehicles_bp.route('/vehicle-list-json')
def vehicle_list_json():
    return {"vehicles": get_filtered_vehicles()}
