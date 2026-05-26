from config import Config
Config.validate()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_wtf.csrf import CSRFProtect
import os
from models.database import load_server_config
from auth.utils import get_current_user_data

from extensions import cache

# Initialize Extensions

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = Config.SECRET_KEY

# Cache Config
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET', 'ivms_secure_secret_2026')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

csrf = CSRFProtect(app)
app.config['CACHE_TYPE'] = 'FileSystemCache'
app.config['CACHE_DIR'] = Config.CACHE_DIR
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache.init_app(app)

# Structured JSON Logging & Request Correlation ID Middleware
from middleware.structured_logging import StructuredLoggingMiddleware
StructuredLoggingMiddleware(app)

# Redis-Backed Sliding Window Rate Limiter (Defense-in-Depth)
from middleware.rate_limiter import RedisRateLimiter
RedisRateLimiter(app, limit=100, period=60)

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

# IVMS ADDITION — Enterprise External API Layer
from routes.external_api import external_api_bp; app.register_blueprint(external_api_bp)

# IVMS ADDITION — Prometheus metrics exposition endpoint
from flask import Response as _Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
@app.route('/metrics')
def metrics():
    return _Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route('/health')
def health():
    return {"status": "ok"}, 200

@app.route('/ready')
def ready():
    from models.database import get_conn
    import redis
    
    # 1. Verify TimescaleDB connectivity
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close(); conn.close()
    except Exception as e:
        return {"status": "unavailable", "reason": f"Database is offline: {e}"}, 503
        
    # 2. Verify Redis responsiveness
    try:
        r = redis.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, db=Config.REDIS_DB, socket_timeout=1.0)
        r.ping()
    except Exception as e:
        return {"status": "unavailable", "reason": f"Redis cache is offline: {e}"}, 503
        
    return {"status": "ready"}, 200

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
