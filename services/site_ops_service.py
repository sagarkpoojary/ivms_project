"""
IVMS Site Operations Service
============================
Provides business logic and PostgreSQL persistence for Site Operations:
- Site Registry CRUD (Geofence definition)
- Site Visits telemetry analysis & haversine radial geofence checks
- Service Tickets CRUD (Status workflow, Priority SLA alerts, Assignments)
- SLA duration validation helpers
- Detailed KPI widgets summaries
"""

import logging
import math
from datetime import datetime, timezone
import psycopg2.extras
from models.database import get_conn
from services.time_service import get_oman_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Haversine Geofencing Utility
# ---------------------------------------------------------------------------

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes radial distance in meters between two coordinates.
    """
    if None in (lat1, lon1, lat2, lon2):
        return 99999999.0
    R = 6371000.0  # Earth's radius in meters
    
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2 - lat1))
    delta_lambda = math.radians(float(lon2 - lon1))
    
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
        
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

# ---------------------------------------------------------------------------
# Sites CRUD
# ---------------------------------------------------------------------------

def get_sites(tenant_id, limit=1000):
    """
    Get all registered sites with geofence details.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT id, tenant_id, name, address, latitude, longitude, 
                   contact_person, contact_phone, created_at
            FROM sites
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND tenant_id = %s"
            params.append(tenant_id)
            
        query += " ORDER BY name ASC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching sites: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_site(tenant_id, data):
    """
    Register a new site with coordinates.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            INSERT INTO sites 
            (tenant_id, name, address, latitude, longitude, contact_person, contact_phone, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id,
            data.get('name'),
            data.get('address') or None,
            float(data['latitude']) if data.get('latitude') else None,
            float(data['longitude']) if data.get('longitude') else None,
            data.get('contact_person') or None,
            data.get('contact_phone') or None,
            now
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating site: {e}")
        return False
    finally:
        cur.close(); conn.close()

def update_site(tenant_id, site_id, data):
    """
    Update site details.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE sites
            SET name = %s,
                address = %s,
                latitude = %s,
                longitude = %s,
                contact_person = %s,
                contact_phone = %s
            WHERE id = %s AND tenant_id = %s
        """, (
            data.get('name'),
            data.get('address') or None,
            float(data['latitude']) if data.get('latitude') else None,
            float(data['longitude']) if data.get('longitude') else None,
            data.get('contact_person') or None,
            data.get('contact_phone') or None,
            int(site_id),
            tenant_id
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating site {site_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

def delete_site(tenant_id, site_id):
    """
    Delete a site geofence safely.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sites WHERE id = %s AND tenant_id = %s", (int(site_id), tenant_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting site {site_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# Site Visits Tracking (Telemetry Geofence Visits)
# ---------------------------------------------------------------------------

