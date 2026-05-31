import sys
sys.path.append("/root/ivms_project")

import json
from models.database import get_conn

def check():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT doc_id, data FROM system_config WHERE doc_id = 'pricing_plans'")
        row = cur.fetchone()
        if row:
            print("PRICING PLANS IN DB:")
            print(json.dumps(row[1], indent=2))
        else:
            print("No pricing_plans row found!")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error checking DB: {e}")

if __name__ == "__main__":
    check()
