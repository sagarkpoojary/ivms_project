import json
import os
from pathlib import Path

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_FILE = Path(os.path.join(APP_ROOT, "users.json"))

def migrate():
    if not USER_FILE.exists():
        print("users.json not found. Skipping migration.")
        return

    with open(USER_FILE, "r", encoding="utf-8") as fh:
        users = json.load(fh)

    updated = False
    for user in users:
        # Prompt 3: Existing Admin accounts should default to Normal unless updated manually.
        if user.get('role') in ['admin', 'main_admin']:
            if 'account_module' not in user:
                user['account_module'] = "Normal"
                updated = True
        
        # Ensure 'user_limit' and 'vehicle_limit' are present for admins if we want to enforce them
        # However, the requirement says "Default limits: Vehicles: 1, Users: 0" which are tied to the module.
        # So we just need the account_module to lookup the limits.

    if updated:
        with open(USER_FILE, "w", encoding="utf-8") as fh:
            json.dump(users, fh, indent=2, ensure_ascii=False)
        print("Sucessfully migrated users.json")
    else:
        print("No changes needed for users.json")

if __name__ == "__main__":
    migrate()
