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

@reports_bp.route('/playback')
@role_required('user')
def playback_page():
    return render_template('playback.html')

@reports_bp.route('/analytics')
@role_required('user')
def analytics_page():
    return render_template('analytics.html')

@reports@api_bp.route('/api/reports/export')
@role_required('user')
def export_report():
    period = request.args.get('period', 'Today')
    report_type = request.args.get('report_type', 'Trips')
    filter_uid = request.args.get('unique_id')
    
    from services.report_service import get_period_dates
    from services.native_report_service import native_report_service
    start_dt, end_dt = get_period_dates(period, request.args.get('from'), request.args.get('to'))

    allowed_vehicles = get_filtered_vehicles()
    if filter_uid:
        allowed_vehicles = [v for v in allowed_vehicles if str(v.get('unique_id')) == str(filter_uid)]

    si = io.StringIO()
    cw = csv.writer(si)

    if report_type == 'Trips':
        cw.writerow(['IMEI', 'Start Time', 'End Time', 'Distance (km)', 'Avg Speed (km/h)', 'Max Speed (km/h)', 'Duration (sec)', 'Fuel (L)'])
        for v in allowed_vehicles:
            trips = native_report_service.get_trip_report(v['unique_id'], start_dt, end_dt)
            for t in trips:
                cw.writerow([
                    t['imei'], 
                    t['start_time'].strftime('%Y-%m-%d %H:%M:%S'), 
                    t['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    round(t['distance_km'], 2),
                    round(t['avg_speed'], 2),
                    round(t['max_speed'], 2),
                    t['duration_sec'],
                    round(t['fuel_consumed'], 2)
                ])
    
    elif report_type == 'Summary':
        cw.writerow(['Vehicle Name', 'IMEI', 'Total Distance (km)', 'Max Speed (km/h)', 'Avg Speed (km/h)', 'Idle Time (min)', 'Fuel (L)'])
        summaries = native_report_service.get_fleet_summary(allowed_vehicles, start_dt, end_dt)
        for s in summaries:
            cw.writerow([
                s['name'],
                s['unique_id'],
                s['total_distance'],
                s['max_speed'],
                s['average_speed'],
                round(s['idle_duration'] / 60000, 1),
                s['fuel_liters']
            ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{report_type.lower()}_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{report_type.lower()}_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output
