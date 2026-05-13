from fastapi import APIRouter, Depends, HTTPException
import asyncpg
import os
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/devices", tags=["Devices"])

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

class DeviceCreate(BaseModel):
    imei: str
    name: Optional[str] = None
    profile_id: Optional[int] = None
    template_id: Optional[int] = None

async def get_db():
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()

@router.get("/")
async def list_devices(db = Depends(get_db)):
    # Join with live_vehicle_status to get current position and status
    rows = await db.fetch("""
        SELECT 
            d.imei as "uniqueId",
            d.name,
            ls.status,
            ls.last_timestamp as "lastUpdate",
            ls.latitude,
            ls.longitude,
            ls.speed,
            ls.ignition,
            p.name as profile_name
        FROM devices d
        LEFT JOIN live_vehicle_status ls ON d.imei = ls.imei
        LEFT JOIN device_profiles p ON d.profile_id = p.id
        ORDER BY ls.last_timestamp DESC NULLS LAST
    """)
    
    devices = []
    for row in rows:
        d = dict(row)
        # Nest position for frontend compatibility
        d['position'] = {
            'latitude': d.pop('latitude'),
            'longitude': d.pop('longitude'),
            'speed': d.get('speed'),
            'ignition': d.get('ignition')
        }
        devices.append(d)
    return devices

@router.post("/")
async def create_device(device: DeviceCreate, db = Depends(get_db)):
    try:
        await db.execute(
            """INSERT INTO devices (imei, name, profile_id, template_id)
               VALUES ($1, $2, $3, $4)""",
            device.imei, device.name, device.profile_id, device.template_id
        )
        return {"status": "success", "imei": device.imei}
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Device already exists")

@router.get("/profiles")
async def list_profiles(db = Depends(get_db)):
    rows = await db.fetch("SELECT * FROM device_profiles")
    return [dict(row) for row in rows]

@router.get("/templates")
async def list_templates(db = Depends(get_db)):
    rows = await db.fetch("SELECT * FROM config_templates")
    return [dict(row) for row in rows]
