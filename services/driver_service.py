"""
IVMS Driver Service
===================
Provides business logic and PostgreSQL persistence for the RFID & Drivers module:
- Driver registry CRUD (Name, License, RFID tag, Phone, Department, Team)
- RFID Tag management
- Driver attendance logs with shift duration calculations (Checkin/Checkout)
- Live driver sessions tracking
- CSV report exporting
"""

import logging
from datetime import datetime, date
import psycopg2.extras
from models.database import get_conn
from services.time_service import get_oman_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Driver CRUD
# ---------------------------------------------------------------------------

def get_drivers(tenant_id, search_query=None, status=None, limit=1000):
    """
    Get all drivers for a tenant with optional search filtering by name/phone/license.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT driver_id, name, rfid_tag, phone, company_name, tenant_id, 
                   license_number, photo_url, department, team, status, created_at
            FROM drivers
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND tenant_id = %s"
            params.append(tenant_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        if search_query:
            query += " AND (name ILIKE %s OR phone ILIKE %s OR license_number ILIKE %s OR driver_id ILIKE %s)"
            like_val = f"%{search_query}%"
            params.extend([like_val, like_val, like_val, like_val])
            
        query += " ORDER BY name ASC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching drivers: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_driver(tenant_id, data):
    """
    Create a new driver in the database.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        driver_id = data.get('driver_id')
        if not driver_id:
            import uuid
            driver_id = f"DRV-{str(uuid.uuid4())[:8].upper()}"
            
        cur.execute("""
            INSERT INTO drivers 
            (driver_id, name, rfid_tag, phone, company_name, tenant_id, 
             license_number, photo_url, department, team, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            driver_id,
            data.get('name'),
            data.get('rfid_tag') or None,
            data.get('phone') or None,
            data.get('company_name'),
            tenant_id,
            data.get('license_number') or None,
            data.get('photo_url') or None,
            data.get('department') or None,
            data.get('team') or None,
            data.get('status') or 'active',
            now
        ))
        
        # If rfid_tag is specified, update the tag status in rfid_tags to assigned
        if data.get('rfid_tag'):
            cur.execute("""
                INSERT INTO rfid_tags (tenant_id, tag_id, status, created_at)
                VALUES (%s, %s, 'assigned', %s)
                ON CONFLICT (tag_id) DO UPDATE SET status = 'assigned'
            """, (tenant_id, data['rfid_tag'], now))
            
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating driver: {e}")
        return False
    finally:
        cur.close(); conn.close()

def update_driver(tenant_id, driver_id, data):
    """
    Update driver details securely.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE drivers
            SET name = %s,
                rfid_tag = %s,
                phone = %s,
                company_name = %s,
                license_number = %s,
                photo_url = %s,
                department = %s,
                team = %s,
                status = %s
            WHERE driver_id = %s AND tenant_id = %s
        """, (
            data.get('name'),
            data.get('rfid_tag') or None,
            data.get('phone') or None,
            data.get('company_name'),
            data.get('license_number') or None,
            data.get('photo_url') or None,
            data.get('department') or None,
            data.get('team') or None,
            data.get('status') or 'active',
            driver_id,
            tenant_id
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating driver {driver_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

def delete_driver(tenant_id, driver_id):
    """
    Remove a driver. Updates mapped RFID tags status back to 'available'.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Get driver's RFID tag
        cur.execute("SELECT rfid_tag FROM drivers WHERE driver_id = %s AND tenant_id = %s", (driver_id, tenant_id))
        row = cur.fetchone()
        tag_id = row[0] if row else None
        
        cur.execute("DELETE FROM drivers WHERE driver_id = %s AND tenant_id = %s", (driver_id, tenant_id))
        
        if tag_id:
            cur.execute("UPDATE rfid_tags SET status = 'available' WHERE tag_id = %s", (tag_id,))
            
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting driver {driver_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# RFID Management
# ---------------------------------------------------------------------------

def get_rfid_tags(tenant_id):
    """
    Get all RFID tags.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = "SELECT id, tag_id, status, created_at FROM rfid_tags"
        params = []
        if tenant_id:
            query += " WHERE tenant_id = %s"
            params.append(tenant_id)
        query += " ORDER BY tag_id ASC"
        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching RFID tags: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_rfid_tag(tenant_id, tag_id):
    """
    Add a new RFID tag to inventory.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            INSERT INTO rfid_tags (tenant_id, tag_id, status, created_at)
            VALUES (%s, %s, 'available', %s)
            ON CONFLICT (tag_id) DO NOTHING
        """, (tenant_id, tag_id, now))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating RFID tag {tag_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# Attendance & Live Sessions
# ---------------------------------------------------------------------------

def get_driver_attendance(tenant_id, start_date=None, end_date=None):
    """
    Fetch driver attendance records including daily check-ins, check-outs,
    and total computed shift hours.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT a.id, a.driver_id, d.name as driver_name, a.tenant_id, a.date, 
                   a.first_checkin, a.last_checkout, a.total_hours
            FROM driver_attendance a
            LEFT JOIN drivers d ON a.driver_id = d.driver_id
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND a.tenant_id = %s"
            params.append(tenant_id)
        if start_date:
            query += " AND a.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND a.date <= %s"
            params.append(end_date)
            
        query += " ORDER BY a.date DESC, d.name ASC"
        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching attendance: {e}")
        return []
    finally:
        cur.close(); conn.close()

def get_driver_sessions(tenant_id):
    """
    Retrieve active and completed driver sessions from driver_sessions table.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT s.id, s.driver_id, d.name as driver_name, s.imei, v.name as vehicle_name,
                   s.login_time, s.logout_time, s.trip_id, s.ignition_state, s.created_at
            FROM driver_sessions s
            LEFT JOIN drivers d ON s.driver_id = d.driver_id
            LEFT JOIN vehicles v ON s.imei = v.unique_id
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND d.tenant_id = %s"
            params.append(tenant_id)
            
        query += " ORDER BY s.login_time DESC LIMIT 100"
        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching driver sessions: {e}")
        return []
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# CSV Export Helper
# ---------------------------------------------------------------------------

def generate_drivers_csv(tenant_id):
    """
    Generate CSV content for all drivers.
    """
    drivers = get_drivers(tenant_id)
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Driver ID', 'Name', 'RFID Tag', 'Phone', 'Company Name', 'Department', 'Team', 'Status', 'License Number'])
    
    for d in drivers:
        writer.writerow([
            d.get('driver_id', ''),
            d.get('name', ''),
            d.get('rfid_tag', ''),
            d.get('phone', ''),
            d.get('company_name', ''),
            d.get('department', ''),
            d.get('team', ''),
            d.get('status', ''),
            d.get('license_number', '')
        ])
    return output.getvalue()
