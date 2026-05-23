import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def query():
    load_dotenv()
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    print(f"Connecting to {db_url}...")
    conn = await asyncpg.connect(db_url)
    
    rows = await conn.fetch("SELECT imei, last_timestamp, updated_at, status, ignition, speed FROM live_vehicle_status")
    print(f"--- live_vehicle_status: ALL NON-OFFLINE VEHICLES ({len(rows)} total vehicles) ---")
    non_offline = []
    for r in rows:
        d = dict(r)
        if d['status'] != 'offline':
            non_offline.append(d)
            print(d)
            
    print("\n--- Recent Telemetry for non-offline devices ---")
    for r in non_offline:
        imei = r['imei']
        t_rows = await conn.fetch("SELECT id, timestamp, speed, io_elements FROM telemetry WHERE imei = $1 ORDER BY timestamp DESC LIMIT 2", imei)
        print(f"IMEI {imei} (Status: {r['status']}, Last TS: {r['last_timestamp']}, Updated At: {r['updated_at']}):")
        for tr in t_rows:
            io = tr['io_elements']
            import json
            io_dict = json.loads(io) if isinstance(io, str) else io
            ign = io_dict.get('239', io_dict.get('1', '0'))
            print(f"  Telemetry: id={tr['id']}, ts={tr['timestamp']}, speed={tr['speed']}, ignition={ign}")
            
    await conn.close()

if __name__ == '__main__':
    asyncio.run(query())
