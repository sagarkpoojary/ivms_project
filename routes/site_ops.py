from flask import Blueprint, render_template, session, request, jsonify
from auth.utils import role_required
from models.database import get_conn
import psycopg2.extras

site_ops_bp = Blueprint('site_ops', __name__)

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
