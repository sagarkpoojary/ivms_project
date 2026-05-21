import redis
import os
from datetime import datetime, timedelta

# Redis-backed Token Blacklist & Session Manager
# Used for instant session revocation and security enforcement.

class SessionManager:
    def __init__(self):
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=2 # Dedicated DB for sessions/blacklist
        )
        self.prefix = "ivms:blacklist:"

    def blacklist_token(self, jti: str, expires_in_seconds: int):
        """Adds a token's unique ID (jti) to the blacklist until it expires."""
        self.redis.setex(f"{self.prefix}{jti}", expires_in_seconds, "1")

    def is_blacklisted(self, jti: str) -> bool:
        """Checks if a token has been revoked."""
        return self.redis.exists(f"{f'{self.prefix}{jti}'}") == 1

    def revoke_user_sessions(self, email: str):
        """Force logout for all sessions of a specific user."""
        # This requires tracking active JTIs per user
        user_sessions_key = f"ivms:user_sessions:{email}"
        jtis = self.redis.smembers(user_sessions_key)
        for jti in jtis:
            self.blacklist_token(jti.decode(), 86400) # Max 24h
        self.redis.delete(user_sessions_key)

    def track_session(self, email: str, jti: str, expires_in_seconds: int):
        """Tracks active sessions for revocation capability."""
        user_sessions_key = f"ivms:user_sessions:{email}"
        self.redis.sadd(user_sessions_key, jti)
        self.redis.expire(user_sessions_key, expires_in_seconds)

session_manager = SessionManager()
