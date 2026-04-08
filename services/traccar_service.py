import os
import json
import requests
from flask import session, has_request_context
from models.database import load_server_config
from config import Config, BASE_DIR

def get_master_credentials():
    """Load master Traccar admin credentials from system config or environment vars.
    Returns (email, password) or (None, None) if not configured.
    """
    cfg = load_server_config()
    email = cfg.get('admin_email') or Config.TRACCAR_ADMIN_EMAIL
    pwd = cfg.get('admin_pass') or Config.TRACCAR_ADMIN_PASS
    
    # DEBUG: Masked credentials check
    try:
        masked_email = f"{email[:3]}...{email[-3:]}" if email and len(email) > 6 else str(email)
        masked_pwd = "***" if pwd else "None"
        with open("api_errors.log", "a") as f:
             import time
             f.write(f"[{time.ctime()}] DEBUG: Creds retrieved: Email={masked_email}, Pass={masked_pwd}, Host={load_server_config().get('active_ip')}\n")
    except: pass
    
    return email, pwd


def full_traccar_host():
    cfg = load_server_config()
    active = cfg.get("active_ip")
    if not active: return None
    if not (active.startswith("http://") or active.startswith("https://")):
            return "http://" + active
    return active.rstrip('/')


def get_traccar_session(use_session_cookies=False): # Returns a requests.Session preloaded with any known cookies
    """
    Returns a session which may contain saved master cookies (file or flask session).
    """
    s = requests.Session()
    host = full_traccar_host()
    if not host: return s

    # 1. Try to load existing master cookies from file
    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, 'r') as f:
                cookies = json.load(f)
                requests.utils.add_dict_to_cookiejar(s.cookies, cookies)
        except Exception:
            # If reading fails, continue without cookies
            pass

    # 2. Try to load cookies from Flask session (if present)
    try:
        if has_request_context() and 'traccar_cookies' in session:
            requests.utils.add_dict_to_cookiejar(s.cookies, session['traccar_cookies'])
    except Exception:
        pass

    return s


def ensure_admin_login(s):
    """Refreshes the session if needed. Returns True on valid session/login, False otherwise."""
    host = full_traccar_host()
    if not host: return False

    # Quick check: is the session valid?
    try:
        r = s.get(f"{host}/api/session", timeout=5)
        if r.status_code == 200:
            return True
    except Exception:
        # Could not reach session endpoint; continue to try login (may produce clearer errors)
        pass

    email, pwd = get_master_credentials()
    if not email or not pwd:
        # No credentials configured to attempt a login
        return False

    try:
        from flask import current_app
        current_app.logger.info("Proxy: Relogging in as Master Admin...")
    except Exception:
        current_app = None

    try:
        # Use JSON payload for compatibility with modern Traccar versions
        r_login = s.post(f"{host}/api/session", data={'email': email, 'password': pwd}, timeout=10)
        # Try both data and json if one fails, some Traccar versions are picky
        if r_login.status_code != 200:
             r_login = s.post(f"{host}/api/session", json={'email': email, 'password': pwd}, timeout=10)

        if r_login.status_code == 200:
            save_traccar_cookies(s, is_admin=True)
            # Also store into Flask session if request context exists
            try:
                if has_request_context():
                    session['traccar_cookies'] = requests.utils.dict_from_cookiejar(s.cookies)
            except Exception:
                pass
            return True
        else:
            try:
                log_path = os.path.join(BASE_DIR, "api_errors.log")
                with open(log_path, "a") as f:
                    f.write(f"Login failed: Status {r_login.status_code}, Body: {r_login.text}\n")
            except: 
                pass
            if current_app:
                current_app.logger.warning(f"Proxy login failed (status={r_login.status_code}): {r_login.text}")
    except Exception as e:
        if current_app:
            current_app.logger.exception("Failed to login to Traccar: %s", e)
    return False


def get_admin_traccar_session():
    return get_traccar_session()


def save_traccar_cookies(s, is_admin=True):
    cookies = requests.utils.dict_from_cookiejar(s.cookies)
    if is_admin:
        cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
        try:
            with open(cookie_path, 'w') as f:
                json.dump(cookies, f)
        except Exception:
            pass

    # Also save to Flask session if request context exists to speed up subsequent requests
    try:
        if has_request_context():
            session['traccar_cookies'] = cookies
    except Exception:
        pass

def try_traccar_get(endpoint, params=None, timeout=10, headers=None, _retry=True):
    host = full_traccar_host()
    if not host: raise Exception("No Traccar Host")

    s = get_traccar_session()
    try:
        r = s.get(f"{host}/{endpoint}", params=params, timeout=timeout, headers=headers)
    except (requests.exceptions.RequestException, ConnectionResetError) as e:
        # Connection reset — clear cookies and retry once with fresh login
        if _retry:
            import os
            cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
            try: os.remove(cookie_path)
            except: pass
            s2 = requests.Session()
            if ensure_admin_login(s2):
                return try_traccar_get(endpoint, params=params, timeout=timeout, headers=headers, _retry=False)
        raise Exception(f"Traccar unreachable: {e}")

    if r.status_code == 401:
        # Session expired — re-login and retry once
        if _retry and ensure_admin_login(s):
            return try_traccar_get(endpoint, params=params, timeout=timeout, headers=headers, _retry=False)
        raise Exception("Traccar authentication failed: invalid or missing master credentials")

    return r, host

def check_device_exists(unique_id):
    """Verifies if a device with unique_id exists in Traccar."""
    try:
        r, _ = try_traccar_get("api/devices", params={"uniqueId": unique_id})
        if r.status_code == 200:
            devices = r.json()
            for d in devices:
                if str(d.get('uniqueId')) == str(unique_id):
                    return d
        return None
    except Exception:
        return None
