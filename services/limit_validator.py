"""
Centralized service for enforcing system limits on user and vehicle creation.

This module provides strict validation to ensure no admin can exceed their
assigned user or vehicle limits. All validation happens at the backend level
to prevent any UI or API bypasses.
"""

from models.database import load_users, load_vehicles, get_user_by_email
from typing import Tuple, Dict, Optional


def count_users_by_parent(parent_email: str) -> int:
    """
    Count the number of users created by a specific admin.
    
    Args:
        parent_email: Email of the admin whose created users to count
        
    Returns:
        Count of users where parent_email matches the given email
    """
    users = load_users()
    return len([u for u in users if u.get('parent_email') == parent_email])


def count_active_vehicles_by_parent(parent_email: str) -> int:
    """
    Count the number of active vehicles owned by a specific admin.
    
    Args:
        parent_email: Email of the admin whose vehicles to count
        
    Returns:
        Count of active vehicles where parent_email matches the given email
    """
    vehicles = load_vehicles()
    return len([v for v in vehicles if v.get('parent_email') == parent_email and v.get('status') == 'active'])


def validate_user_creation_limit(admin_email: str, admin_role: str, admin_user_limit: Optional[int]) -> Tuple[bool, int, str]:
    """
    Validate if an admin can create a new user based on their assigned limit.
    
    Args:
        admin_email: Email of the admin attempting to create a user
        admin_role: Role of the admin (super_admin, main_admin, admin)
        admin_user_limit: Maximum number of users the admin can create (None = unlimited)
        
    Returns:
        Tuple of (can_create, current_count, error_message)
        - can_create: True if user creation is allowed, False otherwise
        - current_count: Current number of users created by this admin
        - error_message: Empty string if allowed, error message if blocked
    """
    # Super admins have no limits
    if admin_role == 'super_admin':
        return (True, 0, "")
    
    # If no limit is set, block creation (limits must be explicitly configured)
    if admin_user_limit is None:
        return (False, 0, "No user limit configured for your account. Please contact your administrator.")
    
    # Count current users created by this admin
    current_count = count_users_by_parent(admin_email)
    
    # Check if limit is reached
    if current_count >= admin_user_limit:
        error_msg = f"User limit reached ({current_count}/{admin_user_limit}). Cannot create more users. Please contact your administrator to increase your limit."
        return (False, current_count, error_msg)
    
    # Creation allowed
    return (True, current_count, "")


def validate_vehicle_registration_limit(admin_email: str, admin_role: str, admin_vehicle_limit: Optional[int]) -> Tuple[bool, int, str]:
    """
    Validate if an admin can register a new vehicle based on their assigned limit.
    
    Args:
        admin_email: Email of the admin attempting to register a vehicle
        admin_role: Role of the admin (super_admin, main_admin, admin)
        admin_vehicle_limit: Maximum number of vehicles the admin can register (None = unlimited)
        
    Returns:
        Tuple of (can_register, current_count, error_message)
        - can_register: True if vehicle registration is allowed, False otherwise
        - current_count: Current number of active vehicles owned by this admin
        - error_message: Empty string if allowed, error message if blocked
    """
    # Super admins have no limits
    if admin_role == 'super_admin':
        return (True, 0, "")
    
    # If no limit is set, block registration (limits must be explicitly configured)
    if admin_vehicle_limit is None:
        return (False, 0, "No vehicle limit configured for your account. Please contact your administrator.")
    
    # Count current active vehicles owned by this admin
    current_count = count_active_vehicles_by_parent(admin_email)
    
    # Check if limit is reached
    if current_count >= admin_vehicle_limit:
        error_msg = f"Vehicle limit reached ({current_count}/{admin_vehicle_limit}). Cannot register more vehicles. Please contact your administrator to increase your limit."
        return (False, current_count, error_msg)
    
    # Registration allowed
    return (True, current_count, "")


def get_usage_stats(admin_email: str) -> Dict[str, int]:
    """
    Get current usage statistics for an admin.
    
    Args:
        admin_email: Email of the admin
        
    Returns:
        Dictionary with keys: users_created, vehicles_registered, user_limit, vehicle_limit
    """
    user_info = get_user_by_email(admin_email)
    
    users_created = count_users_by_parent(admin_email)
    vehicles_registered = count_active_vehicles_by_parent(admin_email)
    
    user_limit = user_info.get('user_limit') if user_info else None
    vehicle_limit = user_info.get('vehicle_limit') if user_info else None
    
    return {
        'users_created': users_created,
        'vehicles_registered': vehicles_registered,
        'user_limit': user_limit if user_limit is not None else 0,
        'vehicle_limit': vehicle_limit if vehicle_limit is not None else 0
    }


def validate_draft_approval_limit(draft_parent_email: str) -> Tuple[bool, str]:
    """
    Validate if a draft vehicle can be approved based on the creator's vehicle limit.
    
    This is used when a Main Admin approves a draft created by a Company Admin.
    The limit check is against the Company Admin's (draft creator's) limits.
    
    Args:
        draft_parent_email: Email of the Company Admin who created the draft
        
    Returns:
        Tuple of (can_approve, error_message)
        - can_approve: True if approval is allowed, False otherwise
        - error_message: Empty string if allowed, error message if blocked
    """
    creator_info = get_user_by_email(draft_parent_email)
    
    if not creator_info:
        return (False, "Draft creator not found in system.")
    
    creator_role = creator_info.get('role', 'user')
    creator_vehicle_limit = creator_info.get('vehicle_limit')
    
    # Validate against the creator's limits
    can_register, current_count, error_msg = validate_vehicle_registration_limit(
        draft_parent_email, 
        creator_role, 
        creator_vehicle_limit
    )
    
    if not can_register:
        # Customize error message for draft approval context
        error_msg = f"Cannot approve: Draft creator has reached their vehicle limit ({current_count}/{creator_vehicle_limit}). The Company Admin must delete existing vehicles or request a limit increase."
        return (False, error_msg)
    
    return (True, "")
