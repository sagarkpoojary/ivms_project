import io
import csv
from datetime import datetime
import pytz
from services.time_service import get_oman_now
from flask import Blueprint, render_template, request, session, make_response
from auth.utils import role_required, get_filtered_vehicles
from services.report_service import render_report_logic, get_period_dates, fetch_cached_summaries
from services.traccar_service import full_traccar_host, get_traccar_session

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
@role_required('user')
def reports_home():
    return render_template('reports.html', vehicles=get_filtered_vehicles())

@reports_bp.route('/pre_reg_report')
@role_required('user')
def pre_reg_report():
    return render_report_logic()

@reports_bp.route('/reports/trips')
@role_required('user')
def report_trips():
    return render_report_logic('Trips')

@reports_bp.route('/reports/stops')
@role_required('user')
def report_stops():
    return render_report_logic('Stops')

@reports_bp.route('/reports/combined')
@role_required('user')
def report_combined():
    return render_report_logic('Combined')

@reports_bp.route('/reports/idle')
@role_required('user')
def report_idle():
    return render_report_logic('Idle')

@reports_bp.route('/api/reports/export')
@role_required('user')
def export_report():
    period = request.args.get('period', 'Today')
    report_type = request.args.get('report_type', 'Trips')
    filter_uid = request.args.get('unique_id')
    
    try:
        stop_threshold_mins = int(request.args.get('stop_threshold', 5))
    except ValueError:
        stop_threshold_mins = 5

    start_dt, end_dt = get_period_dates(period, request.args.get('from'), request.args.get('to'))
    # start_dt and end_dt are now aware (Oman). Convert to UTC for Traccar.
    traccar_from = start_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    traccar_to = end_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    vehicles = get_filtered_vehicles()
    
    company_filter = request.args.get('company_filter')
    if company_filter:
        vehicles = [v for v in vehicles if v.get('company_name') == company_filter]

    target_vehicles = vehicles
    if filter_uid:
        target_vehicles = [v for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]

    if not target_vehicles:
        return "No authorized vehicles found", 403

    s = get_traccar_session()
    traccar = full_traccar_host()
    si = io.StringIO()
    cw = csv.writer(si)

    if report_type == 'Trips':
        cw.writerow(['Device Name', 'Start Time', 'End Time', 'Distance', 'Avg Speed', 'Max Speed', 'Duration'])
        for v in target_vehicles:
            uid = v.get('unique_id')
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid}, timeout=30)
            if r_dev.status_code == 200:
                dev_list = r_dev.json()
                if dev_list:
                    internal_id = dev_list[0]['id']
                    r_trips = s.get(f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}", timeout=30)
                    if r_trips.status_code == 200:
                        raw_trips = r_trips.json()
                        raw_trips.sort(key=lambda x: x.get('startTime', ''))
                        processed = []
                        if raw_trips:
                            curr = raw_trips[0]
                            for i in range(1, len(raw_trips)):
                                next_t = raw_trips[i]
                                try:
                                    t_end = datetime.fromisoformat(curr['endTime'].replace('Z', '+00:00').split('.')[0])
                                    t_start = datetime.fromisoformat(next_t['startTime'].replace('Z', '+00:00').split('.')[0])
                                    gap_sec = (t_start - t_end).total_seconds()
                                    if gap_sec < (stop_threshold_mins * 60):
                                        curr['endTime'] = next_t['endTime']
                                        curr['distance'] += (next_t.get('distance') or 0)
                                        curr['duration'] = (next_t.get('duration') or 0) + (curr.get('duration') or 0) + (gap_sec * 1000)
                                        curr['maxSpeed'] = max((curr.get('maxSpeed') or 0), (next_t.get('maxSpeed') or 0))
                                    else:
                                        processed.append(curr)
                                        curr = next_t
                                except:
                                    processed.append(curr)
                                    curr = next_t
                            processed.append(curr)

                        for t in processed:
                            cw.writerow([
                                t.get('deviceName'), t.get('startTime'), t.get('endTime'),
                                f"{round((t.get('distance') or 0)/1000, 2)} km",
                                f"{round((t.get('averageSpeed') or 0)*1.852, 2)} km/h",
                                f"{round((t.get('maxSpeed') or 0)*1.852, 2)} km/h",
                                f"{round((t.get('duration') or 0)/3600000, 2)} h"
                            ])
    elif report_type == 'Stops':
        cw.writerow(['Device Name', 'Arrival', 'Departure', 'Duration', 'Address', 'Engine Status'])
        for v in target_vehicles:
            uid = v.get('unique_id')
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid}, timeout=30)
            if r_dev.status_code == 200:
                dev_list = r_dev.json()
                if dev_list:
                    internal_id = dev_list[0]['id']
                    r_stops = s.get(f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}", timeout=30)
                    if r_stops.status_code == 200:
                        try:
                            stops_data = r_stops.json()
                        except:
                            stops_data = []

                        for st in stops_data:
                            dur_ms = st.get('duration') or 0
                            if dur_ms < (stop_threshold_mins * 60 * 1000): continue
                            cw.writerow([
                                st.get('deviceName'), st.get('startTime'), st.get('endTime'),
                                f"{round(dur_ms/3600000, 2)} h",
                                st.get('address', 'N/A'),
                                "Engine ON" if st.get('engine') else "Engine OFF"
                            ])
    elif report_type == 'Combined':
        cw.writerow(['Time', 'Device', 'Event', 'Location', 'Details'])
        for v in target_vehicles:
            uid = v.get('unique_id')
            name = v.get('name')
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid}, timeout=30)
            if r_dev.status_code == 200:
                dev_list = r_dev.json()
                if dev_list:
                    internal_id = dev_list[0]['id']
                    
                    all_events = []
                    
                    # 1. Fetch Trips
                    r_t = s.get(f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}", timeout=30)
                    if r_t.status_code == 200:
                        for t in r_t.json():
                            all_events.append({
                                'time': t.get('startTime'),
                                'type': 'Trip Started',
                                'loc': t.get('startAddress', 'N/A'),
                                'details': f"Distance: {round(t.get('distance',0)/1000,2)}km"
                            })
                    
                    # 2. Fetch Stops
                    r_s = s.get(f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}", timeout=30)
                    if r_s.status_code == 200:
                        for st in r_s.json():
                            dur = round((st.get('duration') or 0)/60000, 1)
                            all_events.append({
                                'time': st.get('startTime'),
                                'type': 'Stopped/Parked',
                                'loc': st.get('address', 'N/A'),
                                'details': f"Duration: {dur} min, Engine: {'ON' if st.get('engine') else 'OFF'}"
                            })

                    # 3. Fetch Events (Alarms, Ignition)
                    r_e = s.get(f"{traccar}/api/reports/events?deviceId={internal_id}&from={traccar_from}&to={traccar_to}", timeout=30)
                    if r_e.status_code == 200:
                        for ev in r_e.json():
                            etype = ev.get('type', 'Event')
                            if etype == 'alarm': etype = f"Alarm: {ev.get('attributes', {}).get('alarm', 'unknown')}"
                            all_events.append({
                                'time': ev.get('eventTime'),
                                'type': etype,
                                'loc': 'N/A', # Events don't always have easy addresses in raw list
                                'details': ''
                            })
                    
                    all_events.sort(key=lambda x: x['time'] or '')
                    for row in all_events:
                        cw.writerow([row['time'], name, row['type'], row['loc'], row['details']])

    elif report_type == 'Summary':
        cw.writerow(['Vehicle', 'Max Speed', 'Avg Speed', 'Total Distance', 'Engine Hours', 'Fuel (L)', 'Fuel Cost (OMR)', 'Total Idle Stop', 'Ending OFF', 'Engine ON Stop'])
        # Use the logic from fetch_cached_summaries but we need it here
        data = fetch_cached_summaries(target_vehicles, filter_uid, traccar_from, traccar_to, traccar, s)
        for row in data:
            idle_sec = row.get('idle_duration', 0) / 1000
            idle_str = f"{int(idle_sec // 3600)}h {int((idle_sec % 3600) // 60)}m"
            
            off_sec = row.get('off_duration', 0) / 1000
            off_str = f"{int(off_sec // 3600)}h {int((off_sec % 3600) // 60)}m"
            
            cw.writerow([
                row.get('name'),
                f"{row.get('max_speed', 0)} km/h",
                f"{row.get('average_speed', 0)} km/h",
                f"{row.get('total_distance', 0)} km",
                f"{round(row.get('engine_hours', 0), 1)} h",
                f"{round(row.get('fuel_liters', 0), 1)} L",
                f"{round(row.get('fuel_cost', 0), 3)} OMR",
                idle_str,
                off_str,
                idle_str # Engine ON Stop
            ])
    
    elif report_type == 'Idle':
        cw.writerow(['Vehicle Name', 'Start Time', 'End Time', 'Duration (min)', 'Location'])
        # We'll need to fetch idle data here for export
        # For simplicity, I'll call a service method we'll define soon
        from services.report_service import get_idle_events
        s = get_traccar_session()
        traccar = full_traccar_host()
        
        try:
            min_idle = int(request.args.get('min_idle_time', 5))
        except:
            min_idle = 5

        for v in target_vehicles:
            events = get_idle_events(v, traccar_from, traccar_to, min_idle, traccar, s)
            for ev in events:
                cw.writerow([
                    ev['vehicle_name'],
                    ev['start_time'],
                    ev['end_time'],
                    ev['duration'],
                    ev['location']
                ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{report_type.lower()}_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output
