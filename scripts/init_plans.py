import psycopg2
import json
import os
from config import Config

DB_CONFIG = {
    "dbname": Config.DB_NAME,
    "user": Config.DB_USER,
    "password": Config.DB_PASS,
    "host": Config.DB_HOST,
    "port": Config.DB_PORT
}

PLANS = {
    "Normal": {
        "vehicle_limit": 5,
        "user_limit": 2,
        "enabled_modules": ["dashboard", "reports", "pre_reg_report"]
    },
    "Silver": {
        "vehicle_limit": 20,
        "user_limit": 5,
        "enabled_modules": ["dashboard", "reports", "pre_reg_report", "vehicle_add", "notifications"]
    },
    "Gold": {
        "vehicle_limit": 50,
        "user_limit": 15,
        "enabled_modules": ["dashboard", "reports", "pre_reg_report", "vehicle_add", "user_manager", "notifications", "reports_trips", "reports_stops"]
    },
    "Premium": {
        "vehicle_limit": 500,
        "user_limit": 100,
        "enabled_modules": [
            "dashboard", "reports", "pre_reg_report", "vehicle_add", "user_manager", "notifications", "servers",
            "dashboard_stats", "dashboard_charts", "dashboard_map", "dashboard_big_chart", "dashboard_alerts",
            "reports_trips", "reports_stops", "reports_combined", "pricing"
        ]
    }
}

def init_plans():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("INSERT INTO system_config (doc_id, data) VALUES (%s, %s) ON CONFLICT (doc_id) DO UPDATE SET data = EXCLUDED.data",
                    ("pricing_plans", json.dumps({"plans": PLANS})))
        conn.commit()
        cur.close()
        conn.close()
        print("Pricing plans initialized successfully.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    init_plans()
