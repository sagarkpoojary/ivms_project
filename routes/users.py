from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, jsonify
from werkzeug.security import generate_password_hash
from auth.utils import role_required, get_current_user_data, get_all_descendant_users
from models.database import load_users, load_module_config, add_user_db, update_user_db, delete_user_db
from services.limit_validator import validate_user_creation_limit, get_usage_stats

users_bp = Blueprint('users', __name__)

@users_bp.route('/user-manager', methods=['GET', 'POST'])
@role_required('admin')
def user_manager():
    try:
        users = load_users()
        modules_config = load_module_config()
        current_email = session.get('email')
        current_role = session.get('role')
        user_info, current_data = get_current_user_data()
        current_company = current_data.get('company_name')
        
        # 1. VISIBILITY RULES & GROUPING
        if current_role == 'super_admin':
            visible_users = [u for u in users if u.get('role') == 'main_admin']
            grouped_users = None
        elif current_role == 'main_admin':
            all_descendants = get_all_descendant_users(current_email)
            # Group by Company Admin (Sub-categories)
            company_admins = [u for u in all_descendants if u.get('role') == 'admin' and u.get('parent_email') == current_email]
            
            grouped_users = []
            covered_emails = set()
            
            for ca in company_admins:
                children = [u for u in all_descendants if u.get('parent_email') == ca['email']]
                grouped_users.append({
                    'admin': ca,
                    'children': children
                })
                covered_emails.add(ca['email'])
                for c in children: covered_emails.add(c['email'])
                
            others = [u for u in all_descendants if u['email'] not in covered_emails]
            if others:
                grouped_users.append({
                    'admin': {'name': 'Direct / Miscellaneous', 'email': 'N/A', 'company_name': 'Various', 'is_virtual': True},
                    'children': others
                })
            visible_users = all_descendants
        elif current_role == 'admin':
            # Company Admin sees themselves and users they created directly
            visible_users = [u for u in users if u.get('email') == current_email or u.get('parent_email') == current_email]
            grouped_users = None
        else:
            visible_users = []
            grouped_users = None

        error = None
        
        if request.method == 'POST':
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            action = request.form.get('action')
            
            if action == 'add':
                new_email = request.form.get('email', '').strip()
                password = request.form.get('password', '').strip()
                name = request.form.get('name', '').strip()
                new_role = request.form.get('role', 'user')
                acct_module = 'Normal' # Default
                parent = current_email
                
                # 2. ROLE CREATION RULES & VALIDATION
                allowed_roles = []
                if current_role == 'super_admin':
                    allowed_roles = ['main_admin']
                    new_role = 'main_admin' # Force it
                    company_name = request.form.get('company_name', '').strip()
                    acct_module = 'Premium' 
                elif current_role == 'main_admin':
                    allowed_roles = ['admin']
                    new_role = 'admin' # Force it
                    company_name = request.form.get('company_name', '').strip()
                    acct_module = 'Normal'
                elif current_role == 'admin':
                    allowed_roles = ['user']
                    new_role = 'user' # Force it to user only
                    company_name = current_company # Inherit
                
                if new_role == 'super_admin' or new_role not in allowed_roles:
                    error = f"Unauthorized role creation: {new_role}"
                elif not new_email or not password:
                    error = "Email and Password required."
                elif any(u.get('email') == new_email for u in users):
                    error = "User already exists."
                
                if not error and (current_role == 'super_admin' or current_role == 'main_admin'):
                    if not company_name:
                        error = "Company Name is required."
                    elif any(u.get('company_name') == company_name and u.get('role') in ['admin', 'main_admin', 'super_admin'] for u in users):
                        error = f"Company Name '{company_name}' is already taken."

                if not error:
                    try:
                        v_lim = int(request.form.get('vehicle_limit', 1))
                        u_lim = int(request.form.get('user_limit', 0))
                    except ValueError:
                        error = "Limits must be numeric."
                    
                    if not error and current_role != 'super_admin':
                        my_v_limit = current_data.get('vehicle_limit')
                        my_u_limit = current_data.get('user_limit')
                        if my_v_limit is not None and v_lim > my_v_limit:
                            error = f"Cannot assign {v_lim} vehicles (Your limit: {my_v_limit})."
                        if my_u_limit is not None and u_lim > my_u_limit:
                            error = f"Cannot assign {u_lim} users (Your limit: {my_u_limit})."

                if not error:
                    can_create, current_count, limit_error = validate_user_creation_limit(
                        current_email, 
                        current_role, 
                        current_data.get('user_limit')
                    )
                    if not can_create:
                        error = limit_error

                if not error:
                    new_user = {
                        "email": new_email,
                        "role": new_role,
                        "name": name or new_email,
                        "company_name": company_name,
                        "parent_email": parent,
                        "created_by": current_email,
                        "vehicle_limit": v_lim,
                        "user_limit": u_lim,
                        "account_module": acct_module,
                        "password_hash": generate_password_hash(password)
                    }
                    add_user_db(new_user)
                    if is_ajax:
                        return jsonify({'success': True, 'message': 'User created successfully'})
                    return redirect(url_for('users.user_manager'))
            
            if error and is_ajax:
                return jsonify({'success': False, 'error': error}), 400
            
            elif action == 'update_profile':
                tgt_email = request.form.get('email', '').strip()
                new_name = request.form.get('name')
                target_user = next((u for u in users if u.get('email', '').strip().lower() == tgt_email.lower()), None)
                
                if target_user:
                    if target_user not in visible_users and tgt_email != current_email:
                        error = "Unauthorized update."
                    else:
                        updates = {}
                        if new_name is not None:
                            updates['name'] = new_name.strip()
                        
                        if current_role in ['super_admin', 'main_admin']:
                            new_company = request.form.get('company_name')
                            if new_company:
                                new_company = new_company.strip()
                                if any(u.get('company_name') == new_company and u.get('email') != tgt_email for u in users if u.get('role') in ['main_admin', 'admin']):
                                    error = "Company Name already taken."
                                else:
                                    updates['company_name'] = new_company
                                    if target_user.get('role') == 'admin':
                                        to_process = [tgt_email]
                                        while to_process:
                                            cp = to_process.pop(0)
                                            children = [u for u in users if u.get('parent_email') == cp]
                                            for c in children:
                                                update_user_db(c['email'], {'company_name': new_company})
                                                if c.get('role') == 'admin': to_process.append(c['email'])

                        if not error and updates:
                            v_lim_new = request.form.get('vehicle_limit')
                            u_lim_new = request.form.get('user_limit')
                            if v_lim_new is not None or u_lim_new is not None:
                                 try:
                                    if v_lim_new:
                                        v_val = int(v_lim_new)
                                        if current_role != 'super_admin':
                                            parent_v_limit = current_data.get('vehicle_limit')
                                            if parent_v_limit is not None and v_val > parent_v_limit:
                                                error = f"Limit exceeded: Max {parent_v_limit} vehicles."
                                        if not error: updates['vehicle_limit'] = v_val
                                    
                                    if not error and u_lim_new:
                                        u_val = int(u_lim_new)
                                        if current_role != 'super_admin':
                                            parent_u_limit = current_data.get('user_limit')
                                            if parent_u_limit is not None and u_val > parent_u_limit:
                                                error = f"Limit exceeded: Max {parent_u_limit} users."
                                        if not error: updates['user_limit'] = u_val
                                 except ValueError:
                                    error = "Limits must be numerical."

                        if not error and updates:
                            update_user_db(tgt_email, updates)
                            if tgt_email == current_email:
                                if 'name' in updates: session['user_name'] = updates['name']
                                if 'vehicle_limit' in updates: session['vehicle_limit'] = updates['vehicle_limit']
                                if 'user_limit' in updates: session['user_limit'] = updates['user_limit']
                            
                            if is_ajax:
                                return jsonify({'success': True, 'message': 'Profile updated'})
                            return redirect(url_for('users.user_manager'))
                else:
                    error = "User not found."

            elif action == 'delete':
                tgt_email = request.form.get('email')
                target_user = next((u for u in users if u.get('email') == tgt_email), None)
                if target_user and (target_user in visible_users or tgt_email == current_email):
                    delete_user_db(tgt_email)
                    if is_ajax:
                        return jsonify({'success': True, 'message': 'User deleted'})
                    return redirect(url_for('users.user_manager'))

        admins = [{'name': session.get('user_name'), 'email': session.get('email')}]
        usage = get_usage_stats(current_email)
        return render_template('user_manager.html', users=visible_users, grouped_users=grouped_users, error=error, modules_config=modules_config, role=current_role, admins=admins, usage=usage)
    except Exception as e:
        current_app.logger.error(f"User Manager Error: {e}", exc_info=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 500
        return render_template('base.html', error=str(e))

@users_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    from models.database import get_user_by_email, update_user_db
    email = session.get('email')
    user_info = get_user_by_email(email)
    
    if not user_info:
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        # Extract inputs
        ins_days_str = request.form.getlist('insurance_days')
        reg_days_str = request.form.getlist('registration_days')
        maint_days_str = request.form.getlist('maintenance_days')
        
        # Convert to integers
        ins_days = [int(x) for x in ins_days_str if x.isdigit()]
        reg_days = [int(x) for x in reg_days_str if x.isdigit()]
        maint_days = [int(x) for x in maint_days_str if x.isdigit()]
        
        # Merge into reminder settings
        data = user_info.get('data') or {}
        if not isinstance(data, dict):
            data = {}
        
        data['reminder_settings'] = {
            'insurance_days': ins_days,
            'registration_days': reg_days,
            'maintenance_days': maint_days
        }
        
        update_user_db(email, {'data': data})
        return render_template('settings.html', success="Settings saved successfully.", reminder_settings=data['reminder_settings'])
        
    # GET: load reminder settings
    data = user_info.get('data') or {}
    reminder_settings = data.get('reminder_settings') or {
        'insurance_days': [30, 15, 7],
        'registration_days': [30, 15, 7],
        'maintenance_days': [30, 15, 7]
    }
    
    return render_template('settings.html', reminder_settings=reminder_settings)
