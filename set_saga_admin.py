
import firebase_admin
from firebase_admin import credentials, firestore
import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
cred = credentials.Certificate(os.path.join(APP_ROOT, "serviceAccountKey.json"))
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()
email = "saga@gmail.com"

user_ref = db.collection('users').document(email)
user_doc = user_ref.get()

if user_doc.exists:
    user_ref.update({"role": "super_admin"})
    print(f"Updated existing user {email} to super_admin.")
else:
    user_ref.set({
        "email": email,
        "role": "super_admin",
        "name": "Saga Admin",
        "parent_email": None,
        "account_module": "Premium",
        "can_add_vehicle": True
    })
    print(f"Created new user {email} as super_admin.")
