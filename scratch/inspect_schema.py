import psycopg2
from config import Config

DB_CONFIG = {
    "dbname": Config.DB_NAME,
    "user": Config.DB_USER,
    "password": Config.DB_PASS,
    "host": "localhost",
    "port": Config.DB_PORT
}

def inspect_schema():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        print("Inspecting drivers table schema...")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'drivers'
        """)
        columns = cur.fetchall()
        for col in columns:
            print(f"Column: {col[0]}, Type: {col[1]}")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_schema()
