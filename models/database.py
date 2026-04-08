import psycopg2
import psycopg2.extras
from services.time_service import get_oman_now
from config import Config

DB_CONFIG = {
    "dbname": Config.DB_NAME,
    "user": Config.DB_USER,
    "password": Config.DB_PASS,
    "host": Config.DB_HOST,
    "port": Config.DB_PORT
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def load_server_config():
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM system_config WHERE doc_id = %s", ("traccar_settings",))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row["data"]) if row else {}
    except: return {}

def save_server_config(data):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO system_config (doc_id, data) VALUES (%s, %s) ON CONFLICT (doc_id) DO UPDATE SET data = EXCLUDED.data",
            ("traccar_settings", psycopg2.extras.Json(data)))
        conn.commit(); cur.close(); conn.close()
    except: pass

def load_module_config():
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM system_config WHERE doc_id = %s", ("pricing_plans",))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row["data"]).get("plans", {}) if row else {}
    except: return {}

def save_module_config(data):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO system_config (doc_id, data) VALUES (%s, %s) ON CONFLICT (doc_id) DO UPDATE SET data = EXCLUDED.data",
            ("pricing_plans", psycopg2.extras.Json({"plans": data})))
        conn.commit(); cur.close(); conn.close()
    except: pass

def load_vehicles():
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM vehicles")
        rows = cur.fetchall(); cur.close(); conn.close()
        return [dict(r["data"]) for r in rows]
    except: return []

def get_vehicle_by_uid(unique_id):
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM vehicles WHERE unique_id = %s", (str(unique_id),))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row["data"]) if row else None
    except: return None

def add_vehicle_db(data):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""INSERT INTO vehicles (unique_id, parent_email, name, status, company_name, driver_name, device_model, created_at, approval_date, data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (unique_id) DO UPDATE SET
            parent_email=EXCLUDED.parent_email, name=EXCLUDED.name, status=EXCLUDED.status,
            company_name=EXCLUDED.company_name, driver_name=EXCLUDED.driver_name, data=EXCLUDED.data""",
            (str(data.get("unique_id")), data.get("parent_email"), data.get("name"), data.get("status"),
             data.get("company_name"), data.get("driver_name"), data.get("device_model"),
             str(data.get("created_at","")), str(data.get("approval_date","")), psycopg2.extras.Json(data)))
        conn.commit(); cur.close(); conn.close(); sync_stats()
    except Exception as e: print(f"add_vehicle_db error: {e}")

def delete_vehicle_db(unique_id):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM vehicles WHERE unique_id = %s", (str(unique_id),))
        conn.commit(); cur.close(); conn.close(); sync_stats()
    except: pass

def update_vehicle_db(unique_id, data):
    try:
        existing = get_vehicle_by_uid(unique_id) or {}
        existing.update(data)
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""UPDATE vehicles SET parent_email=%s, name=%s, status=%s, company_name=%s,
            driver_name=%s, device_model=%s, data=%s WHERE unique_id=%s""",
            (existing.get("parent_email"), existing.get("name"), existing.get("status"),
             existing.get("company_name"), existing.get("driver_name"), existing.get("device_model"),
             psycopg2.extras.Json(existing), str(unique_id)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"update_vehicle_db error: {e}")

def load_users():
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM users")
        rows = cur.fetchall(); cur.close(); conn.close()
        users = []
        for r in rows:
            u = dict(r["data"])
            if not u.get("name") or not str(u.get("name")).strip():
                u["name"] = u["email"].split("@")[0] if "@" in u.get("email","") else u.get("email","")
            users.append(u)
        return users
    except: return []

def get_user_by_email(email):
    if not email: return None
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM users WHERE email = %s", (email,))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row["data"]) if row else None
    except: return None

def add_user_db(data):
    if "created_at" not in data: data["created_at"] = str(get_oman_now())
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""INSERT INTO users (email, parent_email, name, role, password_hash, company_name, user_limit, vehicle_limit, account_module, data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO UPDATE SET
            parent_email=EXCLUDED.parent_email, name=EXCLUDED.name, role=EXCLUDED.role,
            password_hash=EXCLUDED.password_hash, company_name=EXCLUDED.company_name, data=EXCLUDED.data""",
            (data.get("email"), data.get("parent_email"), data.get("name"), data.get("role"),
             data.get("password_hash"), data.get("company_name"), data.get("user_limit", 0),
             data.get("vehicle_limit", 0), data.get("account_module"), psycopg2.extras.Json(data)))
        conn.commit(); cur.close(); conn.close(); sync_stats()
    except Exception as e: print(f"add_user_db error: {e}")

def delete_user_db(email):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit(); cur.close(); conn.close(); sync_stats()
    except: pass

def update_user_db(email, data):
    try:
        existing = get_user_by_email(email) or {}
        existing.update(data)
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""UPDATE users SET parent_email=%s, name=%s, role=%s, password_hash=%s,
            company_name=%s, user_limit=%s, vehicle_limit=%s, account_module=%s, data=%s WHERE email=%s""",
            (existing.get("parent_email"), existing.get("name"), existing.get("role"),
             existing.get("password_hash"), existing.get("company_name"),
             existing.get("user_limit", 0), existing.get("vehicle_limit", 0),
             existing.get("account_module"), psycopg2.extras.Json(existing), email))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"update_user_db error: {e}")

def get_system_stats():
    try:
        conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM system_config WHERE doc_id = %s", ("stats",))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row["data"]) if row else sync_stats()
    except: return {}

def sync_stats():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users"); uc = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM vehicles"); vc = cur.fetchone()[0]
        stats = {"total_users": uc, "total_vehicles": vc, "last_updated": str(get_oman_now())}
        cur.execute("INSERT INTO system_config (doc_id, data) VALUES (%s, %s) ON CONFLICT (doc_id) DO UPDATE SET data = EXCLUDED.data",
            ("stats", psycopg2.extras.Json(stats)))
        conn.commit(); cur.close(); conn.close()
        return stats
    except: return {}

def count_users_by_parent(parent_email):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE parent_email = %s", (parent_email,))
        count = cur.fetchone()[0]; cur.close(); conn.close(); return count
    except: return 0

def count_active_vehicles_by_parent(parent_email):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vehicles WHERE parent_email = %s AND status = %s", (parent_email, "active"))
        count = cur.fetchone()[0]; cur.close(); conn.close(); return count
    except: return 0
