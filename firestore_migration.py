import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
import os

# 1. Setup Firebase
# Ensure you have your 'serviceAccountKey.json' in this directory
# Download it from Firebase Console -> Project Settings -> Service accounts
cred_path = "serviceAccountKey.json"

if not os.path.exists(cred_path):
    print(f"Error: {cred_path} not found. Please place your Firebase service account JSON file here.")
    exit(1)

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)

db = firestore.client()

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return None

def migrate_users():
    users = load_json('users.json')
    if not users:
        print("No users.json found.")
        return

    batch = db.batch()
    count = 0
    
    print(f"Migrating {len(users)} users...")
    
    for user in users:
        # distinct document ID based on email
        doc_id = user.get('email')
        if not doc_id:
            continue
            
        doc_ref = db.collection('users').document(doc_id)
        batch.set(doc_ref, user)
        count += 1
        
        # Firestore batch limit is 500
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
            print(f"Committed {count} users...")

    batch.commit()
    print("Users migration complete.")

def migrate_vehicles():
    vehicles = load_json('vehicles.json')
    if not vehicles:
        print("No vehicles.json found.")
        return

    batch = db.batch()
    count = 0
    
    print(f"Migrating {len(vehicles)} vehicles...")
    
    for v in vehicles:
        # distinct document ID based on unique_id
        doc_id = str(v.get('unique_id'))
        if not doc_id:
            continue
            
        doc_ref = db.collection('vehicles').document(doc_id)
        batch.set(doc_ref, v)
        count += 1
        
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    batch.commit()
    print("Vehicles migration complete.")

def migrate_config():
    # 1. Server Config
    server_conf = load_json('server_config.json')
    if server_conf:
        db.collection('system_config').document('traccar_settings').set(server_conf)
        print("Migrated server_config.json -> system_config/traccar_settings")

    # 2. Modules Config
    modules_conf = load_json('modules_config.json')
    if modules_conf:
        # modules_config.json structure is usually a map of Plan Names.
        # We can store the whole map in one doc 'pricing_plans'
        # or split them. Let's store as one doc for simpler retrieval.
        db.collection('system_config').document('pricing_plans').set({
            'plans': modules_conf
        })
        print("Migrated modules_config.json -> system_config/pricing_plans")

if __name__ == "__main__":
    print("Starting Firestore Migration...")
    migrate_users()
    migrate_vehicles()
    migrate_config()
    print("All Done! Remember to delete local JSON files once verified.")
