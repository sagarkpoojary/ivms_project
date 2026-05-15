import os
import json
from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature
import logging

logger = logging.getLogger(__name__)

# Flask's default session cookie name
SESSION_COOKIE_NAME = "session"
# Flask's secret key from .env
SECRET_KEY = os.getenv("FLASK_SECRET", "ivms_secure_secret_2026")

from itsdangerous import URLSafeTimedSerializer, BadSignature
import zlib
import base64

from starlette.requests import HTTPConnection

def get_current_user(request: HTTPConnection):
    """
    Decrypts the Flask session cookie to get the logged-in user data in FastAPI.
    Handles Flask 2.2+ TimedSerializer format and optional zlib compression.
    """
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Flask 3.x in this environment is using sha1 (confirmed via inspection)
        # We'll try sha1 first, then sha256 as fallback
        for digest in ['sha1', 'sha256']:
            try:
                serializer = URLSafeTimedSerializer(
                    SECRET_KEY, 
                    salt='cookie-session',
                    signer_kwargs={'key_derivation': 'hmac', 'digest_method': digest}
                )
                
                is_compressed = False
                if session_cookie.startswith('.'):
                    is_compressed = True
                
                # itsdangerous.loads() handles the splitting. 
                # If it starts with '.', it might fail if it's not a valid base64.
                # However, Flask's itsdangerous version might be patched or used differently.
                
                # Let's try to load it normally first
                try:
                    payload = serializer.loads(session_cookie)
                except BadSignature:
                    if is_compressed:
                        # Try without the leading dot
                        payload = serializer.loads(session_cookie[1:])
                    else:
                        raise
                
                if is_compressed and isinstance(payload, bytes):
                    try:
                        payload = zlib.decompress(payload)
                    except Exception as decompress_err:
                        logger.error(f"Decompression failed: {decompress_err}")
                
                # Payload is now bytes (JSON)
                if isinstance(payload, bytes):
                    data = json.loads(payload.decode('utf-8'))
                else:
                    data = payload
                
                if data.get('logged_in'):
                    return {
                        "email": data.get("email"),
                        "role": data.get("role"),
                        "parent_email": data.get("parent_email"),
                        "company_name": data.get("company_name")
                    }
            except BadSignature:
                continue
            except Exception as e:
                logger.debug(f"Trial with digest {digest} failed: {e}")
                continue
        
        raise HTTPException(status_code=401, detail="invalid session")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session decryption error: {e}")
        raise HTTPException(status_code=401, detail="Authentication error")

async def get_allowed_imeis(user = Depends(get_current_user)):
    """
    Returns the list of IMEIs the current user is allowed to see.
    """
    from auth.shared import resolve_filtered_vehicles
    vehicles = resolve_filtered_vehicles(
        user["email"], 
        user["role"], 
        user.get("parent_email")
    )
    return [str(v.get('unique_id')) for v in vehicles]
