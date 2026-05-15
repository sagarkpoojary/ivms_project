from config import Config
Config.validate()

from flask import Flask, session, request, redirect, url_for
from models.database import load_server_config
from auth.utils import get_current_user_data

from extensions import cache

# Initialize Extensions

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = Config.SECRET_KEY

# Cache Config
app.config['CACHE_TYPE'] = 'FileSystemCache'
app.config['CACHE_DIR'] = Config.CACHE_DIR
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache.init_app(app)

# Register Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.vehicles import vehicles_bp
from routes.users import users_bp
from routes.reports import reports_bp
from routes.notifications import notifications_bp
from routes.api import api_bp
from routes.external_reports import external_reports_bp
from routes.analytics import analytics_bp
from routes.maintenance import maintenance_bp
from routes.drivers import drivers_bp
from routes.site_ops import site_ops_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(vehicles_bp)
app.register_blueprint(users_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(api_bp)
app.register_blueprint(external_reports_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(drivers_bp)
app.register_blueprint(site_ops_bp)

@app.route('/')
def index():
    return redirect(url_for('reports.reports_home') if session.get('logged_in') else url_for('auth.login'))

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.context_processor
def inject_globals():
    cfg = load_server_config()
    active = cfg.get("active_ip", "")
    if active and not (active.startswith("http://") or active.startswith("https://")):
        active = "http://" + active
    web_ip = request.host_url.rstrip("/")
    
    user_info, current_data = get_current_user_data()
    from auth.utils import get_pending_drafts
    drafts = get_pending_drafts()
    pending_drafts_count = len(drafts)

    return {
        "user": user_info.get("name") if user_info and user_info.get("name") else session.get("user_name", "User"),
        "role": current_data.get('role', 'user'),
        "active_ip": active,
        "web_ip": web_ip,
        "enabled_modules": current_data.get('enabled_modules', []),
        "can_add_vehicle": current_data.get("can_add_vehicle", False),
        "company_name": current_data.get('company_name') or "No Company",
        "pending_drafts_count": pending_drafts_count
    }

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
