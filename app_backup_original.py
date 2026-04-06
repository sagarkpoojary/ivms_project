from flask import Flask, request, render_template, redirect, url_for, session, jsonify, abort, make_response, has_request_context
import requests
import os
import json
import random
import csv
import io
from pathlib import Path
from datetime import datetime, timedelta, date

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Firebase Init
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(os.path.join(APP_ROOT, "serviceAccountKey.json"))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Firebase Init Error: {e}")

db = firestore.client()

ALL_SYSTEM_MODULES = [
    "dashboard", 
    "reports", 
    "pre_reg_report", 
    "vehicle_add", 
    "user_manager", 
    "notifications", 
    "servers",
    # Granular Dashboard Features
    "dashboard_stats",
    "dashboard_charts",
    "dashboard_map",
    "dashboard_big_chart",
    "dashboard_alerts",
    # Granular Report Features
    "reports_trips",
    "reports_stops",
    "reports_combined",
    "pricing"
]


app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("FLASK_SECRET", "dev_secret_change_me")


from functools import wraps

# -------------------------
# Helpers & Decorators
# -------------------------

# -------------------------
# helpers
# -------------------------

def load_server_config():
    try:
        doc = db.collection('system_config').document('traccar_settings').get()
        return doc.to_dict() if doc.exists else {}
    except: return {}

def save_server_config(data):
    try:
        db.collection('system_config').document('traccar_settings').set(data)
    except: pass

def load_module_config():
    try:
        doc = db.collection('system_config').document('pricing_plans').get()
        # structure is {plans: {...}}
        data = doc.to_dict()
        return data.get('plans', {}) if data else {}
    except: return {}

def save_module_config(data):
    try:
        db.collection('system_config').document('pricing_plans').set({'plans': data})
    except: pass

def load_vehicles():
    try:
        return [d.to_dict() for d in db.collection('vehicles').stream()]
    except: return []

# Replaces save_vehicles(list) - NOT USED directly anymore
# specific atomic ops:

def add_vehicle_db(data):
    db.collection('vehicles').document(str(data['unique_id'])).set(data)

def delete_vehicle_db(unique_id):
    db.collection('vehicles').document(str(unique_id)).delete()

def update_vehicle_db(unique_id, data):
    db.collection('vehicles').document(str(unique_id)).set(data, merge=True)

def load_users():
    try:
        users = []
        for d in db.collection('users').stream():
            u = d.to_dict()
            if not u.get('email'):
                u['email'] = d.id
            if not u.get('name'):
                u['name'] = u['email'].split('@')[0] if '@' in u['email'] else u['email']
            users.append(u)
        return users
    except: return []

# Replaces save_users(list)

def add_user_db(data):
    db.collection('users').document(data['email']).set(data)

def delete_user_db(email):
    db.collection('users').document(email).delete()

def update_user_db(email, data):
    db.collection('users').document(email).set(data, merge=True)

def get_user_by_email(email):
    users = load_users()
    for u in users:
        if u.get('email') == email:
            return u
    return None

def get_current_user_data():
    if not session.get('logged_in'):
        return None, {}
    email = session.get('email')
    user_info = get_user_by_email(email)
    
    current_data = {
        'role': session.get('role', 'user'),
        'vehicle_limit': session.get('vehicle_limit'),
        'user_limit': session.get('user_limit'),
        'enabled_modules': session.get('enabled_modules', []),
        'account_module': session.get('account_module', 'Normal'),
        'can_add_vehicle': session.get('can_add_vehicle', False)
    }
    return user_info, current_data

def full_traccar_host():
    cfg = load_server_config()
    active = cfg.get("active_ip")
    if not active: return None
    if not (active.startswith("http://") or active.startswith("https://")):
            return "http://" + active
    return active.rstrip('/')

def get_traccar_session():
    s = requests.Session()
    if has_request_context() and 'traccar_cookies' in session:
        requests.utils.add_dict_to_cookiejar(s.cookies, session['traccar_cookies'])
        return s
    if os.path.exists('cookies.txt'):
            try:
                with open('cookies.txt', 'r') as f:
                    cookies = json.load(f)
                    requests.utils.add_dict_to_cookiejar(s.cookies, cookies)
            except: pass
    return s

def save_traccar_cookies(s):
    cookies = requests.utils.dict_from_cookiejar(s.cookies)
    if has_request_context():
        session['traccar_cookies'] = cookies
        session.modified = True
    with open('cookies.txt', 'w') as f:
            json.dump(cookies, f)

def try_traccar_get(endpoint, params=None, timeout=10):
    host = full_traccar_host()
    if not host: raise Exception("No Traccar Host")
    s = get_traccar_session()
    r = s.get(f"{host}/{endpoint}", params=params, timeout=timeout)
    save_traccar_cookies(s)
    return r, host

