from services.traccar_service import get_traccar_session, ensure_admin_login, full_traccar_host

print(f"Traccar Host: {full_traccar_host()}")
s = get_traccar_session()
print("Session created. Testing validity...")
if ensure_admin_login(s):
    print("SUCCESS: Admin login confirmed.")
else:
    print("FAILURE: Admin login failed. Check Traccar admin credentials in Firestore (system_config -> traccar_settings: admin_email/admin_pass) or set TRACCAR_ADMIN_EMAIL/TRACCAR_ADMIN_PASS env vars")
