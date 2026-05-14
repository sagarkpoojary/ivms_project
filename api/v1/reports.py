from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg
import os
import json
from typing import List, Optional
from datetime import datetime
from core.utils import simplify_route
from fastapi import BackgroundTasks
import csv
import io

router = APIRouter()

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

async def get_db():
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()

@router.get("/history/{imei}")
async def get_history(
    imei: str,
    start: datetime,
    end: datetime,
    db = Depends(get_db)
):
    """Fetches raw telemetry history for playback."""
    rows = await db.fetch(
        """SELECT timestamp, latitude, longitude, speed, angle, ignition 
           FROM telemetry 
           WHERE imei = $1 AND timestamp BETWEEN $2 AND $3
           ORDER BY timestamp ASC""",
        imei, start, end
    )
    points = [dict(row) for row in rows]
    return simplify_route(points)

@router.get("/trips/{imei}")
async def get_trips(
    imei: str,
    start: datetime,
    end: datetime,
    db = Depends(get_db)
):
    """Fetches trip summary reports."""
    rows = await db.fetch(
        """SELECT * FROM trip_summary 
           WHERE imei = $1 AND start_time >= $2 AND (end_time <= $3 OR end_time IS NULL)
           ORDER BY start_time DESC""",
        imei, start, end
    )
    return [dict(row) for row in rows]

@router.get("/events/{imei}")
async def get_events(
    imei: str,
    event_type: Optional[str] = None,
    db = Depends(get_db)
):
    """Fetches analytics events (overspeed, trip start/end, etc)."""
    query = "SELECT * FROM analytics_events WHERE imei = $1"
    args = [imei]
    if event_type:
        query += " AND event_type = $2"
        args.append(event_type)
    query += " ORDER BY timestamp DESC LIMIT 100"
    
    rows = await db.fetch(query, *args)
    return [dict(row) for row in rows]

@router.get("/daily-summary/{imei}")
async def get_daily_summary(
    imei: str,
    days: int = 7,
    db = Depends(get_db)
):
    """Aggregated daily metrics."""
    rows = await db.fetch(
        """SELECT 
            DATE(start_time) as date,
            COUNT(*) as trip_count,
            SUM(distance_km) as total_distance,
            MAX(max_speed) as max_speed,
            SUM(idle_duration_sec) as total_idle_sec
           FROM trip_summary 
           WHERE imei = $1 AND start_time > NOW() - INTERVAL '1 day' * $2
           GROUP BY DATE(start_time)
           ORDER BY date DESC""",
        imei, days
    )
    return [dict(row) for row in rows]

@router.post("/export/history/{imei}")
async def export_history(
    imei: str,
    start: datetime,
    end: datetime,
    background_tasks: BackgroundTasks,
    db = Depends(get_db)
):
    """Triggers an async CSV export of telemetry history."""
    filename = f"export_{imei}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    filepath = f"/root/ivms_project/artifacts/exports/{filename}"
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    background_tasks.add_task(generate_csv_report, imei, start, end, filepath)
    
    return {"status": "success", "message": "Export started", "filename": filename}

async def generate_csv_report(imei, start, end, filepath):
    """Worker function for CSV generation."""
    # Note: We use a fresh connection in the worker to avoid pool issues
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT timestamp, latitude, longitude, speed, angle, ignition, io_elements FROM telemetry WHERE imei = $1 AND timestamp BETWEEN $2 AND $3 ORDER BY timestamp ASC",
            imei, start, end
        )
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Latitude', 'Longitude', 'Speed', 'Angle', 'Ignition', 'IO_Elements'])
            for r in rows:
                writer.writerow([r['timestamp'], r['latitude'], r['longitude'], r['speed'], r['angle'], r['ignition'], r['io_elements']])
    finally:
        await conn.close()
