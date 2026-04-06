
import sys
import os
from datetime import datetime, timedelta

# Setup Flask context
from app import app
from services.traccar_service import try_traccar_get, full_traccar_host

def test_specific_route(uid):
    with app.app_context():
        print(f"Testing Route Fetch for UID: {uid}")
        host = full_traccar_host()
        
        # 1. Prepare params
        now = datetime.utcnow()
        start = now - timedelta(hours=24)
        traccar_from = start.strftime('%Y-%m-%dT%H:%M:%SZ')
        traccar_to = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # 2. Get Device Internal ID
        r_dev, _ = try_traccar_get("api/devices", params={"uniqueId": uid})
        if r_dev.status_code != 200 or not r_dev.json():
            print(f"Device not found or error: {r_dev.status_code}")
            return
        
        internal_id = r_dev.json()[0]['id']
        print(f"Internal ID: {internal_id}")

        # 3. Call Route API
        r, _ = try_traccar_get("api/reports/route", params={
            "deviceId": internal_id,
            "from": traccar_from,
            "to": traccar_to
        }, headers={'Accept': 'application/json'})
        
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('Content-Type')}")
        print(f"Body starts with: {r.text[:200]}")
        
        try:
            data = r.json()
            print(f"JSON parsed successfully. Count: {len(data)}")
        except Exception as e:
            print(f"JSON Parse Failed: {e}")

if __name__ == "__main__":
    test_specific_route("864275071210218")