def get_period_dates(period, from_str=None, to_str=None):
    now = datetime.now()
    start_dt = now
    end_dt = now
    
    if period == 'Yesterday':
        start_dt = now - timedelta(days=1)
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999)
    elif period == 'This Week':
        start_dt = now - timedelta(days=now.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'This Month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'Custom' and from_str:
        try:
            start_dt = datetime.strptime(from_str, '%Y-%m-%dT%H:%M')
            if to_str:
                end_dt = datetime.strptime(to_str, '%Y-%m-%dT%H:%M')
        except:
            pass
    else: # Today
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        
    return start_dt, end_dt

def get_filtered_vehicles():
    all_vehicles = load_vehicles()
    if not session.get('logged_in'): return []
    
    role = session.get('role', 'user')
    email = session.get('email')
    parent_email = session.get('parent_email')
    
    if role == 'super_admin':
        return all_vehicles
    elif role == 'main_admin':
        # Filter for vehicles owned by this admin or their direct sub-users
        users = load_users()
        my_subtree = set([email])
        
        # Build parent map for hierarchy traversal
        parent_map = {}
        for u in users:
            p = u.get('parent_email')
            if p:
                parent_map.setdefault(p, []).append(u.get('email'))
        
        # Traverse down to find all descendants
        stack = [email]
        while stack:
            current_parent = stack.pop()
            children = parent_map.get(current_parent, [])
            for child in children:
                if child not in my_subtree:
                    my_subtree.add(child)
                    stack.append(child)
                    
        return [v for v in all_vehicles if v.get('parent_email') in my_subtree]
    elif role == 'admin':
        return [v for v in all_vehicles if v.get('parent_email') == email]
    elif role == 'user':
        return [v for v in all_vehicles if v.get('parent_email') == parent_email]
    
    return []

def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            
            user_role = session.get('role', 'user')
            
            roles = ['user', 'admin', 'main_admin', 'super_admin']
            
            try:
                user_level = roles.index(user_role)
                req_level = roles.index(required_role)
            except ValueError:
                # If role not found in standard list, assume lowest or handle specifically
                # For safety, if user_role is unknown, treat as level -1
                user_level = -1
                req_level = 100
                if required_role in roles:
                     req_level = roles.index(required_role)
            
            # Allow super_admin to access everything
            if user_role == 'super_admin':
                return f(*args, **kwargs)

            if user_level < req_level:
                    return render_template('login.html', error="Unauthorized access.")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/dashboard-config', methods=['GET', 'POST'])
@role_required('super_admin')
def dashboard_config():
    modules_config = load_module_config()
    # Filter only dashboard-related modules + pricing
    dashboard_modules = [m for m in ALL_SYSTEM_MODULES if m.startswith('dashboard') or m == 'pricing']
    
    if request.method == 'POST':
        action = request.form.get('action')
        plan_name = request.form.get('plan_name')
        
        if action == 'update' and plan_name in modules_config:
            try:
                # We only want to update the dashboard modules, preserving others
                current_enabled = set(modules_config[plan_name].get('enabled_modules', []))
                
                # Get submitted modules
                submitted = set(request.form.getlist('enabled_modules'))
                
                # Logic: Remove all *possible* dashboard modules from current, then add back the submitted ones
                # This ensures we don't accidentally delete 'user_manager' or 'reports' if they aren't in the form
                for m in dashboard_modules:
                    if m in current_enabled:
                        current_enabled.remove(m)
                
                # Add back the checked ones from form
                for m in submitted:
                    current_enabled.add(m)
                
                modules_config[plan_name]['enabled_modules'] = list(current_enabled)
                
                save_module_config(modules_config)
                return redirect(url_for('dashboard_config', success=f"Dashboard settings for {plan_name} updated."))
            except Exception as e:
                return render_template('dashboard_config.html', modules_config=modules_config, doc_modules=dashboard_modules, error=f"Error: {e}")
        
    return render_template('dashboard_config.html', modules_config=modules_config, doc_modules=dashboard_modules, success=request.args.get('success'))

@app.route('/plan-manager', methods=['GET', 'POST'])
@role_required('super_admin')
def plan_manager():
    modules_config = load_module_config()
    all_available_modules = ALL_SYSTEM_MODULES
    
    if request.method == 'POST':
        action = request.form.get('action')
        plan_name = request.form.get('plan_name')
        
        if action == 'update' and plan_name in modules_config:
            try:
                v_limit = request.form.get('vehicle_limit')
                u_limit = request.form.get('user_limit')
                enabled = request.form.getlist('enabled_modules')
                
                modules_config[plan_name]['vehicle_limit'] = int(v_limit) if v_limit and v_limit.isdigit() else 0
                modules_config[plan_name]['user_limit'] = int(u_limit) if u_limit and u_limit.isdigit() else 0
                modules_config[plan_name]['enabled_modules'] = enabled
                
                save_module_config(modules_config)
                return redirect(url_for('plan_manager', success=f"Plan {plan_name} updated successfully."))
            except Exception as e:
                return render_template('plan_manager.html', modules_config=modules_config, all_modules=all_available_modules, error=f"Error updating plan: {e}")
        
    return render_template('plan_manager.html', modules_config=modules_config, all_modules=all_available_modules, success=request.args.get('success'))

@app.route('/notifications')
@role_required('user')
def notifications():
    return render_template('notifications.html')

@app.route("/api/notifications", methods=["POST"])
def create_notification():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True)

    # ---- validation ----
    speed = data.get("speed")
    device_ids = data.get("deviceIds")

    if not speed or not device_ids:
        return jsonify({"error": "speed and deviceIds are required"}), 400

    traccar = full_traccar_host()
    s = get_traccar_session()

    payload = {
        "type": "deviceOverspeed",
        "attributes": {
            "speedLimit": int(speed)
        },
        "always": True,
        "notificators": "command",
        "devices": device_ids
    }

    r = s.post(f"{traccar}/api/notifications", json=payload)

    if r.status_code not in (200, 201):
        return jsonify({
            "error": "failed_to_create_notification",
            "status": r.status_code,
            "response": r.text
        }), 500

    return jsonify(r.json()), 201

from datetime import datetime, timedelta

from datetime import datetime, timedelta

@app.route("/api/events")
def proxy_events():
    if not session.get("logged_in"):
        return jsonify([]), 401

    try:
        now = datetime.utcnow()
        start = now - timedelta(hours=24)

        params = {
            "from": start.isoformat() + "Z",
            "to": now.isoformat() + "Z"
        }

        try:
            r, host_used = try_traccar_get("api/events", params=params, timeout=10)
        except Exception as e:
            # return informative error so frontend can show which host failed
            app.logger.exception("Failed to fetch events: %s", e)
            return jsonify({"error": "failed_to_fetch_events", "detail": str(e)}), 502

        return jsonify(r.json()), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/alerts")
def api_alerts():
    if not session.get("logged_in"):
        return jsonify([]), 401
    params = {"type": "deviceOverspeed", "limit": 20}
    try:
        r, host_used = try_traccar_get("api/reports/events", params=params, timeout=10)
        return jsonify(r.json())
    except Exception:
        app.logger.exception("Failed to fetch alerts")
        return jsonify([]), 500


@app.route("/api/notifications", methods=["GET"])
def list_notifications():
    if not session.get("logged_in"):
        return jsonify([]), 401

    traccar = full_traccar_host()
    s = get_traccar_session()

    r = s.get(f"{traccar}/api/notifications", timeout=10)
    save_traccar_cookies(s)

    if r.status_code != 200:
        return jsonify([]), 500

    return jsonify(r.json())

@app.route("/api/notification-rules", methods=["GET"])
def list_notification_rules():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401

    traccar = full_traccar_host()
    s = get_traccar_session()

    r = s.get(f"{traccar}/api/notifications", timeout=10)

    if r.status_code != 200:
        return jsonify({"error": "failed_to_fetch_rules"}), 500

    return jsonify(r.json())

@app.route("/api/notification-rules", methods=["POST"])
def create_notification_rule():
    """Create a new notification rule in Traccar"""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True)
    
    # Validate required fields
    rule_type = data.get("type")
    channels = data.get("channels", [])
    
    if not rule_type:
        return jsonify({"error": "type is required"}), 400
    
    if not channels or len(channels) == 0:
        return jsonify({"error": "at least one channel is required"}), 400
    
    # Build Traccar notification payload
    traccar = full_traccar_host()
    if not traccar:
        return jsonify({"error": "traccar_host_not_configured"}), 500
    
    s = get_traccar_session()
    
    # Construct payload for Traccar API
    payload = {
        "type": rule_type,
        "notificators": ",".join(channels),  # Traccar expects comma-separated string
        "always": data.get("always", False),
        "attributes": data.get("attributes", {})
    }
    
    # Optional fields
    if data.get("description"):
        payload["description"] = data["description"]
    
    if data.get("calendarId"):
        payload["calendarId"] = data["calendarId"]
    elif data.get("calendar"):
        payload["calendarId"] = data["calendar"]

    if data.get("priority"):
        if "attributes" not in payload:
            payload["attributes"] = {}
        payload["attributes"]["priority"] = data.get("priority")
    
    # Handle device associations
    # If not "always", we need to link devices separately after creation
    device_ids = data.get("deviceIds", [])
    
    try:
        # Create the notification rule
        r = s.post(f"{traccar}/api/notifications", json=payload, timeout=10)
        save_traccar_cookies(s)
        
        if r.status_code not in (200, 201):
            app.logger.error(f"Failed to create notification rule: {r.status_code} - {r.text}")
            return jsonify({
                "error": "failed_to_create_rule",
                "status": r.status_code,
                "detail": r.text
            }), 500
        
        created_rule = r.json()
        notification_id = created_rule.get("id")
        
        # Link devices if not "always" and device_ids provided
        if not payload["always"] and device_ids and notification_id:
            for device_id in device_ids:
                link_payload = {
                    "notificationId": notification_id,
                    "deviceId": int(device_id)
                }
                try:
                    link_r = s.post(f"{traccar}/api/permissions", json=link_payload, timeout=10)
                    if link_r.status_code not in (200, 204):
                        app.logger.warning(f"Failed to link device {device_id} to notification {notification_id}")
                except Exception as e:
                    app.logger.error(f"Error linking device {device_id}: {e}")
        
        return jsonify(created_rule), 201
        
    except Exception as e:
        app.logger.exception("Error creating notification rule")
        return jsonify({"error": str(e)}), 500

