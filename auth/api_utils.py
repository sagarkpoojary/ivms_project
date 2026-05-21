import os
import json
from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature
import logging
import zlib
from starlette.requests import HTTPConnection
from auth.jwt_manager import auth_manager

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session"
SECRET_KEY = os.getenv("FLASK_SECRET", "ivms_secure_secret_2026")

def get_current_user(request: HTTPConnection):
    """
    Unified authentication: Checks for JWT Bearer token first, 
    then falls back to Flask session cookie.
    """
    # 1. Check for Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = auth_manager.decode_token(token, expected_type="access")
        if payload:
            return payload # Return JWT payload
        else:
            raise HTTPException(status_code=401, detail="Token expired or invalid")

    # 2. Fallback to Flask session cookie
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        # Check if it's a websocket and token is in query params
        if hasattr(request, 'query_params'):
            token = request.query_params.get("token")
            if token:
                payload = auth_manager.decode_token(token, expected_type="access")
                if payload:
                    return payload
        
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        import hashlib
        
        # Flask compressed sessions start with '.' - the payload inside is zlib-compressed
        # We need to handle this at the serializer level
        is_compressed = session_cookie.startswith('.')
        cookie_value = session_cookie[1:] if is_compressed else session_cookie
        
        data = None
        for digest in [hashlib.sha1, hashlib.sha256, hashlib.sha512]:
            try:
                serializer = URLSafeTimedSerializer(
                    SECRET_KEY, 
                    salt='cookie-session',
                    signer_kwargs={'key_derivation': 'hmac', 'digest_method': digest}
                )
                
                payload = serializer.loads(cookie_value)
                
                if isinstance(payload, dict):
                    data = payload
                elif isinstance(payload, bytes):
                    if is_compressed:
                        decompressed = zlib.decompress(payload)
                        data = json.loads(decompressed.decode('utf-8'))
                    else:
                        data = json.loads(payload.decode('utf-8'))
                else:
                    data = payload
                break  # Successfully decoded
            except BadSignature as e:
                logger.error(f"BadSignature with {digest().name}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error with {digest().name}: {e}")
                continue

        
        if not data:
            # Try one more approach: full cookie with dot (some itsdangerous versions)
            try:
                serializer = URLSafeTimedSerializer(
                    SECRET_KEY, 
                    salt='cookie-session',
                    signer_kwargs={'key_derivation': 'hmac', 'digest_method': hashlib.sha1}
                )
                payload = serializer.loads(session_cookie)
                data = payload if isinstance(payload, dict) else json.loads(payload)
                logger.info(f"Fallback decoded data: {data}")
            except Exception as e:
                logger.error(f"Fallback error: {e}")
                pass
        
        if data and data.get('logged_in'):
            return {
                "email": data.get("email"),
                "role": data.get("role"),
                "parent_email": data.get("parent_email"),
                "company_name": data.get("company_name"),
                "auth_source": "flask_session"
            }
        
        logger.warning(f"Session decode: data={data}")
        raise HTTPException(status_code=401, detail="Invalid session")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_allowed_imeis(user = Depends(get_current_user)):
    from auth.shared import resolve_filtered_vehicles
    vehicles = resolve_filtered_vehicles(
        user["email"], 
        user["role"], 
        user.get("parent_email")
    )
    return [str(v.get('unique_id')) for v in vehicles]

def role_required_api(required_role: str):
    def checker(user = Depends(get_current_user)):
        roles = ['user', 'admin', 'main_admin', 'super_admin']
        try:
            user_level = roles.index(user['role'])
            req_level = roles.index(required_role)
        except ValueError:
            user_level = -1
            req_level = 100
        
        if user['role'] == 'super_admin':
            return user
            
        if user_level < req_level:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker
