import json
from flask import Blueprint, render_template, request, jsonify, session, current_app
from auth.utils import role_required

notifications_bp = Blueprint('notifications', __name__)

def check_and_generate_reminders(tenant_id, user_email):
    if not tenant_id:
        return
        
    from models.database import get_conn, get_user_by_email
    from services.time_service import get_oman_now
    from services.maintenance_service import get_upcoming_maintenance_with_alerts
    from auth.utils import get_filtered_vehicles
    from datetime import datetime
    import psycopg2.extras

    today = get_oman_now().date()
    user_info = get_user_by_email(user_email)
    reminder_settings = {}
    if user_info and isinstance(user_info.get('data'), dict):
        reminder_settings = user_info['data'].get('reminder_settings', {})
    
    # Default values if not configured
    ins_days = reminder_settings.get('insurance_days', [30, 15, 7])
    reg_days = reminder_settings.get('registration_days', [30, 15, 7])
    
    vehicles = get_filtered_vehicles(include_all=True)
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        for v in vehicles:
            v_name = v.get('name', v.get('unique_id'))
            unique_id = v.get('unique_id')
            
            # --- 1. Insurance Expiry ---
            ins_exp_str = v.get('insurance_expiry_date')
            policy_num = v.get('insurance_policy_number', 'N/A')
            if ins_exp_str:
                try:
                    ins_exp = datetime.strptime(ins_exp_str, "%Y-%m-%d").date()
                    days_left = (ins_exp - today).days
                    
                    if days_left in ins_days:
                        title = f"Insurance Expiry: {v_name} expires in {days_left} days"
                        message = f"Insurance policy {policy_num} for vehicle '{v_name}' is expiring in {days_left} days on {ins_exp_str}."
                        cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                                VALUES (%s, %s, %s, %s, FALSE, FALSE)
                            """, (tenant_id, 'WARNING', title, message))
                    elif days_left < 0:
                        title = f"Insurance Expired: {v_name} has expired"
                        message = f"Insurance policy {policy_num} for vehicle '{v_name}' expired on {ins_exp_str} ({abs(days_left)} days ago)."
                        cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                                VALUES (%s, %s, %s, %s, FALSE, FALSE)
                            """, (tenant_id, 'CRITICAL', title, message))
                except Exception:
                    pass
            
            # --- 2. Registration Expiry ---
            reg_exp_str = v.get('registration_expiry_date')
            plate_num = v.get('plate_number', 'N/A')
            if reg_exp_str:
                try:
                    reg_exp = datetime.strptime(reg_exp_str, "%Y-%m-%d").date()
                    days_left = (reg_exp - today).days
                    
                    if days_left in reg_days:
                        title = f"Registration Expiry: {v_name} expires in {days_left} days"
                        message = f"Vehicle registration (Plate: {plate_num}) for '{v_name}' is expiring in {days_left} days on {reg_exp_str}."
                        cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                                VALUES (%s, %s, %s, %s, FALSE, FALSE)
                            """, (tenant_id, 'WARNING', title, message))
                    elif days_left < 0:
                        title = f"Registration Expired: {v_name} has expired"
                        message = f"Vehicle registration (Plate: {plate_num}) for '{v_name}' expired on {reg_exp_str} ({abs(days_left)} days ago)."
                        cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                                VALUES (%s, %s, %s, %s, FALSE, FALSE)
                            """, (tenant_id, 'CRITICAL', title, message))
                except Exception:
                    pass
        
        # --- 3. Maintenance Schedules ---
        upcoming = get_upcoming_maintenance_with_alerts(tenant_id)
        for item in upcoming:
            v_id = item.get('vehicle_id') or item.get('imei')
            service_type = item.get('service_type', 'Service')
            live_status = item.get('live_status')
            
            if live_status == 'due':
                title = f"Maintenance Due: {v_id} - {service_type}"
                message = f"Maintenance task '{service_type}' for vehicle '{v_id}' is due soon. Target date: {item.get('target_date')}."
                cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                        VALUES (%s, %s, %s, %s, FALSE, FALSE)
                    """, (tenant_id, 'WARNING', title, message))
            elif live_status == 'overdue':
                title = f"Maintenance Overdue: {v_id} - {service_type}"
                message = f"Maintenance task '{service_type}' for vehicle '{v_id}' is overdue! Target date was: {item.get('target_date')}."
                cur.execute("SELECT id FROM notification_queue WHERE title = %s AND tenant_id = %s AND archived = FALSE", (title, tenant_id))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO notification_queue (tenant_id, severity, title, message, read, archived)
                        VALUES (%s, %s, %s, %s, FALSE, FALSE)
                    """, (tenant_id, 'CRITICAL', title, message))
                    
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error checking reminders: {e}")
    finally:
        cur.close(); conn.close()

