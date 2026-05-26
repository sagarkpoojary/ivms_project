import psycopg2
from models.database import get_conn
from services.time_service import get_oman_now

def log_api_access(ip_address, endpoint, method, status_code, duration_ms, response_size, error_message=None, token_used=None):
    """
    Persistently log an API request to the PostgreSQL database table.
    Ensures table exists on first insert and handles errors gracefully without dropping connection.
    """
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Ensure schema table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_access_logs (
                id SERIAL PRIMARY KEY,
                ip_address VARCHAR(45) NOT NULL,
                endpoint VARCHAR(255) NOT NULL,
                method VARCHAR(10) NOT NULL,
                status_code INTEGER NOT NULL,
                request_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                response_time TIMESTAMP WITH TIME ZONE NOT NULL,
                duration_ms DOUBLE PRECISION NOT NULL,
                response_size INTEGER NOT NULL,
                error_message TEXT,
                token_used VARCHAR(255)
            );
        """)
        conn.commit()
        
        now = get_oman_now()
        cur.execute("""
            INSERT INTO api_access_logs 
            (ip_address, endpoint, method, status_code, response_time, duration_ms, response_size, error_message, token_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (ip_address, endpoint, method, status_code, now, duration_ms, response_size, error_message, token_used))
        conn.commit()
        
    except Exception as e:
        # Fail close/gracefully log error to stdout/stderr inside docker context
        print(f"Failed to log API access to DB: {e}")
    finally:
        if cur:
            try: cur.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass
