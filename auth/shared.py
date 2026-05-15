from models.database import load_users, load_vehicles

def resolve_filtered_vehicles(email, role, parent_email, include_all=False):
    """Core logic to resolve allowed vehicles for any user, independent of session."""
    all_vehicles = load_vehicles()
    if not email: return []
    
    if role == 'super_admin':
        return all_vehicles
    
    # Filter by status if not including all
    if not include_all:
        target_list = [v for v in all_vehicles if v.get('status') == 'active']
    else:
        target_list = all_vehicles

    if role == 'main_admin':
        users = load_users()
        my_subtree = set([email])
        
        parent_map = {}
        for u in users:
            p = u.get('parent_email')
            if p:
                parent_map.setdefault(p, []).append(u.get('email'))
        
        stack = [email]
        while stack:
            current_parent = stack.pop()
            children = parent_map.get(current_parent, [])
            for child in children:
                if child not in my_subtree:
                    my_subtree.add(child)
                    stack.append(child)
                    
        return [v for v in target_list if v.get('parent_email') in my_subtree]
    elif role == 'admin':
        return [v for v in target_list if v.get('parent_email') == email]
    elif role == 'user':
        # Users only see active vehicles of their parent
        active_vehicles = [v for v in all_vehicles if v.get('status') == 'active']
        return [v for v in active_vehicles if v.get('parent_email') == parent_email]
    
    return []

def get_all_descendant_users_logic(email):
    """
    Returns a list of all users in the hierarchy under the given email.
    Uses a breadth-first search through the parent_email relationships.
    """
    users = load_users()
    all_descendants = []
    parent_map = {}
    for u in users:
        p = u.get('parent_email')
        if p:
            parent_map.setdefault(p, []).append(u)
    
    stack = [email]
    visited = set()
    while stack:
        current_parent_email = stack.pop()
        if current_parent_email in visited:
            continue
        visited.add(current_parent_email)
        
        children = parent_map.get(current_parent_email, [])
        for child in children:
            all_descendants.append(child)
            stack.append(child.get('email'))
            
    return all_descendants
