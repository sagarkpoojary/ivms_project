from flask import Blueprint, render_template, session, request, jsonify
from auth.utils import role_required
from models.database import get_conn
import psycopg2.extras

drivers_bp = Blueprint('drivers', __name__)

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
