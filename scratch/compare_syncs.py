import asyncio, os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["FLASK_SECRET"] = "dummy"
os.environ["IVMS_API_URL"] = "http://localhost:8000"
os.environ["ODOO_REPORT_TOKEN"] = "dummy"
os.environ["SMTP_USER"] = "dummy"
os.environ["SMTP_PASS"] = "dummy"

import datetime
from services.time_service import get_period_dates
from services.native_report_service import native_report_service
from models.database import load_vehicles

def main():
    print("=== Comparing get_fleet_summary outputs ===")
    
    start_dt, end_dt = get_period_dates('Today')
    print(f"Oman Today: {start_dt} to {end_dt}")
    
    vehicles = load_vehicles()
    print(f"Total vehicles loaded from load_vehicles(): {len(vehicles)}")
    
    summaries = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)
    
    print("\nCalculated summaries via native_report_service:")
    for s in summaries:
        print(f"  - Device {s['unique_id']} ({s['name']}): dist={s['total_distance']} km, engineHours={s['engine_hours']} h, fuel={s['fuel_liters']} L")

if __name__ == "__main__":
    main()
