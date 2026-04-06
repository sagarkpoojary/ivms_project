from app import app
from services.traccar_service import try_traccar_get
import json

with app.app_context():
    print("Testing try_traccar_get('api/devices')...")
    try:
        r, host = try_traccar_get("api/devices", timeout=10)
        print(f"Status: {r.status_code}")
        print(f"Host: {host}")
    except Exception as e:
        print(f"Caught Exception: {e}")

