from flask import Blueprint, render_template, request, jsonify, session, current_app
from auth.utils import role_required

notifications_bp = Blueprint('notifications', __name__)

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
