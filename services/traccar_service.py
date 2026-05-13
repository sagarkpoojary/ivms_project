# Deprecated: Traccar service is no longer used in the enterprise direct-telemetry architecture.
# This file is kept as a stub to prevent import errors during the transition phase.

def full_traccar_host(): return None
def get_traccar_session(use_session_cookies=False): return None
def ensure_admin_login(s): return False
def save_traccar_cookies(s, is_admin=True): pass
def try_traccar_get(endpoint, params=None, timeout=10, headers=None, _retry=True): 
    import requests
    r = requests.Response()
    r.status_code = 503
    return r, None
