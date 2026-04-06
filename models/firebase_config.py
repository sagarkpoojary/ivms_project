import os
import firebase_admin
from firebase_admin import credentials, firestore

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

db = None

def init_db():
    global db
    if not firebase_admin._apps:
        try:
            cred_path = os.path.join(APP_ROOT, "serviceAccountKey.json")
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Firebase Init Error: {e}")
    db = firestore.client()
    return db

def get_db():
    global db
    if db is None:
        return init_db()
    return db
