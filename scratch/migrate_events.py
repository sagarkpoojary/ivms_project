import psycopg2
from config import Config

DB_CONFIG = {
    "dbname": Config.DB_NAME,
    "user": Config.DB_USER,
    "password": Config.DB_PASS,
    "host": "localhost",
    "port": Config.DB_PORT
}

def migrate():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        print("Creating system_events table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_events (
                id BIGSERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                vehicle_id VARCHAR(100),
                imei VARCHAR(15),
                driver_id INTEGER,
                severity VARCHAR(20) DEFAULT 'INFO',
                category VARCHAR(50),
                title VARCHAR(255),
                description TEXT,
                raw_payload JSONB,
                source VARCHAR(50) DEFAULT 'system',
                latitude DECIMAL(11, 8),
                longitude DECIMAL(11, 8),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                acknowledged BOOLEAN DEFAULT FALSE,
                acknowledged_by VARCHAR(255)
            );
            CREATE INDEX IF NOT EXISTS idx_system_events_imei ON system_events(imei);
            CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_system_events_tenant ON system_events(tenant_id);
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
