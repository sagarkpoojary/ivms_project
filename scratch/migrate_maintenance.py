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
        
        print("Creating maintenance system tables...")
        cur.execute("""
            -- Workshops
            CREATE TABLE IF NOT EXISTS maintenance_workshops (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                name VARCHAR(255),
                address TEXT,
                phone VARCHAR(50),
                email VARCHAR(255),
                specialty VARCHAR(100),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Maintenance Schedule (Recurring or One-time)
            CREATE TABLE IF NOT EXISTS maintenance_schedule (
                id BIGSERIAL PRIMARY KEY,
                tenant_id VARCHAR(255),
                vehicle_id VARCHAR(100),
                imei VARCHAR(15),
                service_type VARCHAR(100), -- Oil Change, Tire Rotation, Annual Inspection, etc.
                description TEXT,
                
                -- Triggers
                target_mileage INTEGER, -- KM
                target_engine_hours INTEGER, -- Hours
                target_date DATE,
                
                recurring BOOLEAN DEFAULT FALSE,
                mileage_interval INTEGER,
                time_interval_days INTEGER,
                
                status VARCHAR(20) DEFAULT 'planned', -- planned, due, overdue, completed, cancelled
                workshop_id INTEGER REFERENCES maintenance_workshops(id),
                technician_name VARCHAR(100),
                
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Maintenance History (Actual work done)
            CREATE TABLE IF NOT EXISTS maintenance_history (
                id BIGSERIAL PRIMARY KEY,
                schedule_id BIGINT REFERENCES maintenance_schedule(id),
                tenant_id VARCHAR(255),
                vehicle_id VARCHAR(100),
                imei VARCHAR(15),
                service_type VARCHAR(100),
                description TEXT,
                
                completion_date DATE,
                mileage_at_service INTEGER,
                engine_hours_at_service INTEGER,
                
                total_cost DECIMAL(12, 2),
                workshop_id INTEGER REFERENCES maintenance_workshops(id),
                technician_name VARCHAR(100),
                
                notes TEXT,
                status VARCHAR(20) DEFAULT 'completed',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Spare Parts Tracking
            CREATE TABLE IF NOT EXISTS maintenance_parts (
                id BIGSERIAL PRIMARY KEY,
                history_id BIGINT REFERENCES maintenance_history(id),
                part_name VARCHAR(255),
                part_number VARCHAR(100),
                quantity INTEGER,
                unit_cost DECIMAL(12, 2),
                total_cost DECIMAL(12, 2)
            );

            -- Maintenance Attachments (Invoices, Photos)
            CREATE TABLE IF NOT EXISTS maintenance_attachments (
                id BIGSERIAL PRIMARY KEY,
                history_id BIGINT REFERENCES maintenance_history(id),
                file_name VARCHAR(255),
                file_path TEXT,
                file_type VARCHAR(50),
                uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_maint_schedule_imei ON maintenance_schedule(imei);
            CREATE INDEX IF NOT EXISTS idx_maint_history_imei ON maintenance_history(imei);
            CREATE INDEX IF NOT EXISTS idx_maint_schedule_tenant ON maintenance_schedule(tenant_id);
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
