from flask import Blueprint, render_template, session, request, jsonify
from auth.utils import role_required, get_filtered_vehicles
from models.database import get_conn
import psycopg2.extras
from config import Config

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/fleet-efficiency')
@role_required('user')
def fleet_efficiency():
    return render_template('fleet_analytics.html')

@analytics_bp.route('/driver-behavior')
@role_required('user')
def driver_behavior():
    return render_template('driver_analytics.html')

@analytics_bp.route('/event-center')
@role_required('user')
def event_center():
    return render_template('events_center.html')

@analytics_bp.route('/condition-monitoring')
@role_required('user')
def condition_monitoring():
    return render_template('condition_monitoring.html')
@analytics_bp.route('/diagnostics')
@role_required('super_admin')
def diagnostics():
    return render_template('diagnostics.html', title='System Diagnostics', role=session.get('role'))
