import os
import requests
import json
from models.firebase_config import init_db, get_db

init_db()
db = get_db()
doc = db.collection('system_config').document('traccar_settings').get()
cfg = doc.to_dict() if doc.exists else {}

email = cfg.get('admin_email')
pwd = cfg.get('admin_pass')
host = cfg.get('active_ip')
if not host.startswith(('http://', 'https://')):
    host = 'http://' + host

print(f"Testing Login for: {email} at {host}")

s = requests.Session()
# Test JSON login
print("Attempting JSON login...")
try:
    r = s.post(f"{host}/api/session", json={'email': email, 'password': pwd}, timeout=10)
    print(f"JSON Login Status: {r.status_code}")
    print(f"JSON Login Body: {r.text[:500]}")
except Exception as e:
    print(f"JSON Login Error: {e}")

# Test FORM login
print("\nAttempting FORM login...")
try:
    r = s.post(f"{host}/api/session", data={'email': email, 'password': pwd}, timeout=10)
    print(f"FORM Login Status: {r.status_code}")
    print(f"FORM Login Body: {r.text[:500]}")
except Exception as e:
    print(f"FORM Login Error: {e}")
