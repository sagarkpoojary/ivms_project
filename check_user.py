import requests, json, os
from models.firebase_config import get_db

db = get_db()
cfg = db.collection('system_config').document('traccar_settings').get().to_dict()
active = cfg.get('active_ip')
host = 'http://' + active if not active.startswith('http') else active
host = host.rstrip('/')

s = requests.Session()
if os.path.exists('cookies.txt'):
    with open('cookies.txt', 'r') as f:
        cookies = json.load(f)
        requests.utils.add_dict_to_cookiejar(s.cookies, cookies)

r = s.get(f"{host}/api/users")
print(f"Fetch users status: {r.status_code}")
if r.status_code == 200:
    users = r.json()
    match = [u for u in users if u.get('email') == 'TESTUSER1']
    print(f"Found TESTUSER1: {match}")
else:
    print(f"Error: {r.text}")
