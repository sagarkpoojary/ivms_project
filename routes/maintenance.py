import os
import uuid
import logging
from flask import Blueprint, render_template, session, request, jsonify, make_response, send_from_directory
from werkzeug.utils import secure_filename
from auth.utils import role_required
from services.maintenance_service import (
    get_maintenance_schedules,
    create_maintenance_schedule,
    get_upcoming_maintenance_with_alerts,
    complete_maintenance,
    get_maintenance_history,
    get_maintenance_workshops,
    get_maintenance_stats
)

logger = logging.getLogger(__name__)

maintenance_bp = Blueprint('maintenance', __name__)

# Ensure secure upload path exists and is isolated
UPLOAD_FOLDER = '/root/ivms_project/static/uploads/maintenance'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Allowed files for documentation and invoices
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
ALLOWED_MIMETYPES = {'application/pdf', 'image/png', 'image/jpeg', 'image/jpg'}

def get_tenant_id():
    """
    Utility helper to resolve tenant ID based on role permissions.
    """
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    
    # Resolving tenant isolation ID
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin':
        tenant_id = None
    return tenant_id

# ---------------------------------------------------------------------------
# UI Page Routes
# ---------------------------------------------------------------------------

@maintenance_bp.route('/maintenance')
@role_required('user')
def maintenance_home():
    return render_template('maintenance/calendar.html')

@maintenance_bp.route('/maintenance/upcoming')
@role_required('user')
def maintenance_upcoming():
    return render_template('maintenance/upcoming.html')

@maintenance_bp.route('/maintenance/history')
@role_required('user')
def maintenance_history():
    return render_template('maintenance/history.html')

# ---------------------------------------------------------------------------
# API Persistence Endpoints
# ---------------------------------------------------------------------------

@maintenance_bp.route('/api/maintenance/schedule', methods=['GET'])
@role_required('user')
def api_get_schedule():
    tenant_id = get_tenant_id()
    # Resolve live upcoming and alerts
    upcoming = get_upcoming_maintenance_with_alerts(tenant_id)
    return jsonify(upcoming)

@maintenance_bp.route('/api/maintenance/schedule', methods=['POST'])
@role_required('admin')
def api_create_schedule():
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    if not data or not data.get('imei') or not data.get('service_type'):
        return jsonify({"error": "Missing required fields"}), 400

    success = create_maintenance_schedule(tenant_id, data)
    if success:
        return jsonify({"success": True}), 201
    return jsonify({"error": "Failed to schedule maintenance"}), 500

@maintenance_bp.route('/api/maintenance/schedule/complete/<int:schedule_id>', methods=['POST'])
@role_required('admin')
def api_complete_schedule(schedule_id):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return jsonify({"error": "Admin scope required"}), 400
        
    data = request.get_json(force=True)
    success, msg = complete_maintenance(tenant_id, schedule_id, data)
    if success:
        return jsonify({"success": True, "message": msg}), 200
    return jsonify({"error": msg}), 500

@maintenance_bp.route('/api/maintenance/history', methods=['GET'])
@role_required('user')
def api_get_history():
    tenant_id = get_tenant_id()
    history = get_maintenance_history(tenant_id)
    return jsonify(history)

@maintenance_bp.route('/api/maintenance/workshops', methods=['GET'])
@role_required('user')
def api_get_workshops():
    tenant_id = get_tenant_id()
    workshops = get_maintenance_workshops(tenant_id)
    return jsonify(workshops)

@maintenance_bp.route('/api/maintenance/stats', methods=['GET'])
@role_required('user')
def api_get_stats():
    tenant_id = get_tenant_id()
    stats = get_maintenance_stats(tenant_id)
    return jsonify(stats)

# ---------------------------------------------------------------------------
# Secure Document / Invoice Upload
# ---------------------------------------------------------------------------

@maintenance_bp.route('/api/maintenance/history/upload', methods=['POST'])
@role_required('admin')
def api_upload_attachment():
    """
    Secure file upload with magic headers validation, size constraints,
    and automatic path isolation + file renaming.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part in request"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # 1. Enforce size constraint limit of 5MB to prevent DoS/overflows
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({"error": "File size exceeds limit of 5MB"}), 400

    # 2. Extract and validate extension
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Extension .{ext} is not allowed"}), 400

    # 3. Validate content-type header
    mime = file.content_type
    if mime not in ALLOWED_MIMETYPES:
        return jsonify({"error": f"Content-Type {mime} is not allowed"}), 400

    # 4. Generate predictable, secure random UUID name (no user input traversal!)
    secure_name = f"{uuid.uuid4().hex}.{ext}"
    dest_path = os.path.join(UPLOAD_FOLDER, secure_name)

    try:
        file.save(dest_path)
        logger.info(f"File successfully uploaded: {secure_name} (size: {size} bytes)")
        
        return jsonify({
            "success": True,
            "name": filename,
            "path": f"/static/uploads/maintenance/{secure_name}",
            "type": mime
        }), 200
    except Exception as e:
        logger.error(f"Failed to save upload file: {e}")
        return jsonify({"error": "Failed to save file on disk"}), 500

@maintenance_bp.route('/static/uploads/maintenance/<filename>', methods=['GET'])
@role_required('user')
def download_attachment(filename):
    """
    Serve uploaded document safely forcing attachment download to bypass inline execution threats.
    """
    clean_filename = secure_filename(filename)
    dest_path = os.path.join(UPLOAD_FOLDER, clean_filename)
    if not os.path.exists(dest_path):
        return make_response(jsonify({"error": "File not found"}), 404)
        
    # Force attachment mode
    response = make_response(send_from_directory(UPLOAD_FOLDER, clean_filename, as_attachment=True))
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Disposition'] = f'attachment; filename={clean_filename}'
    return response
