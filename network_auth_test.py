import requests
import time

host = "http://172.16.1.26:8082"
email = "alireza@conceptgrps.com"
pwd = "test_password_placeholder"

print(f"Testing connectivity to {host}...")
try:
    start = time.time()
    r = requests.get(f"{host}/api/server", timeout=5)
    print(f"GET /api/server: {r.status_code} ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"GET /api/server failed: {e}")

print("\nTesting POST /api/session (JSON)...")
try:
    start = time.time()
    r = requests.post(f"{host}/api/session", json={'email': email, 'password': pwd}, timeout=5)
    print(f"POST JSON: {r.status_code} - Body: {r.text[:200]} ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"POST JSON failed: {e}")

print("\nTesting POST /api/session (Form)...")
try:
    start = time.time()
    r = requests.post(f"{host}/api/session", data={'email': email, 'password': pwd}, timeout=5)
    print(f"POST Form: {r.status_code} - Body: {r.text[:200]} ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"POST Form failed: {e}")
