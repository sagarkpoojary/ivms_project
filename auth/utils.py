from functools import wraps
from flask import session, redirect, url_for, render_template
from extensions import cache
from models.database import get_user_by_email, load_users, load_vehicles

import time

def get_current_user_data():
    if not session.get('logged_in'):
        return None, {}
    
    email = session.get('email')
    
    # We no longer cache in the session. We rely on the global @cache.memoize(timeout=600)
    # on get_user_by_email in models/database.py, which we invalidate in update_user_db.
    user_info = get_user_by_email(email)
    
    current_data = {
        'role': session.get('role', 'user'),
        'vehicle_limit': session.get('vehicle_limit'),
        'user_limit': session.get('user_limit'),
        'enabled_modules': session.get('enabled_modules', []),
        'account_module': session.get('account_module', 'Normal'),
        'can_add_vehicle': session.get('can_add_vehicle', False),
        'company_name': user_info.get('company_name') if user_info else session.get('company_name')
    }
    return user_info, current_data

from auth.shared import resolve_filtered_vehicles, get_all_descendant_users_logic

def get_filtered_vehicles(include_all=False):
    """Flask-specific wrapper for filtered vehicles."""
    return resolve_filtered_vehicles(
        session.get('email'), 
        session.get('role'), 
        session.get('parent_email'), 
        include_all
    )

@cache.memoize(timeout=60)
def get_pending_drafts():
    return _get_pending_drafts_cached(session.get('email'), session.get('role'))

def _get_pending_drafts_cached(email, role):
    """Returns only vehicles with status 'draft' for Main Admin to review."""
    if not email: return []
    
    if role not in ['super_admin', 'main_admin']: return []
    
    all_vehicles = load_vehicles()
    drafts = [v for v in all_vehicles if v.get('status') == 'draft']
    
    if role == 'super_admin': return drafts
    
    # Main Admin sees drafts from their subtree
    users = load_users()
    my_subtree = set([email])
    parent_map = {u.get('parent_email'): [] for u in users if u.get('parent_email')}
    for u in users:
        p = u.get('parent_email')
        if p: parent_map[p].append(u.get('email'))
        
    stack = [email]
    while stack:
        cp = stack.pop()
        for child in parent_map.get(cp, []):
            if child not in my_subtree:
                my_subtree.add(child)
                stack.append(child)
                
    return [v for v in drafts if v.get('parent_email') in my_subtree]

def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('auth.login'))
            
            user_role = session.get('role', 'user')
            roles = ['user', 'admin', 'main_admin', 'super_admin']
            
            try:
                user_level = roles.index(user_role)
                req_level = roles.index(required_role)
            except ValueError:
                user_level = -1
                req_level = 100
                if required_role in roles:
                     req_level = roles.index(required_role)
            
            if user_role == 'super_admin':
                return f(*args, **kwargs)

            if user_level < req_level:
                    return render_template('login.html', error="Unauthorized access.")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@cache.memoize(timeout=300)
def get_all_descendant_users(email):
    return get_all_descendant_users_logic(email)
