from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from auth.api_utils import get_allowed_imeis
from services.analytics_service import analytics_service
from services.time_service import get_oman_now, get_period_dates

router = APIRouter()

@router.get("/fleet-efficiency")
async def fleet_efficiency(period: str = 'This Week', allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    try:
        start_dt, end_dt = get_period_dates(period)
        vehicles = [{"unique_id": imei} for imei in allowed_imeis]
        return analytics_service.get_fleet_efficiency(vehicles, start_dt, end_dt)
    except Exception as e:
        return {"total_distance": 0, "active_trips": 0, "idle_duration_hours": 0, "fuel_consumed_liters": 0, "efficiency_score": 0, "error": str(e)}

@router.get("/driver-score")
async def driver_scores(period: str = 'This Week', allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    try:
        start_dt, end_dt = get_period_dates(period)
        profiles = analytics_service.get_driver_profiles(start_dt, end_dt, allowed_imeis)
        
        scores = []
        for p in profiles:
            violations = p['overspeed_count'] + p['harsh_braking'] + p['harsh_acceleration']
            scores.append({
                "name": p['name'],
                "driver_id": p['driver_id'],
                "score": p['score'],
                "violations": violations,
                "rank": "Gold" if p['score'] > 90 else "Silver" if p['score'] > 75 else "Bronze"
            })
        return {"scores": scores}
    except Exception as e:
        return {"scores": []}

@router.get("/events")
async def event_intelligence(period: str = 'Today', allowed_imeis: List[str] = Depends(get_allowed_imeis)):
    try:
        from services.native_report_service import native_report_service
        start_dt, end_dt = get_period_dates(period)
        events = native_report_service.get_analytics_events(None, 'all', start_dt, end_dt, allowed_imeis)
        for e in events:
            etype = e.get('event_type')
            if etype in ['overspeed', 'harsh_braking', 'harsh_acceleration', 'unauthorized_rfid']:
                e['severity'] = 'ERROR'
            elif etype in ['idle', 'offline', 'low_battery']:
                e['severity'] = 'WARNING'
            elif etype in ['trip_start', 'trip_end', 'login', 'logout']:
                e['severity'] = 'INFO'
            else:
                e['severity'] = 'INFO'
        return events
    except Exception as e:
        return []
