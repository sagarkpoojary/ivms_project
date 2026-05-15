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
        
        print("Updating/Creating RFID and Site Operations tables...")
        cur.execute("""
            -- Ensure drivers table has necessary columns for Enterprise
            -- Note: driver_id is VARCHAR(50) to match existing schema
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(255);
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS license_number VARCHAR(50);
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS photo_url TEXT;
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS department VARCHAR(100);
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS team VARCHAR(100);
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
            ALTER TABLE drivers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

            -- RFID Tags Registry
            CREATE TABLE IF NOT EXISTS rfid_tags (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                tag_id VARCHAR(50) UNIQUE NOT NULL,
                status VARCHAR(20) DEFAULT 'unassigned', -- unassigned, assigned, lost
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Driver Attendance (Daily Aggregates)
            CREATE TABLE IF NOT EXISTS driver_attendance (
                id BIGSERIAL PRIMARY KEY,
                driver_id VARCHAR(50) REFERENCES drivers(driver_id),
                tenant_id VARCHAR(255),
                date DATE,
                first_checkin TIMESTAMP WITH TIME ZONE,
                last_checkout TIMESTAMP WITH TIME ZONE,
                total_hours DECIMAL(5, 2),
                UNIQUE(driver_id, date)
            );

            -- PHASE 5: SITE OPERATIONS & ELV
            CREATE TABLE IF NOT EXISTS sites (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                name VARCHAR(255) NOT NULL,
                address TEXT,
                latitude DECIMAL(11, 8),
                longitude DECIMAL(11, 8),
                contact_person VARCHAR(255),
                contact_phone VARCHAR(20),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS site_visits (
                id BIGSERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                site_id INTEGER REFERENCES sites(id),
                technician_id VARCHAR(50) REFERENCES drivers(driver_id),
                vehicle_id VARCHAR(100),
                imei VARCHAR(15),
                scheduled_time TIMESTAMP WITH TIME ZONE,
                arrival_time TIMESTAMP WITH TIME ZONE,
                departure_time TIMESTAMP WITH TIME ZONE,
                status VARCHAR(20) DEFAULT 'pending', -- pending, in_progress, completed, cancelled
                work_report TEXT,
                photo_proof_url TEXT,
                signature_url TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS service_tickets (
                id BIGSERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                category VARCHAR(50), -- ELV, Customer Complaint, AMC
                title VARCHAR(255),
                description TEXT,
                priority VARCHAR(20) DEFAULT 'medium',
                status VARCHAR(20) DEFAULT 'open', -- open, assigned, in_progress, on_hold, completed, escalated
                customer_name VARCHAR(255),
                customer_phone VARCHAR(20),
                assigned_to VARCHAR(50) REFERENCES drivers(driver_id),
                related_site_id INTEGER REFERENCES sites(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_drivers_rfid ON drivers(rfid_tag);
            CREATE INDEX IF NOT EXISTS idx_site_visits_site ON site_visits(site_id);
            CREATE INDEX IF NOT EXISTS idx_service_tickets_status ON service_tickets(status);
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
