from datetime import datetime, timedelta
from services.time_service import get_oman_now, SYSTEM_TZ
from flask import request, session, render_template, current_app
from models.database import load_server_config
from auth.utils import get_filtered_vehicles
from extensions import cache
from config import Config
import json

def get_period_dates(period, from_str=None, to_str=None):
    now = get_oman_now()
    start_dt = now
    end_dt = now
    
    if period == 'Yesterday':
        start_dt = now - timedelta(days=1)
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999)
    elif period == 'This Week':
        start_dt = now - timedelta(days=now.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'This Month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'Custom' and from_str:
        try:
            start_dt = datetime.strptime(from_str, '%Y-%m-%dT%H:%M')
            start_dt = SYSTEM_TZ.localize(start_dt)
            if to_str:
                end_dt = datetime.strptime(to_str, '%Y-%m-%dT%H:%M')
                end_dt = SYSTEM_TZ.localize(end_dt)
        except:
            pass
    else: # Today
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        
    return start_dt, end_dt

def render_report_logic(forced_report_type=None):
    if not session.get('logged_in'):
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    all_vehicles = get_filtered_vehicles()
    period = request.args.get('period', 'Today')
    filter_uid = request.args.get('unique_id')
    filter_company = request.args.get('company_filter')
    
    vehicles = all_vehicles
    if filter_company:
        vehicles = [v for v in all_vehicles if v.get('company_name') == filter_company]
    
    report_type = forced_report_type or request.args.get('report_type', 'Trips')
    start_dt, end_dt = get_period_dates(period, request.args.get('from'), request.args.get('to'))

    from_str_display = start_dt.strftime('%Y-%m-%dT%H:%M')
    to_str_display = end_dt.strftime('%Y-%m-%dT%H:%M')
    
    from services.native_report_service import native_report_service
    
    report_data = []
    if not filter_uid:
        report_data = native_report_service.get_fleet_summary(vehicles, start_dt, end_dt)

    trip_data = []
    stop_data_on = []
    stop_data_off = []
    combined_data = []
    route_data = []
    
    summary_distance = 0
    summary_duration = 0
    summary_avg_speed = 0
    summary_idle_time = 0

    if filter_uid:
        # Fetch detailed reports for a single vehicle
        if report_type == 'Trips':
            trips = native_report_service.get_trip_report(filter_uid, start_dt, end_dt)
            for t in trips:
                trip_data.append({
                    'deviceId': t['imei'],
                    'deviceName': t['imei'],
                    'startTime': t['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'endTime': t['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'distance': f"{round(t['distance_km'], 2)} km",
                    'averageSpeed': f"{round(t['avg_speed'], 2)} km/h",
                    'maxSpeed': f"{round(t['max_speed'], 2)} km/h",
                    'duration': t['duration_sec'] * 1000,
                    'startAddress': t.get('start_address', 'N/A'),
                    'endAddress': t.get('end_address', 'N/A'),
                    'spentFuel': f"{round(t['fuel_consumed'], 2)} L"
                })
        
        elif report_type == 'Stops' or report_type == 'Combined':
            # For stops/idle, we look at analytics_events
            idle_events = native_report_service.get_analytics_events(filter_uid, 'idle', start_dt, end_dt)
            for ev in idle_events:
                stop_data_on.append({
                    'startTime': ev['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                    'duration': ev['value'] * 1000,
                    'address': ev.get('location', 'N/A'),
                    'engine': 'ON'
                })
            
            if report_type == 'Combined':
                # Playback route
                records = native_report_service.get_playback_data(filter_uid, start_dt, end_dt)
                for r in records:
                    route_data.append({
                        'fixTime': r['timestamp'].isoformat(),
                        'latitude': r['latitude'],
                        'longitude': r['longitude'],
                        'speed': r['speed']
                    })

    # Summary for cards
    if filter_uid:
        s_list = native_report_service.get_fleet_summary([v for v in vehicles if str(v.get('unique_id')) == str(filter_uid)], start_dt, end_dt)
        if s_list:
            s = s_list[0]
            summary_distance = s['total_distance']
            summary_duration = s['total_duration'] * 1000
            summary_avg_speed = s['average_speed']
            summary_idle_time = s['idle_duration']

    return render_template('pre_reg_report.html', 
                          report_data=report_data, 
                          trip_data=trip_data, 
                          stop_data_on=stop_data_on,
                          stop_data_off=stop_data_off,
                          combined_data=combined_data,
                          route_data=route_data,
                          summary_distance=summary_distance,
                          summary_duration=summary_duration,
                          summary_avg_speed=summary_avg_speed,
                          summary_idle_time=summary_idle_time,
                          from_date=from_str_display, 
                          to_date=to_str_display, 
                          vehicles=all_vehicles, 
                          selected_period=period, 
                          selected_uid=filter_uid,
                          selected_report_type=report_type,
                          role=session.get('role'))