@app.route("/api/notification-rules/<int:rule_id>", methods=["DELETE"])
def delete_notification_rule(rule_id):
    """Delete a notification rule from Traccar"""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    
    traccar = full_traccar_host()
    if not traccar:
        return jsonify({"error": "traccar_host_not_configured"}), 500
    
    s = get_traccar_session()
    
    try:
        r = s.delete(f"{traccar}/api/notifications/{rule_id}", timeout=10)
        save_traccar_cookies(s)
        
        if r.status_code == 204:
            return jsonify({"success": True}), 200
        elif r.status_code == 404:
            return jsonify({"error": "rule_not_found"}), 404
        else:
            app.logger.error(f"Failed to delete notification rule {rule_id}: {r.status_code}")
            return jsonify({
                "error": "failed_to_delete_rule",
                "status": r.status_code
            }), 500
            
    except Exception as e:
        app.logger.exception(f"Error deleting notification rule {rule_id}")
        return jsonify({"error": str(e)}), 500


# -------------------------
# Auth & Index
# -------------------------
@app.route('/')
def index():
    return redirect(url_for('reports') if session.get('logged_in') else url_for('login'))

@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def do_login():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    if not email or not password:
        return render_template('login.html', error="Please enter email and password.")
    traccar = full_traccar_host()
    if not traccar:
        return render_template('login.html', error="Traccar host not configured.")
    s = requests.Session()
    try:
        r = s.post(f"{traccar}/api/session", data={'email': email, 'password': password}, timeout=10)
        save_traccar_cookies(s)
    except Exception as e:
        return render_template('login.html', error=f"Login error: {e}")
    if r.status_code == 200:
        session['logged_in'] = True
        try:
            traccar_user = r.json()
        except:
            traccar_user = {}

        user_info = get_user_by_email(email)
        
        # Determine role and hierarchy:
        if user_info:
            role = user_info.get('role', 'user')
            name = user_info.get('name', email)
            account_module = user_info.get('account_module', 'Normal')
            parent_email = user_info.get('parent_email')
            can_add_vehicle = user_info.get('can_add_vehicle', False)
        elif traccar_user.get('administrator'):
            role = 'main_admin'
            name = traccar_user.get('name', email)
            account_module = 'Normal'
            parent_email = None
            can_add_vehicle = True
        else:
            role = 'user'
            name = email
            account_module = 'Normal'
            parent_email = None
            can_add_vehicle = False

        # Load limits from module config
        modules = load_module_config()
        mod_cfg = modules.get(account_module, modules.get('Normal', {}))
        
        session['user_name'] = name
        session['role'] = role
        session['email'] = email
        session['parent_email'] = parent_email
        session['account_module'] = account_module
        session['vehicle_limit'] = mod_cfg.get('vehicle_limit', 1)
        session['user_limit'] = mod_cfg.get('user_limit', 0)
        session['enabled_modules'] = mod_cfg.get('enabled_modules', [])
        session['can_add_vehicle'] = can_add_vehicle
        
        if role == 'super_admin':
            session['vehicle_limit'] = None
            session['user_limit'] = None
            session['enabled_modules'] = ["dashboard", "reports", "pre_reg_report", "vehicle_add", "user_manager", "notifications", "servers"]
        elif role == 'main_admin' and account_module == 'Normal':
            # Default main_admin to Premium if not otherwise specified
            account_module = 'Premium'
            mod_cfg = modules.get('Premium', mod_cfg)
            session['account_module'] = 'Premium'
            session['vehicle_limit'] = mod_cfg.get('vehicle_limit')
            session['user_limit'] = mod_cfg.get('user_limit')
            session['enabled_modules'] = mod_cfg.get('enabled_modules', [])
            session['can_add_vehicle'] = True
        
        return redirect(url_for('reports'))
    return render_template('login.html', error="Login failed. Check credentials.")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route("/api/device-models")
def device_models():
    try:
        html = requests.get("https://www.traccar.org/devices/", timeout=5).text
        return jsonify({"html": html})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# Templates helpers (globals)
# -------------------------
@app.context_processor
def inject_globals():
    cfg = load_server_config()
    active = cfg.get("active_ip", "")
    if active and not (active.startswith("http://") or active.startswith("https://")):
        active = "http://" + active
    web_ip = request.host_url.rstrip("/")
    
    _, current_data = get_current_user_data()
    
    return {
        "user": session.get("user_name", "User"),
        "role": current_data.get('role', 'user'),
        "active_ip": active,
        "web_ip": web_ip,
        "enabled_modules": current_data.get('enabled_modules', []),
        "can_add_vehicle": session.get("can_add_vehicle", False)
    }

# -------------------------
# Pages
# -------------------------
@app.route('/pricing')
@role_required('user')
def pricing():
    modules_config = load_module_config()
    return render_template('pricing.html', modules_config=modules_config, all_modules=ALL_SYSTEM_MODULES)

@app.route('/download/apk')
@role_required('user')
def download_apk():
    """Serve the IVMS mobile app APK file for download."""
    apk_path = os.path.join(APP_ROOT, 'static', 'downloads', 'ivms-app.apk')
    
    if not os.path.exists(apk_path):
        return render_template('pricing.html', 
                             modules_config=load_module_config(), 
                             all_modules=ALL_SYSTEM_MODULES,
                             error="APK file not found. Please contact administrator."), 404
    
    try:
        return make_response(
            (open(apk_path, 'rb').read(),
             {'Content-Type': 'application/vnd.android.package-archive',
              'Content-Disposition': 'attachment; filename=ivms-app.apk'})
        )
    except Exception as e:
        return render_template('pricing.html', 
                             modules_config=load_module_config(), 
                             all_modules=ALL_SYSTEM_MODULES,
                             error=f"Error downloading APK: {str(e)}"), 500

@app.route('/reports')
@role_required('user')
def reports():
    return render_template('reports.html', vehicles=get_filtered_vehicles())

@app.route('/vehicle/add', methods=['GET'])
@role_required('user')
def vehicle_form():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Check if user has permission to add vehicles
    if session.get('role') not in ['admin', 'main_admin', 'super_admin'] and not session.get('can_add_vehicle'):
        return render_template('login.html', error="Unauthorized access. You don't have permission to add vehicles.")
    
    return render_template('vehicle_form.html', vehicles=get_filtered_vehicles())

