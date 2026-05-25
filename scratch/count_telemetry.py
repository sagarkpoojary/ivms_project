import asyncio, os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["FLASK_SECRET"] = "dummy"
os.environ["IVMS_API_URL"] = "http://localhost:8000"
os.environ["ODOO_REPORT_TOKEN"] = "dummy"
os.environ["SMTP_USER"] = "dummy"
os.environ["SMTP_PASS"] = "dummy"

import asyncpg
from services.time_service import get_period_dates

async def main():
    DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    db = await asyncpg.connect(DB_URL)
    
    start_dt, end_dt = get_period_dates('Today')
    print(f"Query window (Oman local): {start_dt} to {end_dt}")
    
    rows = await db.fetch("""
        SELECT imei, COUNT(*) as cnt, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
        FROM telemetry
        WHERE timestamp BETWEEN $1 AND $2
        GROUP BY imei
    """, start_dt, end_dt)
    
    print("\nTelemetry counts for Today:")
    for r in rows:
        print(dict(r))
        
    print("\nCompleted trips for Today:")
    trip_rows = await db.fetch("""
        SELECT imei, COUNT(*) as cnt, SUM(distance_km) as total_dist
        FROM trip_summary
        WHERE start_time BETWEEN $1 AND $2
        GROUP BY imei
    """, start_dt, end_dt)
    for r in trip_rows:
        print(dict(r))
        
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
