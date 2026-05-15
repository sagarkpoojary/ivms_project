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
        
        print("Creating notification tables...")
        cur.execute("""
            -- Notification Queue
            CREATE TABLE IF NOT EXISTS notification_queue (
                id BIGSERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                user_id INTEGER,
                event_id BIGINT REFERENCES system_events(id),
                severity VARCHAR(20),
                title VARCHAR(255),
                message TEXT,
                link VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                read BOOLEAN DEFAULT FALSE,
                archived BOOLEAN DEFAULT FALSE
            );

            -- Notification Delivery Logs
            CREATE TABLE IF NOT EXISTS notification_delivery (
                id BIGSERIAL PRIMARY KEY,
                notification_id BIGINT REFERENCES notification_queue(id),
                channel VARCHAR(20), -- in-app, email, whatsapp
                status VARCHAR(20), -- pending, sent, failed
                error_message TEXT,
                sent_at TIMESTAMP WITH TIME ZONE
            );

            -- User Notification Preferences
            CREATE TABLE IF NOT EXISTS notification_preferences (
                id SERIAL PRIMARY KEY,
                user_email VARCHAR(255),
                category VARCHAR(50),
                channel VARCHAR(20),
                enabled BOOLEAN DEFAULT TRUE,
                UNIQUE(user_email, category, channel)
            );

            CREATE INDEX IF NOT EXISTS idx_notifications_user ON notification_queue(user_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_tenant ON notification_queue(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_read ON notification_queue(read) WHERE read = FALSE;
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
