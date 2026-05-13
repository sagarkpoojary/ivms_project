import psycopg2
from werkzeug.security import generate_password_hash
import json
import os

DB_CONFIG = {
    "dbname": "ivmsdb",
    "user": "ivmsuser",
    "password": "ivms_secure_2026",
    "host": "db",
    "port": "5432"
}

def init_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # 1. Create system_config table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                doc_id VARCHAR(100) PRIMARY KEY,
                data JSONB NOT NULL
            );
        """)
        
        # 2. Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email VARCHAR(255) PRIMARY KEY,
                parent_email VARCHAR(255),
                name VARCHAR(255),
                role VARCHAR(50),
                password_hash TEXT,
                company_name VARCHAR(255),
                user_limit INTEGER DEFAULT 0,
                vehicle_limit INTEGER DEFAULT 0,
                account_module VARCHAR(50) DEFAULT 'Normal',
                data JSONB DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 3. Create vehicles table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                unique_id VARCHAR(100) PRIMARY KEY,
                parent_email VARCHAR(255),
                name VARCHAR(255),
                status VARCHAR(50) DEFAULT 'active',
                company_name VARCHAR(255),
                driver_name VARCHAR(255),
                device_model VARCHAR(100),
                created_at TEXT,
                approval_date TEXT,
                data JSONB DEFAULT '{}'
            );
        """)

        # 4. Create password_reset_tokens table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255),
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                used BOOLEAN DEFAULT FALSE
            );
        """)
        
        # 5. Insert default super_admin
        admin_email = "saga@gmail.com"
        admin_pass = "admin123"
        hashed_pass = generate_password_hash(admin_pass)
        
        user_data = {
            "email": admin_email,
            "name": "Super Admin",
            "role": "super_admin",
            "password_hash": hashed_pass,
            "account_module": "Premium",
            "company_name": "System",
            "can_add_vehicle": True
        }
        
        cur.execute("""
            INSERT INTO users (email, name, role, password_hash, account_module, company_name, data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            data = EXCLUDED.data;
        """, (admin_email, user_data["name"], user_data["role"], hashed_pass, 
              user_data["account_module"], user_data["company_name"], json.dumps(user_data)))
        
        # 6. Insert default system config
        default_traccar = {
            "active_ip": "72.61.254.210:8082",
            "admin_email": "admin@conceptgrps.com",
            "admin_pass": "admin",
            "stop_threshold": 5,
            "servers": ["72.61.254.210:8082"]
        }
        cur.execute("""
            INSERT INTO system_config (doc_id, data)
            VALUES (%s, %s)
            ON CONFLICT (doc_id) DO NOTHING;
        """, ("traccar_settings", json.dumps(default_traccar)))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Database initialized. Admin user: {admin_email} / {admin_pass}")
        
    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_db()