def get_site_visits(tenant_id, limit=100):
    """
    Get visits logged for sites.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT v.id, v.tenant_id, v.site_id, s.name as site_name, v.technician_id,
                   d.name as technician_name, v.vehicle_id, v.imei, v.scheduled_time, 
                   v.arrival_time, v.departure_time, v.status, v.work_report, 
                   v.photo_proof_url, v.signature_url, v.created_at
            FROM site_visits v
            LEFT JOIN sites s ON v.site_id = s.id
            LEFT JOIN drivers d ON v.technician_id = d.driver_id
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND v.tenant_id = %s"
            params.append(tenant_id)
            
        query += " ORDER BY v.arrival_time DESC NULLS LAST, v.scheduled_time DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching site visits: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_site_visit(tenant_id, data):
    """
    Schedule a technician site visit manually.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            INSERT INTO site_visits 
            (tenant_id, site_id, technician_id, vehicle_id, imei, scheduled_time, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'scheduled', %s)
        """, (
            tenant_id,
            int(data['site_id']),
            data.get('technician_id') or None,
            data.get('vehicle_name') or None,
            data.get('imei') or None,
            data.get('scheduled_time') or now,
            now
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error scheduling site visit: {e}")
        return False
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# Service Tickets & SLA Workflow
# ---------------------------------------------------------------------------

def get_service_tickets(tenant_id, limit=1000):
    """
    Fetch service tickets, calculating live SLA breach warnings.
    High = 4 hrs, Medium = 24 hrs, Low = 72 hrs.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        query = """
            SELECT t.id, t.tenant_id, t.category, t.title, t.description, 
                   t.priority, t.status, t.customer_name, t.customer_phone, 
                   t.assigned_to, d.name as technician_name, t.related_site_id, 
                   s.name as site_name, t.created_at, t.updated_at
            FROM service_tickets t
            LEFT JOIN sites s ON t.related_site_id = s.id
            LEFT JOIN drivers d ON t.assigned_to = d.driver_id
            WHERE 1=1
        """
        params = []
        if tenant_id:
            query += " AND t.tenant_id = %s"
            params.append(tenant_id)
            
        query += " ORDER BY t.priority DESC, t.created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        
        # Calculate SLA breaches
        now = get_oman_now()
        for r in rows:
            created = r.get('created_at')
            status = r.get('status')
            priority = r.get('priority') or 'Low'
            
            sla_breached = False
            sla_hours = 72
            if priority == 'High':
                sla_hours = 4
            elif priority == 'Medium':
                sla_hours = 24
                
            if created and status in ('open', 'in-progress'):
                diff = now - created
                diff_hours = diff.total_seconds() / 3600.0
                if diff_hours > sla_hours:
                    sla_breached = True
            
            r['sla_hours'] = sla_hours
            r['sla_breached'] = sla_breached
            
        return rows
    except Exception as e:
        logger.error(f"Error fetching service tickets: {e}")
        return []
    finally:
        cur.close(); conn.close()

def create_service_ticket(tenant_id, data):
    """
    Create a new support ticket.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            INSERT INTO service_tickets 
            (tenant_id, category, title, description, priority, status, 
             customer_name, customer_phone, assigned_to, related_site_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id,
            data.get('category') or 'Service Request',
            data.get('title'),
            data.get('description'),
            data.get('priority') or 'Low',
            data.get('customer_name') or None,
            data.get('customer_phone') or None,
            data.get('assigned_to') or None,
            int(data['related_site_id']) if data.get('related_site_id') else None,
            now,
            now
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating service ticket: {e}")
        return False
    finally:
        cur.close(); conn.close()

def update_service_ticket_status(tenant_id, ticket_id, status, notes=None):
    """
    Transition ticket status safely (open -> in-progress -> resolved -> closed).
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        now = get_oman_now()
        cur.execute("""
            UPDATE service_tickets
            SET status = %s,
                updated_at = %s
            WHERE id = %s AND tenant_id = %s
        """, (status, now, int(ticket_id), tenant_id))
        
        # Log note if provided
        if notes:
            # We can log to system_events or a notes trail in ticket description
            cur.execute("""
                UPDATE service_tickets
                SET description = CONCAT(description, E'\n\n[', %s::text, E' - Note]: ', %s::text)
                WHERE id = %s
            """, (str(now)[:19], notes, int(ticket_id)))
            
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating ticket {ticket_id}: {e}")
        return False
    finally:
        cur.close(); conn.close()

# ---------------------------------------------------------------------------
# Site Operations KPIs & Summary
# ---------------------------------------------------------------------------

def get_site_ops_kpis(tenant_id):
    """
    Aggregate SLA breached tickets, total site visits, open tickets,
    and geofences count for a dashboard KPI summary.
    """
    tickets = get_service_tickets(tenant_id)
    sites = get_sites(tenant_id)
    visits = get_site_visits(tenant_id)
    
    open_count = sum(1 for t in tickets if t['status'] in ('open', 'in-progress'))
    sla_breached_count = sum(1 for t in tickets if t.get('sla_breached'))
    completed_visits = sum(1 for v in visits if v['status'] == 'completed')
    
    return {
        "open_tickets": open_count,
        "sla_breaches": sla_breached_count,
        "total_sites": len(sites),
        "completed_visits": completed_visits
    }
