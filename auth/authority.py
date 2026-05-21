import os
import datetime
import json
import asyncpg
from typing import Optional, Dict
from auth.jwt_manager import auth_manager

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

class AuthAuthority:
    @staticmethod
    async def log_event(event_type: str, email: Optional[str], ip: Optional[str], user_agent: Optional[str], details: dict = {}):
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("""
                INSERT INTO security_audit (event_type, email, ip_address, user_agent, details)
                VALUES ($1, $2, $3, $4, $5)
            """, event_type, email, ip, user_agent, json.dumps(details))
        finally:
            await conn.close()

    @staticmethod
    async def check_brute_force(ip: str) -> bool:
        conn = await asyncpg.connect(DB_URL)
        try:
            row = await conn.fetchrow("SELECT * FROM login_attempts WHERE ip_address = $1", ip)
            if row:
                if row['is_blocked'] and row['blocked_until'] > datetime.datetime.now(datetime.timezone.utc):
                    return True # Blocked
                if row['attempts'] >= 5 and (datetime.datetime.now(datetime.timezone.utc) - row['last_attempt']).seconds < 600:
                    # Block for 15 mins after 5 failures
                    blocked_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
                    await conn.execute("UPDATE login_attempts SET is_blocked = TRUE, blocked_until = $2 WHERE ip_address = $1", ip, blocked_until)
                    return True
            return False
        finally:
            await conn.close()

    @staticmethod
    async def record_login_failure(ip: str):
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("""
                INSERT INTO login_attempts (ip_address, attempts, last_attempt)
                VALUES ($1, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (ip_address) DO UPDATE 
                SET attempts = login_attempts.attempts + 1, last_attempt = CURRENT_TIMESTAMP
            """, ip)
        finally:
            await conn.close()

    @staticmethod
    async def reset_login_attempts(ip: str):
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("DELETE FROM login_attempts WHERE ip_address = $1", ip)
        finally:
            await conn.close()

auth_authority = AuthAuthority()