@app.route('/vehicle/add', methods=['POST'])
@role_required('user')
def register_vehicle():
    # Check if user has permission to add vehicles
    if session.get('role') not in ['admin', 'main_admin', 'super_admin'] and not session.get('can_add_vehicle'):
        return render_template('login.html', error="Unauthorized access.", vehicles=get_filtered_vehicles())
    name = request.form.get('name', '').strip()
    unique_id = request.form.get('unique_id', '').strip()
    
    # Check vehicle limit (for admin and main_admin)
    user_info, current_data = get_current_user_data()
    if current_data['role'] in ['admin', 'main_admin']:
        limit = current_data['vehicle_limit']
        if limit is not None:
            # Get vehicles owned by this admin
            all_v = load_vehicles()
            current_count = len([v for v in all_v if v.get('parent_email') == session.get('email')])
            if current_count >= limit:
                return render_template('vehicle_form.html', error=f"Vehicle limit reached ({limit}). Please contact Concept Admin.", vehicles=get_filtered_vehicles())
    device_model = request.form.get('device_model', '').strip()

    if not name or not unique_id:
        return render_template('vehicle_form.html', error="Please enter Name and Unique ID.", vehicles=get_filtered_vehicles())

    current = load_vehicles()
    if any(str(v.get('unique_id')) == unique_id for v in current):
        return render_template('vehicle_form.html', error="Vehicle already registered!", vehicles=get_filtered_vehicles())

    # Validate against backend
    try:
        # Traccar search by uniqueId
        r, _ = try_traccar_get("api/devices", params={"uniqueId": unique_id})
        data = r.json()
        # Ensure we found exactly what we were looking for
        # Traccar API returns a list of devices matching the uniqueId
        found = False
        if isinstance(data, list):
            for d in data:
                if str(d.get('uniqueId')) == unique_id:
                    found = True
                    break
        
        if not found:
             return render_template('vehicle_form.html', error=f"Device {unique_id} not found in backend.", vehicles=get_filtered_vehicles())
             
    except Exception as e:
        return render_template('vehicle_form.html', error=f"Backend validation error: {str(e)}", vehicles=get_filtered_vehicles())

    # If adder is a 'user', the vehicle should belong to their parent admin
    v_parent = session.get('parent_email') if session.get('role') == 'user' else session.get('email')

    new_vehicle = {
        "name": name, 
        "unique_id": unique_id, 
        "device_model": device_model,
        "driver_name": request.form.get('driver_name', '').strip(),
        "parent_email": v_parent
    }
    
    add_vehicle_db(new_vehicle)
    return render_template('vehicle_form.html', success="Vehicle added.", vehicles=get_filtered_vehicles())

@app.route('/vehicle/delete/<unique_id>')
@role_required('user')
def delete_vehicle(unique_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    # Check permission
    if session.get('role') not in ['admin', 'main_admin', 'super_admin'] and not session.get('can_add_vehicle'):
        return render_template('login.html', error="Unauthorized access.")

    # Authorization: can they even see this vehicle?
    allowed = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(unique_id) for v in allowed):
        return render_template('login.html', error="Access denied to this vehicle.")

    delete_vehicle_db(unique_id)
    return redirect(url_for('vehicle_form'))

