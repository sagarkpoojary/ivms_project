import sys
sys.path.append("/root/ivms_project")

from app import app
from flask import session
from models.database import add_vehicle_db, delete_vehicle_db, get_conn
from routes.notifications import check_and_generate_reminders
from datetime import datetime, timedelta
from services.time_service import get_oman_now

def run_test():
    today = get_oman_now().date()
    
    # 1. Setup two test vehicles
    v1_uid = "TEST_INS_EXP_15"
    v2_uid = "TEST_REG_EXPIRED"
    
    # Clean up any previous test instances
    delete_vehicle_db(v1_uid)
    delete_vehicle_db(v2_uid)
    
    # Vehicle 1: Insurance expiring in exactly 15 days (Warning)
    v1_exp = (today + timedelta(days=15)).strftime("%Y-%m-%d")
    v1 = {
        "unique_id": v1_uid,
        "name": "Oman Delivery Truck 15",
        "brand": "Toyota",
        "model": "Hilux",
        "plate_number": "1515 AA",
        "insurance_company": "National Life & General",
        "insurance_policy_number": "POL-INS-15",
        "insurance_start_date": "2025-05-30",
        "insurance_expiry_date": v1_exp,
        "parent_email": "sagar@conceptgrps.com",
        "company_name": "System",
        "status": "active"
    }
    
    # Vehicle 2: Registration expired 5 days ago (Critical)
    v2_exp = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    v2 = {
        "unique_id": v2_uid,
        "name": "Oman Cargo Van Expired",
        "brand": "Mercedes",
        "model": "Sprinter",
        "plate_number": "5555 MM",
        "registration_start_date": "2025-05-30",
        "registration_expiry_date": v2_exp,
        "parent_email": "sagar@conceptgrps.com",
        "company_name": "System",
        "status": "active"
    }
    
    print("Inserting test vehicles with custom dates...")
    add_vehicle_db(v1)
    add_vehicle_db(v2)
    
    # 2. Run reminder calculations for the tenant
    print("Running dynamic check_and_generate_reminders under test_request_context...")
    with app.test_request_context():
        session['email'] = 'sagar@conceptgrps.com'
        session['role'] = 'super_admin'
        check_and_generate_reminders("sagar@conceptgrps.com", "sagar@conceptgrps.com")
    
    # 3. Query notification queue
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, severity, message, read 
        FROM notification_queue 
        WHERE tenant_id = 'sagar@conceptgrps.com' 
          AND (title LIKE '%TEST_INS_EXP_15%' OR title LIKE '%TEST_REG_EXPIRED%' 
               OR title LIKE '%Oman Delivery Truck 15%' OR title LIKE '%Oman Cargo Van Expired%')
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    
    print("\nQUERY RESULTS FROM notification_queue:")
    for r in rows:
        print(f"ID: {r[0]} | Title: {r[1]} | Severity: {r[2]} | Message: {r[3]} | Read: {r[4]}")
        
    # Clean up test database records
    delete_vehicle_db(v1_uid)
    delete_vehicle_db(v2_uid)
    cur.close(); conn.close()

if __name__ == "__main__":
    run_test()
