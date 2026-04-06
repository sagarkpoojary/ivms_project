import requests
from app import app
from flask import session

# We need to simulate a request context or just call the service logic directly
# But the service logic relies on 'try_traccar_get' which uses requests.
# Let's just write a script that uses the existing 'services.traccar_service' to fetch raw data.

from services.traccar_service import try_traccar_get, get_admin_traccar_session, full_traccar_host

def debug_fetch():
    host = full_traccar_host()
    print(f"Target Host: {host}")
    
    s = get_admin_traccar_session()
    
    # Fetch devices first
    print("Fetching Devices...")
    r_dev = s.get(f"{host}/api/devices")
    if r_dev.status_code != 200:
        print(f"Error fetching devices: {r_dev.status_code} {r_dev.text}")
        return

    devices = r_dev.json()
    print(f"Found {len(devices)} devices.")
    
    # Fetch positions
    print("Fetching Positions...")
    # Get all device IDs
    dev_ids = [d['id'] for d in devices]
    
    # Fetch positions for these
    # Note: Traccar might need repeated params: ?deviceId=1&deviceId=2
    # requests handles list in params differently depending on version, let's construct explicit query if needed
    # but try_traccar_get usually handles it or we used standard requests.
    # checking recent usage: api.py uses params={"deviceId": device_ids}
    
    r_pos = s.get(f"{host}/api/positions", params=[('deviceId', i) for i in dev_ids])
    if r_pos.status_code != 200:
        print(f"Error fetching positions: {r_pos.status_code} {r_pos.text}")
        # Try fetching one by one if bulk fails just to be sure, or just dump what we have
    
    positions = {p['deviceId']: p for p in r_pos.json()} if r_pos.status_code == 200 else {}
    
    print("\n--- DEVICE DATA DUMP ---")
    for d in devices:
        d_id = d['id']
        name = d['name']
        uid = d['uniqueId']
        pos = positions.get(d_id, {})
        
        status = d.get('status')
        last_update = d.get('lastUpdate')
        
        # Attributes check
        p_attrs = pos.get('attributes', {})
        d_attrs = d.get('attributes', {})
        
        print(f"\nDevice: {name} (UID: {uid})")
        print(f"  - Status (Root): {status}")
        print(f"  - Last Update: {last_update}")
        print(f"  - Position Ignition: {pos.get('ignition')}")
        print(f"  - Position Attributes Ignition: {p_attrs.get('ignition')} / {p_attrs.get('Ignition')}")
        print(f"  - Device Attributes Ignition: {d_attrs.get('ignition')} / {d_attrs.get('Ignition')}")
        print(f"  - Speed: {pos.get('speed')}")
        print(f"  - Motion: {p_attrs.get('motion')}")
        
        # Simulating dashboard logic
        ign = p_attrs.get('ignition') if p_attrs.get('ignition') is not None else (
              p_attrs.get('Ignition') if p_attrs.get('Ignition') is not None else (
              pos.get('ignition') if pos.get('ignition') is not None else (
              d_attrs.get('ignition') if d_attrs.get('ignition') is not None else d_attrs.get('Ignition')
        )))
        
        print(f"  -> LOGIC RESULT: {ign}")

if __name__ == "__main__":
    debug_fetch()
