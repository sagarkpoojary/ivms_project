import jwt
import datetime
import os
import uuid
from typing import Optional, Dict
from auth.session_manager import session_manager
from passlib.context import CryptContext

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "ivms_enterprise_secret_2026_xyz")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours for enterprise stability
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
        to_encode = data.copy()
        jti = str(uuid.uuid4())
        to_encode.update({"type": "access", "jti": jti})
        if expires_delta:
            expire = datetime.datetime.utcnow() + expires_delta
        else:
            expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire, "iat": datetime.datetime.utcnow()})
        token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        # Track session for revocation
        session_manager.track_session(data.get("email"), jti, ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        return token

    @staticmethod
    def create_refresh_token(data: dict) -> str:
        to_encode = data.copy()
        jti = str(uuid.uuid4())
        to_encode.update({"type": "refresh", "jti": jti})
        expire = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "iat": datetime.datetime.utcnow()})
        token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        # Refresh tokens tracked longer
        session_manager.track_session(data.get("email"), jti, REFRESH_TOKEN_EXPIRE_DAYS * 86400)
        return token

    @staticmethod
    def decode_token(token: str, expected_type: str = "access") -> Optional[Dict]:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            if payload.get("type") != expected_type:
                return None
            
            # Check Blacklist
            if session_manager.is_blacklisted(payload.get("jti")):
                return None
                
            return payload
        except jwt.ExpiredSignatureError:
            return None # Expired
        except jwt.InvalidTokenError:
            return None # Invalid

auth_manager = AuthManager()