@app.route('/vehicle/update/<unique_id>', methods=['POST'])
@role_required('user')
def update_vehicle(unique_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Check permission
    if session.get('role') not in ['admin', 'main_admin', 'super_admin'] and not session.get('can_add_vehicle'):
        return render_template('login.html', error="Unauthorized access.")

    # Authorization
    allowed = get_filtered_vehicles()
    if not any(str(v.get('unique_id')) == str(unique_id) for v in allowed):
        return render_template('login.html', error="Access denied to this vehicle.")
        
    name = request.form.get('name', '').strip()
    device_model = request.form.get('device_model', '').strip()
    driver_name = request.form.get('driver_name', '').strip()
    
    if not name:
        return redirect(url_for('vehicle_form', error="Name is required"))

    current = load_vehicles()
    updated = False
    for v in current:
        if str(v.get('unique_id')) == str(unique_id):
            # Verify permission? (Only owner or super admin?)
            # Assuming 'admin' role check is sufficient for now, or check parent_email if stricter needed.
            v['name'] = name
            v['device_model'] = device_model
            v['driver_name'] = driver_name
            updated = True
            break
            
    if updated:
        update_vehicle_db(unique_id, next((v for v in current if str(v.get('unique_id')) == str(unique_id)), {}))
        return redirect(url_for('vehicle_form', success="Vehicle updated successfully"))
    else:
        return redirect(url_for('vehicle_form', error="Vehicle not found"))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/user-manager', methods=['GET', 'POST'])
@role_required('admin')
def user_manager():
    users = load_users()
    modules_config = load_module_config()
    current_email = session.get('email')
    current_role = session.get('role')
    
    # Hierarchy filtering
    if current_role == 'super_admin':
        visible_users = users
    elif current_role == 'main_admin':
        # See self, and anyone with parent_email == self.email, AND their children?
        # For simplicity: See self and direct children. 
        # Requirement says "Create and manage users".
        # Let's show all users where this admin is in the hierarchy chain or is the direct parent
        # For now, simplest is direct parent or parent's parent.
        # But commonly: See users where parent_email is ME.
        visible_users = [u for u in users if u.get('parent_email') == current_email or u.get('email') == current_email]
        # Also include sub-users of my admins? 
        # If I am main_admin, I might have created an 'admin' who has 'users'.
        # Let's simpler approach: Recursive check is better, but maybe just 1 level down for now.
        direct_children = [u.get('email') for u in visible_users]
        grand_children = [u for u in users if u.get('parent_email') in direct_children]
        for gc in grand_children:
            if gc not in visible_users:
                visible_users.append(gc)
    elif current_role == 'admin':
        visible_users = [u for u in users if u.get('parent_email') == current_email or u.get('email') == current_email]
    else:
        visible_users = []

    error = None
    success = None

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            new_email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            name = request.form.get('name', '').strip()
            new_role = request.form.get('role', 'user') # default user
            acct_module = request.form.get('account_module', 'Normal')
            parent = request.form.get('parent_email')
            can_add = request.form.get('can_add_vehicle') == 'on'
            
            mod_data = modules_config.get(acct_module, {})
            
            # Validation
            if not new_email or not password:
                error = "Email and Password required."
            elif any(u.get('email') == new_email for u in users):
                error = "User already exists."
            else:
                # Check limits
                _, current_data = get_current_user_data()
                limit = current_data.get('user_limit')
                if limit is not None:
                    # Count users owned by me
                    my_users_count = len([u for u in users if u.get('parent_email') == current_email])
                    if my_users_count >= limit and current_role != 'super_admin':
                        error = f"User limit reached ({limit}). Upgrade plan."
                
                if not error:
                    # create in Traccar
                    traccar = full_traccar_host()
                    if traccar:
                        s = get_traccar_session()
                        # fetch traccar users to check existence
                        try:
                            # Try to create
                            payload = {
                                "name": name or new_email,
                                "email": new_email,
                                "password": password,
                                "readonly": False,
                                "administrator": (new_role == 'main_admin'), # Only map main_admin to admin?
                                "userLimit": mod_data.get('user_limit', 0) if new_role in ['admin', 'main_admin'] else 0,
                                "deviceLimit": mod_data.get('vehicle_limit', 0) if new_role in ['admin', 'main_admin'] else 0
                            }
                            # If role is super_admin, we might want to set admin flag too?
                            if new_role == 'super_admin': payload['administrator'] = True
                            
                            r_create = s.post(f"{traccar}/api/users", json=payload, timeout=10)
                            save_traccar_cookies(s)
                            
                            if r_create.status_code in [200, 201] or "Unique index or primary key violation" in r_create.text:
                                # Proceed to local save
                                new_user = {
                                    "email": new_email,
                                    "role": new_role,
                                    "name": name or new_email,
                                    "parent_email": parent,
                                    "vehicle_limit": mod_data.get('vehicle_limit', 0) if new_role in ['admin', 'main_admin'] else 0,
                                    "account_module": acct_module if new_role in ['admin', 'main_admin'] else 'Normal',
                                    "can_add_vehicle": can_add if new_role == 'user' else True
                                }

                                add_user_db(new_user)
                                return redirect(url_for('user_manager'))
                            else:
                                error = f"Traccar Error: {r_create.text}"
                        except Exception as e:
                            error = f"Connection Error: {e}"
        
        elif action == 'update_module':
            # Update module logic
             tgt_email = request.form.get('email')
             new_mod = request.form.get('account_module')
             for u in users:
                 if u.get('email') == tgt_email:
                     u['account_module'] = new_mod
                     # Update limits
                     mod_data = modules_config.get(new_mod, {})
                     u['vehicle_limit'] = mod_data.get('vehicle_limit', u.get('vehicle_limit'))
                     u['vehicle_limit'] = mod_data.get('vehicle_limit', u.get('vehicle_limit'))
                     update_user_db(u['email'], u)
                     
                     # Sync to Traccar
                     traccar = full_traccar_host()
                     if traccar:
                         s = get_traccar_session()
                         try:
                             r_all = s.get(f"{traccar}/api/users", timeout=10)
                             if r_all.status_code == 200:
                                 t_users = r_all.json()
                                 t_user = next((tu for tu in t_users if tu.get('email') == tgt_email), None)
                                 if t_user:
                                     t_user['userLimit'] = mod_data.get('user_limit', 0)
                                     t_user['deviceLimit'] = mod_data.get('vehicle_limit', 0)
                                     s.put(f"{traccar}/api/users/{t_user['id']}", json=t_user, timeout=10)
                         except Exception as e:
                             app.logger.error(f"Failed to sync Traccar limits: {e}")
                     break
             return redirect(url_for('user_manager'))

        elif action == 'update_permissions':
             tgt_email = request.form.get('email')
             can_add = request.form.get('can_add_vehicle') == 'on'
             for u in users:
                 if u.get('email') == tgt_email:
                     u['can_add_vehicle'] = can_add
                     update_user_db(u['email'], u)
                     break
             return redirect(url_for('user_manager'))

        elif action == 'delete':
            tgt_email = request.form.get('email')
            if tgt_email:
                # Delete from Traccar
                traccar = full_traccar_host()
                if traccar:
                    s = get_traccar_session()
                    # Find ID
                    try:
                        r_all = s.get(f"{traccar}/api/users", timeout=10)
                        if r_all.status_code == 200:
                            t_users = r_all.json()
                            t_id = next((tu['id'] for tu in t_users if tu.get('email') == tgt_email), None)
                            if t_id:
                                s.delete(f"{traccar}/api/users/{t_id}")
                    except: pass
                
                delete_user_db(tgt_email)
                return redirect(url_for('user_manager'))

    # Prepare data for template
    # potential parent admins: 
    # if super_admin: all main_admins and admins
    # if main_admin: self and my admins
    admins = []
    if current_role == 'super_admin':
        admins = [u for u in users if u.get('role') in ['main_admin', 'admin']]
        # Also add self? Super admin usually doesn't need to be parent of user directly if they have main_admins, but possible.
        admins.append({'name': 'Super Admin', 'email': session.get('email')}) 
    elif current_role == 'main_admin':
        admins = [u for u in visible_users if u.get('role') == 'admin']
        admins.append({'name': session.get('user_name'), 'email': session.get('email')})
    elif current_role == 'admin':
        admins = [{'name': session.get('user_name'), 'email': session.get('email')}]

    return render_template('user_manager.html', users=visible_users, error=error, modules_config=modules_config, role=current_role, admins=admins)

def render_report_logic(forced_report_type=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    vehicles = get_filtered_vehicles()
    
    # Filter Inputs
    period = request.args.get('period', 'Today')
    filter_uid = request.args.get('unique_id')
    filter_group = request.args.get('groups')
    
    if forced_report_type:
        report_type = forced_report_type
    else:
        report_type = request.args.get('report_type', 'Trips')
    
    # Calculate Date Range based on Period
    # ... (rest of date calculation remains same)
    now = datetime.now()
    if period == 'Yesterday':
        start_dt = now - timedelta(days=1)
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999)
    elif period == 'This Week':
        start_dt = now - timedelta(days=now.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'This Month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'Custom':
        from_str = request.args.get('from')
        to_str = request.args.get('to')
        try:
            if from_str: start_dt = datetime.strptime(from_str, '%Y-%m-%dT%H:%M')
            else: start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if to_str: end_dt = datetime.strptime(to_str, '%Y-%m-%dT%H:%M')
            else: end_dt = now
        except:
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now
    else: # Default to Today
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now

    from_str_display = start_dt.strftime('%Y-%m-%dT%H:%M')
    to_str_display = end_dt.strftime('%Y-%m-%dT%H:%M')
    traccar_from = start_dt.isoformat() + "Z"
    traccar_to = end_dt.isoformat() + "Z"

    report_data = []
    traccar = full_traccar_host()
    if not traccar:
         return render_template('pre_reg_report.html', report_data=[], from_date=from_str_display, to_date=to_str_display, error="Traccar host not configured", vehicles=vehicles)

    s = get_traccar_session()
    
    # Read stop threshold from request parameters, fall back to server config
    try:
        stop_threshold_mins = int(request.args.get('stop_threshold', ''))
    except (ValueError, TypeError):
        cfg = load_server_config()
        stop_threshold_mins = int(cfg.get('stop_threshold', 5))

    # 1. Get All Devices to map Unique ID -> Internal ID
    device_map = {} 
    try:
        r_dev = s.get(f"{traccar}/api/devices", timeout=10)
        save_traccar_cookies(s)
        if r_dev.status_code == 200:
            for d in r_dev.json():
                device_map[d.get("uniqueId")] = d.get("id")
        else:
            app.logger.error(f"Failed to fetch devices: status {r_dev.status_code}")
    except Exception as e:
        app.logger.error(f"Failed to fetch devices: {e}")
    
    # Log the device map for debugging


    # 2. Build summary report data (always needed for the top table)
    if report_type != 'Combined':
        for v in vehicles:
            unique_id = v.get("unique_id")
            if filter_uid and str(unique_id) != str(filter_uid):
                continue
            internal_id = device_map.get(unique_id)
            row = {"name": v.get("name"), "unique_id": unique_id, "max_speed": 0, "total_distance": 0}
            if internal_id:
                try:
                    url = f"{traccar}/api/reports/summary?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_sum = s.get(url, headers={'Accept': 'application/json'}, timeout=10)
                    if r_sum.status_code == 200:
                        data = r_sum.json()
                        if data:
                            item = data[0]
                            knots = item.get("maxSpeed") or 0
                            meters = item.get("distance") or 0
                            row["max_speed"] = round(float(knots) * 1.852, 2)
                            row["total_distance"] = round(float(meters) / 1000, 2)
                except Exception as e:
                    app.logger.error(f"Failed to fetch summary for {unique_id}: {e}")
            report_data.append(row)

    # Column Filters
    # Updated list based on user request
    all_available_cols = ['startTime', 'startOdometer', 'startAddress', 'endTime', 'endOdometer', 'endAddress', 'distance', 'averageSpeed', 'maxSpeed', 'duration', 'spentFuel', 'driverName']
    selected_columns = []
    
    # Check if any column is explicitly selected
    has_any_col_param = any(request.args.get(f'col_{col}') for col in all_available_cols)
    
    if has_any_col_param:
        # User has made a selection, only show checked columns
        for col in all_available_cols:
            if request.args.get(f'col_{col}'):
                selected_columns.append(col)
    else:
        # No selection made (first load), show a sensible default set
        # Don't show all columns by default
        selected_columns = []  # Empty means template will use its default view
    
    
    trip_data = []
    stop_data_on = []
    stop_data_off = []
    combined_data = []
    route_data = []
    
    summary_distance = 0
    summary_duration = 0
    summary_avg_speed = 0
    summary_idle_time = 0

    # If a vehicle is selected, fetch detailed data
    if filter_uid:
        internal_id = device_map.get(filter_uid)
        if internal_id and traccar:
            if report_type == 'Trips':
                try:
                    url = f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_trips = s.get(url, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_trips.status_code == 200:
                        try:
                            raw_trips = r_trips.json()
                        except:
                            raw_trips = []
                        
                        # Manual Trip Merging based on Stop Threshold
                        # Traccar already segments by its internal rule (usually 5 mins).
                        # If user wants e.g. 15 mins, we merge sequences separated by less than 15.
                        processed_trips = []
                        if raw_trips:
                            # Sort by startTime just in case
                            raw_trips.sort(key=lambda x: x.get('startTime', ''))
                            
                            curr = raw_trips[0]
                            for i in range(1, len(raw_trips)):
                                next_t = raw_trips[i]
                                
                                # Convert times to compare
                                try:
                                    # Handle Zulu time or offset
                                    end_str = curr['endTime'].replace('Z', '+00:00').split('.')[0]
                                    start_str = next_t['startTime'].replace('Z', '+00:00').split('.')[0]
                                    
                                    t_end = datetime.fromisoformat(end_str)
                                    t_start = datetime.fromisoformat(start_str)
                                    gap_sec = (t_start - t_end).total_seconds()
                                    
                                    if gap_sec < (stop_threshold_mins * 60):
                                        # MERGE: Extend current trip to include next one
                                        curr['endTime'] = next_t['endTime']
                                        curr['distance'] += next_t.get('distance', 0)
                                        # duration in ms
                                        # In merging, we include the idle time in the duration to be consistent
                                        curr['duration'] = next_t.get('duration', 0) + curr.get('duration', 0) + (gap_sec * 1000)
                                        curr['maxSpeed'] = max(curr.get('maxSpeed', 0), next_t.get('maxSpeed', 0))
                                        # Start odometer stays same, end odometer updates
                                        curr['endOdometer'] = next_t.get('endOdometer', 0)
                                        curr['endEngineHours'] = next_t.get('endEngineHours', 0)
                                        curr['spentFuel'] = curr.get('spentFuel', 0) + next_t.get('spentFuel', 0)
                                        # Update end address
                                        curr['endAddress'] = next_t.get('endAddress')
                                    else:
                                        processed_trips.append(curr)
                                        curr = next_t
                                except Exception:
                                    processed_trips.append(curr)
                                    curr = next_t
                            processed_trips.append(curr)
                        
                        for t in processed_trips:
                            dist_km = round((t.get('distance') or 0) / 1000, 2)
                            avg_spd_kmh = round((t.get('averageSpeed') or 0) * 1.852, 2)
                            max_spd_kmh = round((t.get('maxSpeed') or 0) * 1.852, 2)
                            
                            # Engine hours usually in milliseconds or hours depending on version
                            # spentFuel is usually in liters
                            
                            # Get driver name from local vehicle data
                            driver_name = '-' 
                            for v in vehicles:
                                if str(v.get('unique_id')) == str(filter_uid):
                                    driver_name = v.get('driver_name', '-')
                                    break

                            trip_data.append({
                                'deviceName': t.get('deviceName'),
                                'startTime': t.get('startTime'),
                                'endTime': t.get('endTime'),
                                'distance': f"{dist_km} km",
                                'averageSpeed': f"{avg_spd_kmh} km/h",
                                'maxSpeed': f"{max_spd_kmh} km/h",
                                'startOdometer': f"{round((t.get('startOdometer') or 0) / 1000, 2)} km",
                                'endOdometer': f"{round((t.get('endOdometer') or 0) / 1000, 2)} km",
                                'startAddress': t.get('startAddress', 'N/A'),
                                'endAddress': t.get('endAddress', 'N/A'),
                                'spentFuel': f"{round((t.get('spentFuel') or 0), 2)} L",
                                'duration': t.get('duration'),
                                'driverName': driver_name
                            })
                except Exception as e:
                    app.logger.error(f"Failed to fetch trips for {filter_uid}: {e}")
            
            elif report_type == 'Stops':
                try:
                    url = f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_stops = s.get(url, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_stops.status_code == 200:
                        raw_stops = r_stops.json()
                        for s_item in raw_stops:
                            # Filter by threshold (milliseconds)
                            dur_ms = s_item.get('duration') or 0
                            if dur_ms < (stop_threshold_mins * 60 * 1000):
                                continue
                            
                            engine_status = "OFF"
                            # Standard Traccar Stops API includes 'engine' boolean
                            if s_item.get('engine') is True: engine_status = "ON"
                            
                            dist_meters = s_item.get('totalDistance') or 0
                            odo_km = round(dist_meters / 1000, 2)
                            
                            row = {
                                'deviceName': s_item.get('deviceName'),
                                'startTime': s_item.get('startTime'),
                                'endTime': s_item.get('endTime'),
                                'duration': s_item.get('duration'),
                                'address': s_item.get('address', 'N/A'),
                                'odometer': odo_km,
                                'engine': engine_status,
                                'spentFuel': f"{round((s_item.get('spentFuel') or 0), 2)} L",
                                'engineHours': f"{round((s_item.get('engineHours') or 0) / 3600000, 2)} h"
                            }
                            
                            if engine_status == 'ON':
                                stop_data_on.append(row)
                            else:
                                stop_data_off.append(row)
                except Exception as e:
                    app.logger.error(f"Failed to fetch stops for {filter_uid}: {e}")

            elif report_type == 'Combined':
                # Combined report: Route (for map) + Events (for table) + Summary metrics
                try:
                    # 1. Route (Positions)
                    url_route = f"{traccar}/api/reports/route?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_route = s.get(url_route, headers={'Accept': 'application/json'}, timeout=20)
                    save_traccar_cookies(s)
                    if r_route.status_code == 200:
                        route_data = r_route.json()

                    # 2. Fetch Trip Summary for metrics
                    summary_distance = 0
                    summary_duration = 0
                    summary_avg_speed = 0
                    summary_idle_time = 0
                    
                    url_trips = f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_trips = s.get(url_trips, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_trips.status_code == 200:
                        trips = r_trips.json()
                        total_distance_m = 0
                        total_duration_ms = 0
                        total_speeds = []
                        
                        for trip in trips:
                            total_distance_m += trip.get('distance', 0)
                            total_duration_ms += trip.get('duration', 0)
                            avg_spd = trip.get('averageSpeed', 0)
                            if avg_spd > 0:
                                total_speeds.append(avg_spd)
                        
                        summary_distance = round(total_distance_m / 1000, 2)  # km
                        summary_duration = total_duration_ms  # milliseconds
                        if total_speeds:
                            summary_avg_speed = round(sum(total_speeds) / len(total_speeds) * 1.852, 2)  # km/h
                    
                    # Calculate idle time from stops
                    url_stops = f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_stops = s.get(url_stops, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_stops.status_code == 200:
                        stops = r_stops.json()
                        total_idle_ms = 0
                        for stop in stops:
                            # Only count engine ON stops as idle
                            if stop.get('engine') is True:
                                total_idle_ms += stop.get('duration', 0)
                        summary_idle_time = total_idle_ms  # milliseconds

                    # 3. Events with position enrichment
                    url_events = f"{traccar}/api/reports/events?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_events = s.get(url_events, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_events.status_code == 200:
                        raw_events = r_events.json()
                        
                        dev_name = 'Unknown'
                        matches = [v['name'] for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]
                        if matches:
                            dev_name = matches[0]
                        elif report_data:
                            dev_name = report_data[0]['name']

                        # Create position lookup by timestamp
                        position_map = {}
                        if route_data:
                            for pos in route_data:
                                fix_time = pos.get('fixTime')
                                if fix_time:
                                    position_map[fix_time] = pos
                        
                        for ev in raw_events:
                            event_time = ev.get('eventTime')
                            
                            # Try to find matching position by exact timestamp
                            position = position_map.get(event_time)
                            
                            # If no exact match, find nearest position within 60 seconds
                            if not position and route_data and event_time:
                                try:
                                    ev_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00').split('.')[0])
                                    min_diff = float('inf')
                                    nearest_pos = None
                                    
                                    for pos in route_data:
                                        pos_time = pos.get('fixTime')
                                        if pos_time:
                                            pos_dt = datetime.fromisoformat(pos_time.replace('Z', '+00:00').split('.')[0])
                                            diff = abs((ev_dt - pos_dt).total_seconds())
                                            if diff < min_diff and diff < 60:  # within 60 seconds
                                                min_diff = diff
                                                nearest_pos = pos
                                    
                                    if nearest_pos:
                                        position = nearest_pos
                                except Exception:
                                    pass
                            
                            combined_data.append({
                                'deviceName': dev_name,
                                'fixTime': event_time,
                                'type': ev.get('type'),
                                'attributes': ev.get('attributes', {}),
                                'position': position  # Add position data
                            })
                        
                        # Sort events by time
                        combined_data.sort(key=lambda x: x['fixTime'] or '')
                except Exception as e:
                    app.logger.error(f"Failed to fetch combined data for {filter_uid}: {e}")

    # Fetch Groups to populate the filter
    groups = []
    try:
        r_grp = s.get(f"{traccar}/api/groups", timeout=10)
        save_traccar_cookies(s)
        if r_grp.status_code == 200:
            groups = r_grp.json()
    except Exception as e:
        app.logger.error(f"Failed to fetch groups: {e}")

    # Initialize summary metrics if not set (for non-Combined reports)


    return render_template('pre_reg_report.html', 
                          report_data=report_data, 
                          trip_data=trip_data, 
                          stop_data_on=stop_data_on,
                          stop_data_off=stop_data_off,
                          combined_data=combined_data,
                          route_data=route_data,
                          summary_distance=summary_distance,
                          summary_duration=summary_duration,
                          summary_avg_speed=summary_avg_speed,
                          summary_idle_time=summary_idle_time,
                          from_date=from_str_display, 
                          to_date=to_str_display, 
                          vehicles=vehicles, 
                          groups=groups,
                          selected_period=period, 
                          selected_uid=filter_uid,
                          selected_group=filter_group,
                          selected_report_type=report_type,
                          selected_threshold=str(stop_threshold_mins),
                          selected_columns=selected_columns,
                          role=session.get('role'))

@app.route('/pre_reg_report')
def pre_reg_report():
    return render_report_logic()

@app.route('/reports/trips')
def report_trips():
    return render_report_logic('Trips')

@app.route('/reports/stops')
def report_stops():
    return render_report_logic('Stops')

@app.route('/reports/combined')
def report_combined():
    return render_report_logic('Combined')

@app.route('/server-settings', methods=['GET', 'POST'])
@role_required('main_admin')
def server_settings():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    cfg = load_server_config()
    if request.method == 'POST':
        new_ip = request.form.get('server_ip', '').strip()
        new_threshold = request.form.get('stop_threshold', '5').strip()
        if new_ip:
            if new_ip.startswith("http://") or new_ip.startswith("https://"):
                new_ip = new_ip.split("://", 1)[1]
            servers = cfg.get("servers", [])
            if new_ip not in servers:
                servers.append(new_ip)
            cfg["servers"] = servers
            cfg["active_ip"] = new_ip
        
        if new_threshold.isdigit():
            cfg["stop_threshold"] = int(new_threshold)
            
        save_server_config(cfg)
        return redirect(url_for('server_settings'))
    return render_template('server_settings.html', config=cfg)

# -------------------------
# JSON endpoints used by frontend
# -------------------------
@app.route('/vehicle-list-json')
def vehicle_list_json():
    return jsonify({"vehicles": get_filtered_vehicles()})

# Primary devices proxy with UID filter handling
@app.route('/api/devices')
@role_required('user')
def devices_proxy():
    if not session.get('logged_in'):
        return jsonify({'error': 'unauthorized'}), 401

    traccar = full_traccar_host()
    if not traccar:
        return jsonify({'error': 'host_not_configured'}), 500

    s = get_traccar_session()

    uid = request.args.get("uid")

    try:
        # Fetch devices
        r = s.get(f"{traccar}/api/devices", timeout=10)
        save_traccar_cookies(s)
        if r.status_code != 200:
            return jsonify({'error': 'bad_status_devices'}), 500
        devices = r.json()

        # Filter by authorized vehicles from IVMS config
        v_list = get_filtered_vehicles()
        allowed_uids = {str(v.get('unique_id')) for v in v_list}
        devices = [d for d in devices if str(d.get("uniqueId")) in allowed_uids]

        if uid:
            devices = [d for d in devices if str(d.get("uniqueId")) == str(uid)]

        # Fetch latest positions ONLY if uid is provided (for map/report)
        # Optimization: Do not fetch positions for simple device lists (like notifications)
        if uid:
            device_ids = [d["id"] for d in devices if d.get("id")]
            if device_ids:
                pos_params = {"deviceId": device_ids}  # Supports multiple
                pos_r = s.get(f"{traccar}/api/positions", params=pos_params, timeout=10)
                save_traccar_cookies(s)
                if pos_r.status_code == 200:
                    positions = pos_r.json()
                    pos_map = {p["deviceId"]: p for p in positions}
                    for d in devices:
                        if d["id"] in pos_map:
                            d["position"] = pos_map[d["id"]]

        return jsonify(devices)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/export')
@role_required('user')
def export_report():
    # Filter Inputs
    period = request.args.get('period', 'Today')
    report_type = request.args.get('report_type', 'Trips')
    filter_uid = request.args.get('unique_id')
    filter_group = request.args.get('groups')
    
    # NEW: Stop Threshold (mins)
    try:
        stop_threshold_mins = int(request.args.get('stop_threshold', 5))
    except ValueError:
        stop_threshold_mins = 5

    start_dt, end_dt = get_period_dates(period, request.args.get('from'), request.args.get('to'))
    traccar_from = start_dt.isoformat() + "Z"
    traccar_to = end_dt.isoformat() + "Z"

    vehicles = get_filtered_vehicles()
    target_vehicles = vehicles
    if filter_uid:
        target_vehicles = [v for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]

    if not target_vehicles:
        return "No authorized vehicles found", 403

    s = get_traccar_session()
    traccar = full_traccar_host()

    si = io.StringIO()
    cw = csv.writer(si)

    if report_type == 'Trips':
        cw.writerow(['Device Name', 'Start Time', 'End Time', 'Distance', 'Avg Speed', 'Max Speed', 'Duration'])
        for v in target_vehicles:
            uid = v.get('unique_id')
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid})
            if r_dev.status_code == 200 and r_dev.json():
                internal_id = r_dev.json()[0]['id']
                r_trips = s.get(f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}")
                if r_trips.status_code == 200:
                    raw_trips = r_trips.json()
                    raw_trips.sort(key=lambda x: x.get('startTime', ''))
                    
                    processed = []
                    if raw_trips:
                        curr = raw_trips[0]
                        for i in range(1, len(raw_trips)):
                            next_t = raw_trips[i]
                            try:
                                t_end = datetime.fromisoformat(curr['endTime'].replace('Z', '+00:00').split('.')[0])
                                t_start = datetime.fromisoformat(next_t['startTime'].replace('Z', '+00:00').split('.')[0])
                                gap_sec = (t_start - t_end).total_seconds()
                                if gap_sec < (stop_threshold_mins * 60):
                                    curr['endTime'] = next_t['endTime']
                                    curr['distance'] += (next_t.get('distance') or 0)
                                    curr['duration'] = (next_t.get('duration') or 0) + (curr.get('duration') or 0) + (gap_sec * 1000)
                                    curr['maxSpeed'] = max((curr.get('maxSpeed') or 0), (next_t.get('maxSpeed') or 0))
                                else:
                                    processed.append(curr)
                                    curr = next_t
                            except Exception:
                                processed.append(curr)
                                curr = next_t
                        processed.append(curr)

                    for t in processed:
                        cw.writerow([
                            t.get('deviceName'),
                            t.get('startTime'),
                            t.get('endTime'),
                            f"{round((t.get('distance') or 0)/1000, 2)} km",
                            f"{round((t.get('averageSpeed') or 0)*1.852, 2)} km/h",
                            f"{round((t.get('maxSpeed') or 0)*1.852, 2)} km/h",
                            f"{round((t.get('duration') or 0)/3600000, 2)} h"
                        ])
    else: # Stops
        cw.writerow(['Device Name', 'Start Time', 'End Time', 'Duration', 'Engine', 'Address'])
        for v in target_vehicles:
            uid = v.get('unique_id')
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid})
            if r_dev.status_code == 200 and r_dev.json():
                internal_id = r_dev.json()[0]['id']
                r_stops = s.get(f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}")
                if r_stops.status_code == 200:
                    for st in r_stops.json():
                        dur_ms = st.get('duration') or 0
                        if dur_ms < (stop_threshold_mins * 60 * 1000):
                            continue
                        cw.writerow([
                            st.get('deviceName'),
                            st.get('startTime'),
                            st.get('endTime'),
                            f"{round(dur_ms/3600000, 2)} h",
                            "ON" if st.get('engine') else "OFF",
                            st.get('address', 'N/A')
                        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{report_type.lower()}_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/api/dashboard/devices')
@role_required('user')
def api_dashboard_devices():
    tr = full_traccar_host()
    s = get_traccar_session()
    try:
        r = s.get(f"{tr}/api/devices", timeout=10)
        save_traccar_cookies(s)
        if r.status_code != 200:
            return jsonify({'error': 'bad_status'}), 500
        
        devices = r.json()
        
        # Filter based on authorized vehicles
        v_list = get_filtered_vehicles()
        allowed_uids = {str(v.get('unique_id')) for v in v_list}
        
        filtered = [d for d in devices if str(d.get('uniqueId')) in allowed_uids]
        return jsonify(filtered)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dashboard/groups')
@role_required('user')
def api_dashboard_groups():
    tr = full_traccar_host()
    s = get_traccar_session()
    try:
        r = s.get(f"{tr}/api/groups", timeout=10)
        save_traccar_cookies(s)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception:
        pass
    return jsonify([])

@app.route('/api/dashboard/combined-report')
@role_required('user')
def api_combined_report():
    device_id = request.args.get('deviceId')
    if not device_id:
        return jsonify({'error': 'no_id'}), 400
    
    # To be safe, we should really verify.
    # For now, proceeding with date range check.

    from_param = request.args.get('from')
    to_param = request.args.get('to')
    if not from_param or not to_param:
        return jsonify({'error': 'missing_date_range'}), 400

    tr = full_traccar_host()
    s = get_traccar_session()

    # Traccar expects ISO with Z or offset, colons are fine
    url = f"{tr}/api/reports/trips?deviceId={device_id}&from={from_param}&to={to_param}"
    # Note: There is no /api/reports/combined in standard Traccar.
    # If you need events/trips/stops, call separate endpoints or adjust frontend.
    # Here using trips as example; duplicate for events/stops if needed.

    try:
        r = s.get(url, timeout=15)
        save_traccar_cookies(s)
        if r.status_code != 200:
            return jsonify({'trips': [], 'error': f'bad_status_{r.status_code}'})
        data = r.json()
        return jsonify({'trips': data, 'events': [], 'stops': []})
    except Exception as e:
        return jsonify({'trips': [], 'events': [], 'stops': [], 'error': str(e)})

@app.route('/api/dashboard/distance')
@role_required('user')
def api_dashboard_distance():
    device_id = request.args.get('id')
    if not device_id:
        return jsonify({'error': 'missing_device_id'}), 400

    tr = full_traccar_host()
    s = get_traccar_session()

    from_param = request.args.get('from')
    to_param = request.args.get('to')
    
    if not from_param or not to_param:
        now = datetime.utcnow()
        start_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
        end_iso = now.isoformat() + "Z"
    else:
        start_iso = from_param
        end_iso = to_param

    url = f"{tr}/api/reports/summary?deviceId={device_id}&from={start_iso}&to={end_iso}"

    try:
        r = s.get(url, timeout=12)
        save_traccar_cookies(s)
        if r.status_code != 200 or not r.json():
            return jsonify({'distance': 0})
        meters = r.json()[0].get('distance', 0)
        return jsonify({'distance': round(meters / 1000, 2)})
    except Exception as e:
        return jsonify({'distance': 0, 'error': str(e)})

@app.route('/api/debug/device/<uid>')
@role_required('admin')
def debug_device(uid):
    traccar = full_traccar_host()
    s = get_traccar_session()
    
    result = {
        'uid': uid,
        'traccar_host': traccar,
        'device_data': None,
        'position_data': None,
        'errors': []
    }
    
    try:
        r = s.get(f"{traccar}/api/devices", timeout=10)
        save_traccar_cookies(s)
        if r.status_code != 200:
            result['errors'].append(f"Devices API status {r.status_code}")
            return jsonify(result)
        
        devices = r.json()
        device = next((d for d in devices if str(d.get("uniqueId")) == str(uid)), None)
        
        if device:
            result['device_data'] = device
            dev_id = device.get("id")
            if dev_id:
                pos_r = s.get(f"{traccar}/api/positions?deviceId={dev_id}", timeout=10)
                save_traccar_cookies(s)
                if pos_r.status_code == 200:
                    result['position_data'] = pos_r.json()
                else:
                    result['errors'].append(f"Position API status {pos_r.status_code}")
        else:
            result['errors'].append(f"Device with UID {uid} not found")
            result['available_devices'] = [d.get("uniqueId") for d in devices if d.get("uniqueId")]
    except Exception as e:
        result['errors'].append(str(e))
    
    return jsonify(result)

# -------------------------
# Run
# -------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