@notifications_bp.route('/notifications')
@role_required('user')
def notifications_home():
    return render_template('notifications.html')

@notifications_bp.route("/api/notifications/latest")
@role_required('user')
def get_latest_notifications():
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    
    # Identify the relevant tenant for notifications
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None
    
    # Generate reminders dynamically
    if tenant_id:
        check_and_generate_reminders(tenant_id, email)
        
    from models.database import get_conn
    import psycopg2.extras
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Fetch unread count
        count_query = "SELECT COUNT(*) FROM notification_queue WHERE read = FALSE"
        params = []
        if tenant_id:
            count_query += " AND tenant_id = %s"
            params.append(tenant_id)
        cur.execute(count_query, tuple(params))
        unread_count = cur.fetchone()['count']
        
        # Fetch latest 10 notifications
        notif_query = "SELECT * FROM notification_queue WHERE archived = FALSE"
        params = []
        if tenant_id:
            notif_query += " AND tenant_id = %s"
            params.append(tenant_id)
        notif_query += " ORDER BY created_at DESC LIMIT 10"
        
        cur.execute(notif_query, tuple(params))
        notifications = [dict(r) for r in cur.fetchall()]
        
        return jsonify({
            "notifications": notifications,
            "unread_count": unread_count
        })
    finally:
        cur.close(); conn.close()

@notifications_bp.route("/api/notifications/read/<int:id>", methods=["POST"])
@role_required('user')
def mark_read(id):
    from models.database import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE notification_queue SET read = TRUE WHERE id = %s", (id,))
        conn.commit()
        return jsonify({"success": True})
    finally:
        cur.close(); conn.close()

@notifications_bp.route("/api/notifications/read-all", methods=["POST"])
@role_required('user')
def mark_all_read():
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None
    
    from models.database import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        query = "UPDATE notification_queue SET read = TRUE WHERE read = FALSE"
        params = []
        if tenant_id:
            query += " AND tenant_id = %s"
            params.append(tenant_id)
        cur.execute(query, tuple(params))
        conn.commit()
        return jsonify({"success": True})
    finally:
        cur.close(); conn.close()

# --- Notification Rules CRUD Endpoints ---
@notifications_bp.route("/api/notification-rules", methods=["GET"])
@role_required('user')
def api_get_rules():
    from models.database import get_conn
    import psycopg2.extras
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None
    
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = "SELECT * FROM notification_rules"
        params = []
        if tenant_id:
            query += " WHERE tenant_id = %s"
            params.append(tenant_id)
        query += " ORDER BY type"
        cur.execute(query, tuple(params))
        rules = [dict(r) for r in cur.fetchall()]
        return jsonify(rules)
    finally:
        cur.close(); conn.close()

@notifications_bp.route("/api/notification-rules", methods=["POST"])
@role_required('admin')
def api_create_rule():
    from models.database import get_conn
    data = request.get_json(force=True)
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None
    
    conn = get_conn()
    cur = conn.cursor()
    try:
        query = "INSERT INTO notification_rules (tenant_id, type, notificators, description, attributes) VALUES (%s, %s, %s, %s, %s)"
        cur.execute(query, (tenant_id, data.get('type'), ','.join(data.get('channels', [])), data.get('description'), json.dumps(data.get('attributes', {}))))
        conn.commit()
        return jsonify({"status": "success"}), 201
    finally:
        cur.close(); conn.close()

@notifications_bp.route("/api/notification-rules/<int:rule_id>", methods=["DELETE"])
@role_required('admin')
def api_delete_rule(rule_id):
    from models.database import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM notification_rules WHERE id = %s", (rule_id,))
        conn.commit()
        return jsonify({"success": True})
    finally:
        cur.close(); conn.close()
