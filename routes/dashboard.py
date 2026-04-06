import os
from flask import Blueprint, render_template, request, redirect, url_for, session, make_response
from auth.utils import role_required
from models.database import load_module_config, save_module_config, load_server_config

dashboard_bp = Blueprint('dashboard', __name__)

# Constants (moved from app.py but here for simplicity or centralized later)
ALL_SYSTEM_MODULES = [
    "dashboard", "reports", "pre_reg_report", "vehicle_add", "user_manager", "notifications", "servers",
    "dashboard_stats", "dashboard_charts", "dashboard_map", "dashboard_big_chart", "dashboard_alerts",
    "reports_trips", "reports_stops", "reports_combined", "pricing"
]

@dashboard_bp.route('/dashboard')
def dashboard_home():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    return render_template('dashboard.html')

@dashboard_bp.route('/dashboard-config', methods=['GET', 'POST'])
@role_required('main_admin')
def dashboard_config():
    modules_config = load_module_config()
    dashboard_modules = [m for m in ALL_SYSTEM_MODULES if m.startswith('dashboard') or m == 'pricing']
    
    if request.method == 'POST':
        action = request.form.get('action')
        plan_name = request.form.get('plan_name')
        if action == 'update' and plan_name in modules_config:
            try:
                current_enabled = set(modules_config[plan_name].get('enabled_modules', []))
                submitted = set(request.form.getlist('enabled_modules'))
                for m in dashboard_modules:
                    if m in current_enabled: current_enabled.remove(m)
                for m in submitted: current_enabled.add(m)
                modules_config[plan_name]['enabled_modules'] = list(current_enabled)
                save_module_config(modules_config)
                return redirect(url_for('dashboard.dashboard_config', success=f"Dashboard settings for {plan_name} updated."))
            except Exception as e:
                return render_template('dashboard_config.html', modules_config=modules_config, doc_modules=dashboard_modules, error=f"Error: {e}")
    return render_template('dashboard_config.html', modules_config=modules_config, doc_modules=dashboard_modules, success=request.args.get('success'))

@dashboard_bp.route('/plan-manager', methods=['GET', 'POST'])
@role_required('main_admin')
def plan_manager():
    modules_config = load_module_config()
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
                return redirect(url_for('dashboard.plan_manager', success=f"Plan {plan_name} updated successfully."))
            except Exception as e:
                return render_template('plan_manager.html', modules_config=modules_config, all_modules=ALL_SYSTEM_MODULES, error=f"Error updating plan: {e}")
    return render_template('plan_manager.html', modules_config=modules_config, all_modules=ALL_SYSTEM_MODULES, success=request.args.get('success'))

@dashboard_bp.route('/pricing')
@role_required('main_admin')
def pricing():
    modules_config = load_module_config()
    return render_template('pricing.html', modules_config=modules_config, all_modules=ALL_SYSTEM_MODULES)

@dashboard_bp.route('/download/apk')
@role_required('main_admin')
def download_apk():
    APP_ROOT_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apk_path = os.path.join(APP_ROOT_PROJECT, 'static', 'downloads', 'ivms-app.apk')
    if not os.path.exists(apk_path):
        return render_template('pricing.html', modules_config=load_module_config(), all_modules=ALL_SYSTEM_MODULES, error="APK file not found."), 404
    try:
        return make_response((open(apk_path, 'rb').read(), {'Content-Type': 'application/vnd.android.package-archive', 'Content-Disposition': 'attachment; filename=ivms-app.apk'}))
    except Exception as e:
        return render_template('pricing.html', modules_config=load_module_config(), all_modules=ALL_SYSTEM_MODULES, error=f"Error: {str(e)}"), 500
