from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from auth.utils import role_required, get_filtered_vehicles
from models.database import get_conn
import psycopg2.extras
from datetime import datetime

maintenance_bp = Blueprint('maintenance', __name__)

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

@maintenance_bp.route('/api/maintenance/schedule')
@role_required('user')
def api_get_schedule():
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = "SELECT * FROM maintenance_schedule WHERE status != 'completed'"
        params = []
        if tenant_id:
            query += " AND tenant_id = %s"
            params.append(tenant_id)
        
        cur.execute(query, tuple(params))
        schedule = [dict(r) for r in cur.fetchall()]
        return jsonify(schedule)
    finally:
        cur.close(); conn.close()

@maintenance_bp.route('/api/maintenance/schedule', methods=['POST'])
@role_required('admin')
def api_create_schedule():
    data = request.get_json(force=True)
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO maintenance_schedule 
            (tenant_id, vehicle_id, imei, service_type, description, target_date, target_mileage, target_engine_hours, workshop_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, data.get('vehicle_name'), data.get('imei'), data.get('service_type'), 
            data.get('description'), data.get('target_date'), data.get('target_mileage'),
            data.get('target_engine_hours'), data.get('workshop_id')
        ))
        conn.commit()
        return jsonify({"success": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close(); conn.close()

@maintenance_bp.route('/api/maintenance/history')
@role_required('user')
def api_get_history():
    email = session.get('email')
    parent_email = session.get('parent_email')
    role = session.get('role')
    tenant_id = email if role == 'main_admin' else parent_email
    if role == 'super_admin': tenant_id = None

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = "SELECT * FROM maintenance_schedule WHERE status = 'completed' ORDER BY updated_at DESC LIMIT 100"
        params = []
        if tenant_id:
            query = "SELECT * FROM maintenance_schedule WHERE status = 'completed' AND tenant_id = %s ORDER BY updated_at DESC LIMIT 100"
            params.append(tenant_id)

        cur.execute(query, tuple(params))
        history = [dict(r) for r in cur.fetchall()]
        return jsonify(history)
    finally:
        cur.close(); conn.close()
