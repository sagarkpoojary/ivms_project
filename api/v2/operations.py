from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg
import os
from typing import List, Optional
from pydantic import BaseModel
from auth.api_utils import get_allowed_imeis, get_current_user
from services.report_service import get_period_dates
from datetime import datetime

router = APIRouter(prefix="/api/v2/ops", tags=["Operations"])

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

async def get_db():
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()

# --- Schemas ---
class SiteCreate(BaseModel):
    site_id: str
    name: str
    latitude: float
    longitude: float
    radius: Optional[int] = 100

class DriverCreate(BaseModel):
    driver_id: str
    name: str
    rfid_tag: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    department: Optional[str] = None
    team: Optional[str] = None

# --- Sites ---
@router.get("/sites")
async def list_sites(
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    tenant_id = user.get('email') if user.get('role') == 'main_admin' else user.get('parent_email')
    if user.get('role') == 'super_admin':
        rows = await db.fetch("SELECT * FROM sites")
    else:
        rows = await db.fetch("SELECT * FROM sites WHERE tenant_id = $1", tenant_id)
    return [dict(row) for row in rows]

@router.post("/sites")
async def create_site(
    site: SiteCreate,
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    if user.get('role') not in ['admin', 'main_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Permission denied")
        
    tenant_id = user.get('email') if user.get('role') == 'main_admin' else user.get('parent_email')
    
    await db.execute("""
        INSERT INTO sites (site_id, tenant_id, name, latitude, longitude, radius)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (site_id) DO UPDATE SET
        name = EXCLUDED.name, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, radius = EXCLUDED.radius
    """, site.site_id, tenant_id, site.name, site.latitude, site.longitude, site.radius)
    
    return {"status": "success"}

# --- Drivers ---
@router.get("/drivers")
async def list_drivers(
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    tenant_id = user.get('email') if user.get('role') == 'main_admin' else user.get('parent_email')
    if user.get('role') == 'super_admin':
        rows = await db.fetch("SELECT * FROM drivers")
    else:
        rows = await db.fetch("SELECT * FROM drivers WHERE tenant_id = $1", tenant_id)
    return [dict(row) for row in rows]

@router.post("/drivers")
async def create_driver(
    driver: DriverCreate,
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    if user.get('role') not in ['admin', 'main_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Permission denied")
        
    tenant_id = user.get('email') if user.get('role') == 'main_admin' else user.get('parent_email')
    
    await db.execute("""
        INSERT INTO drivers (driver_id, tenant_id, name, rfid_tag, phone, license_number, department, team)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (driver_id) DO UPDATE SET
        name = EXCLUDED.name, rfid_tag = EXCLUDED.rfid_tag, phone = EXCLUDED.phone,
        license_number = EXCLUDED.license_number, department = EXCLUDED.department, team = EXCLUDED.team
    """, driver.driver_id, tenant_id, driver.name, driver.rfid_tag, 
       driver.phone, driver.license_number, driver.department, driver.team)
    
    return {"status": "success"}

# --- Site Visits ---
@router.get("/site-visits")
async def list_site_visits(
    period: str = 'Today',
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    start_dt, end_dt = get_period_dates(period)
    
    rows = await db.fetch("""
        SELECT v.*, s.name as site_name, veh.name as vehicle_name
        FROM site_visits v
        JOIN sites s ON v.site_id = s.site_id
        LEFT JOIN vehicles veh ON v.imei = veh.unique_id
        WHERE v.arrival_time BETWEEN $1 AND $2 AND v.imei = ANY($3)
        ORDER BY v.arrival_time DESC
    """, start_dt, end_dt, allowed_imeis)
    
    return [dict(row) for row in rows]

# --- Service Tickets ---
@router.get("/service-tickets")
async def list_service_tickets(
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    rows = await db.fetch("""
        SELECT t.*, v.name as vehicle_name 
        FROM service_tickets t 
        LEFT JOIN vehicles v ON t.imei = v.unique_id
        WHERE t.imei = ANY($1)
        ORDER BY t.created_at DESC
    """, allowed_imeis)
    
    return [dict(row) for row in rows]

# --- Driver Attendance ---
@router.get("/driver-attendance")
async def list_driver_attendance(
    period: str = 'Today',
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    start_dt, end_dt = get_period_dates(period)
    
    rows = await db.fetch("""
        SELECT s.*, d.name as driver_name, d.rfid_tag, v.name as vehicle_name
        FROM driver_sessions s
        JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN vehicles v ON s.imei = v.unique_id
        WHERE s.login_time BETWEEN $1 AND $2 AND s.imei = ANY($3)
        ORDER BY s.login_time DESC
    """, start_dt, end_dt, allowed_imeis)
    
    return [dict(row) for row in rows]

@router.get("/rfid-timeline")
async def list_rfid_timeline(
    imei: Optional[str] = None,
    period: str = 'Today',
    allowed_imeis: List[str] = Depends(get_allowed_imeis),
    db = Depends(get_db)
):
    start_dt, end_dt = get_period_dates(period)
    
    query = """
        SELECT e.*, d.name as driver_name
        FROM rfid_events e
        LEFT JOIN drivers d ON e.driver_id = d.driver_id
        WHERE e.timestamp BETWEEN $1 AND $2
    """
    params = [start_dt, end_dt]
    
    if imei:
        if imei not in allowed_imeis:
            raise HTTPException(status_code=403, detail="Access denied")
        query += " AND e.imei = $3"
        params.append(imei)
    else:
        query += " AND e.imei = ANY($3)"
        params.append(allowed_imeis)
        
    query += " ORDER BY e.timestamp DESC LIMIT 200"
    rows = await db.fetch(query, *params)
    
    return [dict(row) for row in rows]
