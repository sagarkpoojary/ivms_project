"""
IVMS Maintenance Service
========================
Provides business logic and PostgreSQL persistence for the Maintenance module:
- Calendar view list & schedule CRUD
- Upcoming & overdue service checks (mileage/hours limit checks)
- Maintenance completions, cost logs, and document attachment registrations
- Detailed dashboard widget analytics
"""

import logging
from datetime import datetime
import psycopg2.extras
from models.database import get_conn
from services.time_service import get_oman_now

logger = logging.getLogger(__name__)

def get_maintenance_schedules(tenant_id, status=None, limit=1000):
    """
    Fetch active maintenance schedules for a tenant, optionally filtered by status.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT id, tenant_id, vehicle_id, imei, service_type, description, 
                   target_mileage, target_engine_hours, target_date, recurring, 
                   mileage_interval, time_interval_days, status, workshop_id, 
                   technician_name, created_at, updated_at
            FROM maintenance_schedule
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND tenant_id = %s"
            params.append(tenant_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY target_date ASC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching maintenance schedules: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_maintenance_schedule(tenant_id, data):
    """
    Create a new scheduled maintenance task in the database.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            INSERT INTO maintenance_schedule 
            (tenant_id, vehicle_id, imei, service_type, description, 
             target_mileage, target_engine_hours, target_date, recurring, 
             mileage_interval, time_interval_days, status, workshop_id, 
             technician_name, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'planned', %s, %s, %s, %s)
            RETURNING id
        """, (
            tenant_id,
            data.get('vehicle_name'),
            data.get('imei'),
            data.get('service_type'),
            data.get('description'),
            int(data['target_mileage']) if data.get('target_mileage') else None,
            int(data['target_engine_hours']) if data.get('target_engine_hours') else None,
            data.get('target_date') or None,
            bool(data.get('recurring')),
            int(data['mileage_interval']) if data.get('mileage_interval') else None,
            int(data['time_interval_days']) if data.get('time_interval_days') else None,
            int(data['workshop_id']) if data.get('workshop_id') else None,
            data.get('technician_name') or None,
            now,
            now
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating maintenance schedule: {e}")
        return False
    finally:
        cur.close(); conn.close()

def get_upcoming_maintenance_with_alerts(tenant_id):
    """
    Return upcoming maintenance, computing live 'due soon' and 'overdue' flags 
    by checking vehicle live status counters (date, current mileage, and engine hours).
    """
    schedules = get_maintenance_schedules(tenant_id, status='planned')
    
    # Load live vehicle updates to check live limits
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT imei, speed, longitude, latitude, status, ignition, current_driver_name FROM live_vehicle_status")
        live_data = {r['imei']: r for r in cur.fetchall()}
        
        # We'll also fetch vehicle mileage and engine hours from the latest telemetry/aggregates or static details
        cur.execute("SELECT unique_id, data FROM vehicles")
        v_data = {r['unique_id']: dict(r['data']) for r in cur.fetchall() if r['data']}
    except Exception as e:
        logger.error(f"Error fetching live counters for alerts: {e}")
        live_data = {}
        v_data = {}
    finally:
        cur.close(); conn.close()

    result = []
    now = get_oman_now().date()
    
    for item in schedules:
        imei = item.get('imei')
        v_info = v_data.get(imei, {})
        
        # Check current odometer/engine hours from vehicles data payload
        cur_mileage = float(v_info.get('odometer', 0))
        cur_hours = float(v_info.get('engine_hours', 0))
        
        # Compute days and limit diffs
        days_left = None
        if item.get('target_date'):
            t_date = item['target_date']
            if isinstance(t_date, str):
                t_date = datetime.strptime(t_date, "%Y-%m-%d").date()
            days_left = (t_date - now).days
            
        mileage_left = None
        if item.get('target_mileage'):
            mileage_left = item['target_mileage'] - cur_mileage
            
        hours_left = None
        if item.get('target_engine_hours'):
            hours_left = item['target_engine_hours'] - cur_hours

        # Determine alert status
        is_overdue = False
        is_due_soon = False
        
        # Overdue checks
        if days_left is not None and days_left < 0:
            is_overdue = True
        if mileage_left is not None and mileage_left < 0:
            is_overdue = True
        if hours_left is not None and hours_left < 0:
            is_overdue = True
            
        # Due soon checks (within 7 days, 500 km, or 50 hours)
        if not is_overdue:
            if days_left is not None and days_left <= 7:
                is_due_soon = True
            if mileage_left is not None and mileage_left <= 500:
                is_due_soon = True
            if hours_left is not None and hours_left <= 50:
                is_due_soon = True

        status_label = 'planned'
        if is_overdue:
            status_label = 'overdue'
        elif is_due_soon:
            status_label = 'due'
            
        item_copy = dict(item)
        item_copy['live_status'] = status_label
        item_copy['days_left'] = days_left
        item_copy['mileage_left'] = mileage_left
        item_copy['hours_left'] = hours_left
        item_copy['current_mileage'] = cur_mileage
        item_copy['current_hours'] = cur_hours
        result.append(item_copy)

    return result

def complete_maintenance(tenant_id, schedule_id, data):
    """
    Mark a maintenance event as completed. Writes records to maintenance_history,
    updates the schedule status, and links document attachments if present.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        
        # 1. Fetch details of the schedule
        cur.execute("""
            SELECT vehicle_id, imei, service_type, description, target_date
            FROM maintenance_schedule
            WHERE id = %s AND tenant_id = %s
        """, (schedule_id, tenant_id))
        sched = cur.fetchone()
        if not sched:
            return False, "Schedule task not found"
            
        vehicle_id, imei, service_type, description, target_date = sched
        
        # 2. Insert into maintenance_history
        cur.execute("""
            INSERT INTO maintenance_history 
            (schedule_id, tenant_id, vehicle_id, imei, service_type, completion_date, 
             mileage_at_service, engine_hours_at_service, total_cost, workshop_id, 
             technician_name, notes, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'completed', %s)
            RETURNING id
        """, (
            schedule_id,
            tenant_id,
            vehicle_id,
            imei,
            service_type,
            data.get('completion_date') or now.date(),
            int(data['mileage_at_service']) if data.get('mileage_at_service') else None,
            int(data['engine_hours_at_service']) if data.get('engine_hours_at_service') else None,
            float(data['total_cost']) if data.get('total_cost') else 0.0,
            int(data['workshop_id']) if data.get('workshop_id') else None,
            data.get('technician_name') or None,
            data.get('notes') or '',
            now
        ))
        history_id = cur.fetchone()[0]

        # 3. Handle documents link
        attachments = data.get('attachments') or []
        for attach in attachments:
            cur.execute("""
                INSERT INTO maintenance_attachments (history_id, file_name, file_path, file_type, uploaded_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (history_id, attach.get('name'), attach.get('path'), attach.get('type'), now))

        # 4. Update the schedule task status
        # If it's recurring, calculate next date and reset status to 'planned', otherwise mark 'completed'
        cur.execute("SELECT recurring, mileage_interval, time_interval_days FROM maintenance_schedule WHERE id = %s", (schedule_id,))
        rec_row = cur.fetchone()
        is_recurring = rec_row[0] if rec_row else False
        
        if is_recurring:
            mileage_interval, time_interval = rec_row[1], rec_row[2]
            next_date = None
            if time_interval and target_date:
                # Target date calculation
                from datetime import timedelta
                next_date = target_date + timedelta(days=time_interval)
            
            cur.execute("""
                UPDATE maintenance_schedule
                SET status = 'planned', 
                    target_date = %s,
                    target_mileage = CASE WHEN target_mileage IS NOT NULL AND %s IS NOT NULL THEN target_mileage + %s ELSE target_mileage END,
                    updated_at = %s
                WHERE id = %s
            """, (next_date, mileage_interval, mileage_interval, now, schedule_id))
        else:
            cur.execute("""
                UPDATE maintenance_schedule
                SET status = 'completed', updated_at = %s
                WHERE id = %s
            """, (now, schedule_id))

        conn.commit()
        return True, "Maintenance successfully completed"
    except Exception as e:
        conn.rollback()
        logger.error(f"Error completing maintenance: {e}")
        return False, str(e)
    finally:
        cur.close(); conn.close()

def get_maintenance_history(tenant_id, limit=100):
    """
    Fetch completed maintenance history with linked attachments and workshop names.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT h.id, h.schedule_id, h.tenant_id, h.vehicle_id, h.imei, h.service_type, 
                   h.completion_date, h.mileage_at_service, h.engine_hours_at_service, 
                   h.total_cost, h.workshop_id, w.name as workshop_name, h.technician_name, 
                   h.notes, h.status, h.created_at
            FROM maintenance_history h
            LEFT JOIN maintenance_workshops w ON h.workshop_id = w.id
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND h.tenant_id = %s"
            params.append(tenant_id)
        query += " ORDER BY h.completion_date DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        
        # Load attachments for these history records
        if rows:
            hist_ids = [r['id'] for r in rows]
            cur.execute("""
                SELECT id, history_id, file_name, file_path, file_type, uploaded_at 
                FROM maintenance_attachments 
                WHERE history_id = ANY(%s)
            """, (hist_ids,))
            attach_rows = cur.fetchall()
            
            # Map history_id to list of attachments
            attach_map = {}
            for a in attach_rows:
                h_id = a['history_id']
                attach_map.setdefault(h_id, []).append({
                    "id": a['id'],
                    "name": a['file_name'],
                    "path": a['file_path'],
                    "type": a['file_type'],
                    "uploaded_at": a['uploaded_at'].isoformat() if a['uploaded_at'] else None
                })
                
            for r in rows:
                r['attachments'] = attach_map.get(r['id'], [])
                
        return rows
    except Exception as e:
        logger.error(f"Error fetching maintenance history: {e}")
        return []
    finally:
        cur.close(); conn.close()

def get_maintenance_workshops(tenant_id):
    """
    Get all registered service workshops.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = "SELECT id, name, address, phone, email, specialty FROM maintenance_workshops"
        params = []
        if tenant_id:
            query += " WHERE tenant_id = %s OR tenant_id IS NULL"
            params.append(tenant_id)
        query += " ORDER BY name ASC"
        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching workshops: {e}")
        return []
    finally:
        cur.close(); conn.close()

def get_maintenance_stats(tenant_id):
    """
    Return statistics for the planned, due soon, overdue, and monthly costs metrics.
    """
    upcoming = get_upcoming_maintenance_with_alerts(tenant_id)
    history = get_maintenance_history(tenant_id, limit=1000)
    
    planned = sum(1 for item in upcoming if item['live_status'] == 'planned')
    due = sum(1 for item in upcoming if item['live_status'] == 'due')
    overdue = sum(1 for item in upcoming if item['live_status'] == 'overdue')
    
    # Calculate costs for the current month
    now = get_oman_now()
    cur_year = now.year
    cur_month = now.month
    
    total_cost_month = 0.0
    for h in history:
        comp_date = h.get('completion_date')
        if comp_date:
            if isinstance(comp_date, str):
                comp_date = datetime.strptime(comp_date, "%Y-%m-%d").date()
            if comp_date.year == cur_year and comp_date.month == cur_month:
                total_cost_month += float(h.get('total_cost') or 0.0)

    return {
        "planned": planned,
        "due": due,
        "overdue": overdue,
        "completed": len(history),
        "monthly_cost": round(total_cost_month, 2)
    }
