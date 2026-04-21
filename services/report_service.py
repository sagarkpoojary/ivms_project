from datetime import datetime, timedelta
import pytz
from services.time_service import get_oman_now, format_to_oman, SYSTEM_TZ, parse_traccar_to_oman_str
from flask import request, session, render_template, current_app
from models.database import load_server_config
from services.traccar_service import full_traccar_host, get_traccar_session, save_traccar_cookies
from auth.utils import get_filtered_vehicles
from extensions import cache
from config import Config

def get_period_dates(period, from_str=None, to_str=None):
    now = get_oman_now()
    start_dt = now
    end_dt = now
    
    if period == 'Yesterday':
        start_dt = now - timedelta(days=1)
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999)
    elif period == 'This Week':
        # Oman week often starts on Saturday? But Python weekday() is Monday=0.
        # Let's stick to Monday for now unless specifically asked for Sunday/Saturday start.
        start_dt = now - timedelta(days=now.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'This Month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'Custom' and from_str:
        try:
            # User input from HTML datetime-local is usually in local time (Oman)
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
    filter_group = request.args.get('groups')
    filter_company = request.args.get('company_filter')
    
    vehicles = all_vehicles
    if filter_company:
        vehicles = [v for v in all_vehicles if v.get('company_name') == filter_company]
    
    if forced_report_type:
        report_type = forced_report_type
    else:
        report_type = request.args.get('report_type', 'Trips')
    
    now = get_oman_now()
    start_dt, end_dt = get_period_dates(period, request.args.get('from'), request.args.get('to'))

    # For display in the HTML form
    from_str_display = start_dt.strftime('%Y-%m-%dT%H:%M')
    to_str_display = end_dt.strftime('%Y-%m-%dT%H:%M')
    
    # Traccar API expects UTC. Convert Oman time to UTC.
    traccar_from = start_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    traccar_to = end_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    report_data = []
    traccar = full_traccar_host()
    if not traccar:
         return render_template('pre_reg_report.html', report_data=[], from_date=from_str_display, to_date=to_str_display, error="Traccar host not configured", vehicles=vehicles)

    s = get_traccar_session()
    
    try:
        val = request.args.get('stop_threshold', '')
        stop_threshold_mins = int(val) if val else 5
    except (ValueError, TypeError):
        cfg = load_server_config()
        stop_threshold_mins = int(cfg.get('stop_threshold', 5))

    device_map = {} 
    traccar_admin_warning = False
    try:
        r_dev = s.get(f"{traccar}/api/devices", timeout=10)
        save_traccar_cookies(s)
        if r_dev.status_code == 200:
            for d in r_dev.json():
                device_map[str(d.get("uniqueId"))] = d.get("id")
            
            # Check if user is actually a Traccar admin
            r_sess = s.get(f"{traccar}/api/session", timeout=5)
            if r_sess.status_code == 200:
                is_traccar_admin = r_sess.json().get('administrator', False)
                if not is_traccar_admin and session.get('role') == 'super_admin':
                    traccar_admin_warning = True
        else:
            current_app.logger.error(f"Failed to fetch devices from Traccar: {r_dev.status_code}")
    except Exception as e:
        current_app.logger.error(f"Failed to fetch devices: {e}")
    
    if report_type != 'Combined' or not filter_uid:
        # Batch fetch/Cache summaries to avoid N+1 slow reads
        report_data = fetch_cached_summaries(vehicles, filter_uid, traccar_from, traccar_to, traccar, s)


    # Define columns based on report type
    if report_type == 'Trips':
        all_available_cols = ['startTime', 'startOdometer', 'startAddress', 'endTime', 'endOdometer', 'endAddress', 'distance', 'averageSpeed', 'maxSpeed', 'duration', 'spentFuel', 'driverName']
    elif report_type == 'Stops':
        all_available_cols = ['startTime', 'endTime', 'duration', 'startOdometer', 'address', 'engineHours', 'spentFuel']
    else:
        all_available_cols = []
    
    selected_columns = []
    
    has_any_col_param = any(request.args.get(f'col_{col}') for col in all_available_cols)
    
    if has_any_col_param:
        for col in all_available_cols:
            if request.args.get(f'col_{col}'):
                selected_columns.append(col)
    
    
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
        internal_id = device_map.get(str(filter_uid))
        current_app.logger.info(f"Report filter UID: {filter_uid}, found internal ID: {internal_id} among {len(device_map)} devices in Traccar")
        if internal_id and traccar:
            # 1. AUTHORITATIVE SUMMARY for cards (Distance, Duration, Speed)
            try:
                url_sum = f"{traccar}/api/reports/summary?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                r_sum = s.get(url_sum, headers={'Accept': 'application/json'}, timeout=10)
                if r_sum.status_code == 200 and r_sum.json():
                    s_auth = r_sum.json()[0]
                    summary_distance = round(s_auth.get('distance', 0) / 1000, 2)
                    summary_duration = s_auth.get('duration', 0)
                    summary_avg_speed = round(s_auth.get('averageSpeed', 0) * 1.852, 2)
            except: pass

            # 2. AUTHORITATIVE STOPS (needed for Idle Time card and Stops/Combined reports)
            all_raw_stops = []
            try:
                url_stops = f"{traccar}/api/reports/stops?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                r_stops_auth = s.get(url_stops, headers={'Accept': 'application/json'}, timeout=15)
                if r_stops_auth.status_code == 200:
                    all_raw_stops = r_stops_auth.json()
                    for st in all_raw_stops:
                        if st.get('engine') is True:
                            summary_idle_time += st.get('duration', 0)
            except: pass

            if report_type == 'Trips':

                try:
                    url = f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_trips = s.get(url, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_trips.status_code == 200:
                        processed_trips = r_trips.json()
                        processed_trips.sort(key=lambda x: x.get('startTime', ''))
                        
                        for t in processed_trips:
                            dist_km = round((t.get('distance') or 0) / 1000, 2)
                            avg_spd_kmh = round((t.get('averageSpeed') or 0) * 1.852, 2)
                            max_spd_kmh = round((t.get('maxSpeed') or 0) * 1.852, 2)
                            
                            # Estimate fuel if sensor not present
                            fuel_liters = round(dist_km / Config.MILEAGE_KM_PER_LITER, 2)
                            fuel_cost = round(fuel_liters * Config.FUEL_PRICE_OMR, 3)

                            driver_name = '-' 
                            for v in vehicles:
                                if str(v.get('unique_id')) == str(filter_uid):
                                    driver_name = v.get('driver_name', '-')
                                    break

                            trip_data.append({
                                'deviceId': t.get('deviceId'),
                                'deviceName': t.get('deviceName'),
                                'startTime': parse_traccar_to_oman_str(t.get('startTime')),
                                'endTime': parse_traccar_to_oman_str(t.get('endTime')),
                                'rawStartTime': t.get('startTime'),
                                'rawEndTime': t.get('endTime'),
                                'distance': f"{dist_km} km",
                                'averageSpeed': f"{avg_spd_kmh} km/h",
                                'maxSpeed': f"{max_spd_kmh} km/h",
                                'startOdometer': f"{round((t.get('startOdometer') or 0) / 1000, 2)} km",
                                'endOdometer': f"{round((t.get('endOdometer') or 0) / 1000, 2)} km",
                                'startAddress': t.get('startAddress', 'N/A'),
                                'endAddress': t.get('endAddress', 'N/A'),
                                'spentFuel': f"{fuel_liters} L ({fuel_cost} OMR)",
                                'duration': t.get('duration'),
                                'driverName': driver_name,
                                'startLat': t.get('startLat'),
                                'startLon': t.get('startLon'),
                                'endLat': t.get('endLat'),
                                'endLon': t.get('endLon')
                            })
                except Exception as e:
                    current_app.logger.error(f"Failed to fetch trips for {filter_uid}: {e}")
            
            elif report_type == 'Stops':
                try:
                    for s_item in all_raw_stops:
                        # Remove manual Stop filtering. Respect Traccar backend report.
                        
                        engine_status = "OFF"
                        if s_item.get('engine') is True: 
                            engine_status = "ON"

                        # Duration fallback for engine hours if Traccar data is missing
                        dur_ms = s_item.get('duration') or 0
                        dur_h = round(dur_ms / 3600000, 2)
                        
                        eng_h = round((s_item.get('engineHours') or 0) / 3600000, 2)
                        if eng_h == 0 and engine_status == "ON":
                            eng_h = dur_h
                        
                        # Fuel fallback for idling if Traccar data is missing
                        fuel_l = round(s_item.get('spentFuel') or 0, 2)
                        if fuel_l == 0 and engine_status == "ON":
                            fuel_l = round(dur_h * Config.IDLE_FUEL_LPH, 2)

                        odo_km = round((s_item.get('startOdometer') or 0) / 1000, 2)
                        
                        row = {
                            'deviceId': s_item.get('deviceId'),
                            'deviceName': s_item.get('deviceName'),
                            'startTime': parse_traccar_to_oman_str(s_item.get('startTime')),
                            'endTime': parse_traccar_to_oman_str(s_item.get('endTime')),
                            'duration': dur_ms,
                            'address': s_item.get('address', 'N/A'),
                            'odometer': odo_km,
                            'engine': engine_status,
                            'spentFuel': f"{fuel_l} L",
                            'engineHours': f"{eng_h} h",
                            'latitude': s_item.get('latitude'),
                            'longitude': s_item.get('longitude')
                        }
                        
                        if engine_status == 'ON':
                            stop_data_on.append(row)
                        else:
                            stop_data_off.append(row)
                except Exception as e:
                    current_app.logger.error(f"Failed to process stops for {filter_uid}: {e}")

            elif report_type == 'Combined':
                try:
                    dev_name = 'Unknown'
                    matches = [v['name'] for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]
                    if matches: dev_name = matches[0]

                    url_route = f"{traccar}/api/reports/route?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_route = s.get(url_route, headers={'Accept': 'application/json'}, timeout=20)
                    save_traccar_cookies(s)
                    if r_route.status_code == 200:
                        full_route = r_route.json()
                        # Optimization: Create a map of positions from FULL route_data for quick lookup
                        route_pos_map = {p.get('id'): p for p in full_route if p.get('id')}
                        
                        # Virtual Overspeed markers are no longer needed as the route line itself is colored red for speed > 80.
                        # This also prevents massive response sizes for long trips.

                        # Downsample for frontend map
                        if len(full_route) > 800:
                            step = len(full_route) // 400
                            route_data = full_route[::step]
                            # Always include absolute last point
                            if full_route[-1] not in route_data:
                                route_data.append(full_route[-1])
                        else:
                            route_data = full_route
                    else:
                        route_pos_map = {}
                        route_data = []

                    url_trips = f"{traccar}/api/reports/trips?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_trips = s.get(url_trips, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    # Summary and Stops already fetched above
                    for stop in all_raw_stops:
                        # Inject stop into combined_data as a pseudo-event for UI timeline
                        # Respecting Traccar's reported boundaries exactly
                        combined_data.append({
                            'deviceName': dev_name,
                            'fixTime': parse_traccar_to_oman_str(stop.get('startTime')),
                            'type': 'deviceStopped', # Matches JS filter for 'Stops'
                            'attributes': {
                                'duration_ms': stop.get('duration'),
                                'address': stop.get('address'),
                                'engine': stop.get('engine'),
                                'endTime': parse_traccar_to_oman_str(stop.get('endTime'))
                            },
                            'position': {
                                'latitude': stop.get('latitude'),
                                'longitude': stop.get('longitude'),
                                'address': stop.get('address')
                            }
                        })


                    url_events = f"{traccar}/api/reports/events?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
                    r_events = s.get(url_events, headers={'Accept': 'application/json'}, timeout=15)
                    save_traccar_cookies(s)
                    if r_events.status_code == 200:
                        raw_events = r_events.json()
                        dev_name = 'Unknown'
                        matches = [v['name'] for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]
                        if matches: dev_name = matches[0]
                        elif report_data: dev_name = report_data[0]['name']

                        # Fetch positions for each event
                        for ev in raw_events:
                            event_time = ev.get('eventTime')
                            position_id = ev.get('positionId')
                            position = None
                            
                            # 1. Try to find in route_data map first (fastest)
                            if position_id and position_id in route_pos_map:
                                position = route_pos_map[position_id]
                            
                            # 2. If not found, try time-based match in route_data
                            if not position and route_data and event_time:
                                try:
                                    ev_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00').split('.')[0])
                                    min_diff = float('inf')
                                    nearest_pos = None
                                    for pos in route_data:
                                        pos_time = pos.get('fixTime')
                                        if pos_time:
                                            pos_dt = datetime.fromisoformat(pos_time.replace('Z', '+00:00').split('.')[0])
                                            diff = abs((ev_dt - pos_dt).total_seconds())
                                            if diff < min_diff and diff < 5: # Tight match (5s)
                                                min_diff = diff
                                                nearest_pos = pos
                                    if nearest_pos: position = nearest_pos
                                except Exception: pass
                            
                            # 3. Last resort: Individual API call (only if we have few events)
                            if not position and position_id:
                                # Avoid many calls for long reports
                                if len(raw_events) < 30: 
                                    try:
                                        pos_url = f"{traccar}/api/positions?id={position_id}"
                                        r_pos = s.get(pos_url, headers={'Accept': 'application/json'}, timeout=5)
                                        if r_pos.status_code == 200:
                                            res_pos = r_pos.json()
                                            if res_pos:
                                                position = res_pos[0]
                                    except Exception as pos_err:
                                        current_app.logger.warning(f"Failed to fetch position {position_id}: {pos_err}")
                            
                            combined_data.append({
                                'deviceName': dev_name,
                                'fixTime': parse_traccar_to_oman_str(ev.get('eventTime')),
                                'type': ev.get('type'),
                                'attributes': ev.get('attributes', {}),
                                'position': position
                            })
                        combined_data.sort(key=lambda x: x['fixTime'] or '')
                except Exception as e:
                    current_app.logger.error(f"Failed to fetch combined data for {filter_uid}: {e}")

    elif report_type == 'Stops':
        # Handle fleet-wide Stops report when no specific vehicle is selected
        target_iids = []
        for v in vehicles:
            uid = str(v.get("unique_id"))
            iid = device_map.get(uid)
            if iid: target_iids.append(iid)
        
        if target_iids and traccar:
            try:
                params = [('from', traccar_from), ('to', traccar_to)]
                for iid in target_iids:
                    params.append(('deviceId', iid))
                
                url = f"{traccar}/api/reports/stops"
                r_stops = s.get(url, params=params, headers={'Accept': 'application/json'}, timeout=40)
                save_traccar_cookies(s)
                
                if r_stops.status_code == 200:
                    raw_stops = r_stops.json()
                    raw_stops.sort(key=lambda x: x.get('startTime', ''))
                    
                    for s_item in raw_stops:
                        # dur_ms = s_item.get('duration') or 0
                        # Remove manual Stop filtering for fleet view. Respect Traccar backend.
                        
                        engine_status = "OFF"
                        if s_item.get('engine') is True: engine_status = "ON"
                        
                        dist_meters = s_item.get('totalDistance') or 0
                        odo_km = round(dist_meters / 1000, 2)
                        
                        row = {
                            'deviceId': s_item.get('deviceId'),
                            'deviceName': s_item.get('deviceName'),
                            'startTime': parse_traccar_to_oman_str(s_item.get('startTime')),
                            'endTime': parse_traccar_to_oman_str(s_item.get('endTime')),
                            'duration': s_item.get('duration'),
                            'address': s_item.get('address', 'N/A'),
                            'odometer': odo_km,
                            'engine': engine_status,
                            'spentFuel': f"{round((s_item.get('spentFuel') or 0), 2)} L",
                            'engineHours': f"{round((s_item.get('engineHours') or 0) / 3600000, 2)} h",
                            'latitude': s_item.get('latitude'),
                            'longitude': s_item.get('longitude')
                        }
                        
                        if engine_status == 'ON':
                            stop_data_on.append(row)
                        else:
                            stop_data_off.append(row)
            except Exception as e:
                current_app.logger.error(f"Failed to fetch fleet-wide stops: {e}")

    elif report_type == 'Idle':
        try:
            val = request.args.get('min_idle_time', '')
            min_idle_time = int(val) if val else 5
        except (ValueError, TypeError):
            min_idle_time = 5
            
        idle_data = [] # Detailed events list for template
        fleet_idle_summary = [] # Grouped by vehicle for the overview
        
        target_vehicles_for_idle = vehicles
        if filter_uid:
            target_vehicles_for_idle = [v for v in vehicles if str(v.get('unique_id')) == str(filter_uid)]
            
        for v in target_vehicles_for_idle:
            iid = device_map.get(str(v.get('unique_id')))
            if iid:
                result = get_idle_events(v, traccar_from, traccar_to, min_idle_time, traccar, s, internal_id=iid)
                events = result.get('events', [])
                idle_data.extend(events)
                fleet_idle_summary.append({
                    'vehicle_id': v.get('unique_id'),
                    'name': v.get('name'),
                    'total_idle_time': result.get('summary', {}).get('total_idle_time', 0),
                    'total_idle_events': result.get('summary', {}).get('total_idle_events', 0)
                })
        
        # Sort events by duration DESC by default
        idle_data.sort(key=lambda x: x['duration'], reverse=True)
        # Sort summary by total idle time DESC
        fleet_idle_summary.sort(key=lambda x: x['total_idle_time'], reverse=True)

    groups = []
    try:
        r_grp = s.get(f"{traccar}/api/groups", timeout=10)
        save_traccar_cookies(s)
        if r_grp.status_code == 200:
            groups = r_grp.json()
    except Exception as e:
        current_app.logger.error(f"Failed to fetch groups: {e}")

    internal_id = None
    if filter_uid:
        internal_id = device_map.get(str(filter_uid))

    # Calculate Summary Stats for Cards
    cfg = load_server_config()
    speed_limit = int(cfg.get('speed_limit', 100))
    
    low_usage_count = 0
    no_movement_count = 0
    overspeed_count = 0
    total_vehicles_count = len(report_data)

    for row in report_data:
        if row.get('status') == 'No Movement':
            no_movement_count += 1
        elif row.get('status') == 'Low Usage':
            low_usage_count += 1
        
        # Check max speed for overspeed regardless of primary status priority
        if row.get('max_speed', 0) > speed_limit:
            overspeed_count += 1

    return render_template('pre_reg_report.html', 
                          report_data=report_data, 
                          low_usage_count=low_usage_count,
                          no_movement_count=no_movement_count,
                          overspeed_count=overspeed_count,
                          total_vehicles_count=total_vehicles_count,
                          speed_limit=speed_limit,
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
                          groups=groups,
                          selected_period=period, 
                          selected_uid=filter_uid,
                          selected_group=filter_group,
                          selected_report_type=report_type,
                          selected_threshold=str(stop_threshold_mins),
                          selected_min_idle=str(request.args.get('min_idle_time', 5)),
                          idle_data=idle_data if report_type == 'Idle' else [],
                          idle_summary=fleet_idle_summary if report_type == 'Idle' else [],
                          selected_columns=selected_columns,
                          internal_id=internal_id,
                          traccar_admin_warning=traccar_admin_warning,
                          role=session.get('role'))

def fetch_cached_summaries(vehicles, filter_uid, traccar_from, traccar_to, traccar, s):
    # Cache key based on user, vehicles (UIDs) and time range
    email = session.get('email', 'anon')
    v_uids = "-".join([str(v.get('unique_id')) for v in vehicles[:20]]) # Limit length
    cache_key = f"summaries_v3_{email}_{v_uids}_{filter_uid}_{traccar_from}_{traccar_to}"
    
    cached = cache.get(cache_key)
    if cached is not None: return cached
    
    # We need a device map (internal IDs)
    device_map = {}
    try:
        r_dev = s.get(f"{traccar}/api/devices", timeout=10)
        if r_dev.status_code == 200:
            for d in r_dev.json():
                device_map[str(d.get("uniqueId"))] = d.get("id")
    except: pass

    # Collect target internal IDs for bulk fetch
    target_iids = []
    vehicle_lookup = {}
    for v in vehicles:
        uid = str(v.get("unique_id"))
        if filter_uid and uid != str(filter_uid):
            continue
        iid = device_map.get(uid)
        if iid:
            target_iids.append(iid)
            vehicle_lookup[iid] = v

    summary_data_map = {}
    stop_data_map = {}
    
    if target_iids:
        try:
            # 1. Bulk Summary fetch
            params = [('from', traccar_from), ('to', traccar_to)]
            # Optimization: If too many, maybe don't bulk all, but usually is fine for ~50
            for iid in target_iids:
                params.append(('deviceId', iid))
            
            r_sum = s.get(f"{traccar}/api/reports/summary", params=params, headers={'Accept': 'application/json'}, timeout=20)
            if r_sum.status_code == 200:
                for item in r_sum.json():
                    summary_data_map[item.get('deviceId')] = item
            
            # 2. Bulk Stops fetch to calculate idle/off times
            r_stops = s.get(f"{traccar}/api/reports/stops", params=params, headers={'Accept': 'application/json'}, timeout=25)
            if r_stops.status_code == 200:
                for st in r_stops.json():
                    d_id = st.get('deviceId')
                    if d_id not in stop_data_map:
                        stop_data_map[d_id] = []
                    stop_data_map[d_id].append(st)
                    
        except Exception as e:
            current_app.logger.error(f"Bulk report fetch error: {e}")

    # Calculate total duration of period for 'off_duration' fallback
    try:
        dt_to = datetime.fromisoformat(traccar_to.replace('Z', '+00:00'))
        dt_from = datetime.fromisoformat(traccar_from.replace('Z', '+00:00'))
        total_period_ms = int((dt_to - dt_from).total_seconds() * 1000)
    except:
        total_period_ms = 0

    cfg = load_server_config()
    speed_limit = int(cfg.get('speed_limit', 100))

    report_data = []
    for v in vehicles:
        unique_id = str(v.get("unique_id"))
        if filter_uid and unique_id != str(filter_uid):
            continue
        
        internal_id = device_map.get(unique_id)
        row = {
            "name": v.get("name"), 
            "unique_id": unique_id, 
            "company_name": v.get("company_name"),
            "max_speed": 0, 
            "average_speed": 0,
            "total_distance": 0,
            "idle_duration": 0,
            "off_duration": 0,
            "internal_id": internal_id
        }
        
        row["engine_hours"] = 0
        engine_on_ms = 0
        if internal_id and internal_id in summary_data_map:
            item = summary_data_map[internal_id]
            try:
                row["max_speed"] = round(float(item.get("maxSpeed", 0)) * 1.852, 2)
                row["average_speed"] = round(float(item.get("averageSpeed", 0)) * 1.852, 2)
                row["total_distance"] = round(float(item.get("distance", 0)) / 1000, 2)
                engine_on_ms = float(item.get("engineHours", 0))
                row["engine_hours"] = round(engine_on_ms / 3600000, 1)
            except: pass
        
        # 2. Get Idling from Stops (already bulk fetched above)
        if internal_id and internal_id in stop_data_map:
            stops = stop_data_map[internal_id]
            idle_ms = 0
            for st in stops:
                if st.get('engine') is True:
                    idle_ms += st.get('duration', 0)
            row["idle_duration"] = idle_ms
            
            # Refine engine hours if 0 (estimate from idling stops + trips) 
            # Note: For full accuracy we'd need Trips too, but Idling is the main missing piece for many trackers.
            if row["engine_hours"] == 0 and idle_ms > 0:
                row["engine_hours"] = round(idle_ms / 3600000, 1)

        # 3. Fuel Calcs (Combine trip distance fuel + idling fuel)
        dist_km = row["total_distance"]
        idle_h = row["idle_duration"] / 3600000
        
        # Initial estimate based on distance
        fuel_liters = dist_km / Config.MILEAGE_KM_PER_LITER
        # Add idling consumption
        fuel_liters += (idle_h * Config.IDLE_FUEL_LPH)
        
        row["fuel_liters"] = round(fuel_liters, 2)
        row["fuel_cost"] = round(fuel_liters * Config.FUEL_PRICE_OMR, 3)

        # off_duration = period - engineON
        row["off_duration"] = max(0, total_period_ms - engine_on_ms)

        # Status / Insight Logic
        status = "Normal"
        insight = "No issues detected"
        priority = 0
        
        if row["total_distance"] == 0 and row["off_duration"] > 21600000: # 6 hours
            status = "No Movement"
            insight = "Vehicle inactive for >6h"
            priority = 3
        elif row["total_distance"] < 20:
            status = "Low Usage"
            insight = "Distance < 20 km"
            priority = 2
        
        if row["max_speed"] > speed_limit:
            # Possible move status to Overspeed if priority is lower
            if priority < 1:
                status = "Possible Overspeed"
                insight = f"Speed exceeded {speed_limit} km/h"
                priority = 1
            else:
                # Add to insight if already has another status
                insight += f" (also Overspeed)"

        row["status"] = status
        row["insight"] = insight
        row["priority"] = priority
            
        report_data.append(row)
    
    # Default Table Sorting: Prioritize No Movement > Low Usage > Overspeed
    report_data.sort(key=lambda x: x.get('priority', 0), reverse=True)

    # Cache for 2 minutes
    cache.set(cache_key, report_data, timeout=120)
    return report_data

def get_idle_events(v, traccar_from, traccar_to, min_idle, traccar, s, internal_id=None):
    uid = v.get('unique_id')
    name = v.get('name')
    
    if not internal_id:
        try:
            r_dev = s.get(f"{traccar}/api/devices", params={'uniqueId': uid}, timeout=10)
            if r_dev.status_code == 200:
                devs = r_dev.json()
                if devs: internal_id = devs[0]['id']
        except: 
            return {'summary': {'total_idle_time': 0, 'total_idle_events': 0}, 'events': []}

    if not internal_id: 
        return {'summary': {'total_idle_time': 0, 'total_idle_events': 0}, 'events': []}

    try:
        # Enforce date range limit (max 31 days) to prevent memory issues
        t_from = datetime.fromisoformat(traccar_from.replace('Z', '+00:00'))
        t_to = datetime.fromisoformat(traccar_to.replace('Z', '+00:00'))
        if (t_to - t_from).days > 31:
             t_to = t_from + timedelta(days=31)
             traccar_to = t_to.strftime('%Y-%m-%dT%H:%M:%SZ')

        url = f"{traccar}/api/reports/route?deviceId={internal_id}&from={traccar_from}&to={traccar_to}"
        r = s.get(url, headers={'Accept': 'application/json'}, timeout=45)
        if r.status_code != 200: 
            return {'summary': {'total_idle_time': 0, 'total_idle_events': 0}, 'events': []}
        
        positions = r.json()
        if not positions: 
            return {'summary': {'total_idle_time': 0, 'total_idle_events': 0}, 'events': []}
        
        # Ensure sorting and handle potential out-of-order data
        positions.sort(key=lambda x: x.get('fixTime', ''))
        
        idle_events = []
        current_idle_start = None
        last_processed_pos = None
        
        total_idle_time = 0
        
        for pos in positions:
            # 1. Engine Detection Logic (Harden check)
            attrs = pos.get('attributes', {})
            ignition = attrs.get('ignition')
            motion = attrs.get('motion')
            speed_kmh = (pos.get('speed', 0) or 0) * 1.852
            
            # Use ignition if available, else motion/speed fallback
            engine_on = False
            if ignition is not None:
                engine_on = ignition
            elif motion is not None:
                # If moving, engine must be on; if stopped and motion is true, likely idling
                engine_on = motion or speed_kmh > 0
            else:
                engine_on = speed_kmh > 0
            
            is_idle_now = engine_on and speed_kmh < Config.IDLE_SPEED_THRESHOLD
            
            # 2. Data Gap Detection
            gap_detected = False
            if last_processed_pos:
                try:
                    t_last = datetime.fromisoformat(last_processed_pos['fixTime'].replace('Z', '+00:00').split('.')[0])
                    t_curr = datetime.fromisoformat(pos['fixTime'].replace('Z', '+00:00').split('.')[0])
                    gap_sec = (t_curr - t_last).total_seconds()
                    if gap_sec > (Config.MAX_DATA_GAP_MINUTES * 60):
                        gap_detected = True
                except: pass
            
            # 3. Session Management
            if current_idle_start:
                # Idle session ends if: not idling anymore, OR engine turned off, OR gap detected
                if not is_idle_now or gap_detected:
                    try:
                        t_start = datetime.fromisoformat(current_idle_start['fixTime'].replace('Z', '+00:00').split('.')[0])
                        # End time is the last position that was STILL idle
                        t_end = datetime.fromisoformat(last_processed_pos['fixTime'].replace('Z', '+00:00').split('.')[0])
                        dur_min = (t_end - t_start).total_seconds() / 60
                        
                        if dur_min >= min_idle:
                            idle_events.append({
                                'vehicle_id': uid,
                                'vehicle_name': name,
                                'start_time': parse_traccar_to_oman_str(current_idle_start['fixTime']),
                                'end_time': parse_traccar_to_oman_str(last_processed_pos['fixTime']),
                                'duration': round(dur_min, 1),
                                'location': last_processed_pos.get('address') or f"{last_processed_pos.get('latitude')}, {last_processed_pos.get('longitude')}",
                                'latitude': last_processed_pos.get('latitude'),
                                'longitude': last_processed_pos.get('longitude')
                            })
                            total_idle_time += dur_min
                    except: pass
                    current_idle_start = pos if is_idle_now else None
            elif is_idle_now:
                current_idle_start = pos
                
            last_processed_pos = pos
        
        # 4. Handle trailing idle spell
        if current_idle_start and last_processed_pos:
            try:
                t_start = datetime.fromisoformat(current_idle_start['fixTime'].replace('Z', '+00:00').split('.')[0])
                t_end = datetime.fromisoformat(last_processed_pos['fixTime'].replace('Z', '+00:00').split('.')[0])
                dur_min = (t_end - t_start).total_seconds() / 60
                if dur_min >= min_idle:
                    idle_events.append({
                        'vehicle_id': uid,
                        'vehicle_name': name,
                        'start_time': parse_traccar_to_oman_str(current_idle_start['fixTime']),
                        'end_time': parse_traccar_to_oman_str(last_processed_pos['fixTime']),
                        'duration': round(dur_min, 1),
                        'location': last_processed_pos.get('address') or f"{last_processed_pos.get('latitude')}, {last_processed_pos.get('longitude')}",
                        'latitude': last_processed_pos.get('latitude'),
                        'longitude': last_processed_pos.get('longitude')
                    })
                    total_idle_time += dur_min
            except: pass
        
        return {
            'summary': {
                'total_idle_time': round(total_idle_time, 1),
                'total_idle_events': len(idle_events)
            },
            'events': idle_events
        }
    except Exception as e:
        current_app.logger.error(f"Enhanced Idle report error for {uid}: {e}")
        return {'summary': {'total_idle_time': 0, 'total_idle_events': 0}, 'events': []}
