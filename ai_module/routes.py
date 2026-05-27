import os
from flask import request, jsonify, render_template, redirect, url_for, session, current_app, send_file, after_this_request
from werkzeug.utils import secure_filename
from auth.utils import role_required
from ai_module import ai_blueprint
from ai_module.services.ai_service import ai_service
from ai_module.services.rag_service import rag_service

import uuid
import psycopg2
import psycopg2.extras
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
MAX_FILE_SIZE = 5 * 1024 * 1024 # 5 MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@ai_blueprint.route('/chat', methods=['POST'])
@role_required('user')
def chat():
    data = request.get_json() or {}
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({"error": "Empty message"}), 400
        
    # Detect report generation intent
    from ai_module.services.ai_service import is_report_request
    if is_report_request(user_message):
        msg_lower = user_message.lower()
        report_type = "trip_summary"
        if "driver" in msg_lower or "activity" in msg_lower or "session" in msg_lower:
            report_type = "driver_activity"
        elif "utilization" in msg_lower or "utility" in msg_lower or "idle" in msg_lower or "efficiency" in msg_lower:
            report_type = "fleet_utilization"
        elif "alert" in msg_lower or "event" in msg_lower or "fault" in msg_lower:
            report_type = "alerts"
            
        date_range = "today"
        if "week" in msg_lower or "7 days" in msg_lower or "last week" in msg_lower:
            date_range = "week"
        elif "month" in msg_lower or "30 days" in msg_lower or "last month" in msg_lower:
            date_range = "month"
            
        try:
            filename, file_uuid = generate_pdf_report_file(report_type, date_range, {})
            pdf_url = f"/ai/report/download/{file_uuid}"
            confirm_msg = f"I have successfully generated your detailed **{report_type.replace('_', ' ').title()}** report filtered by the last **{date_range}**."
            
            ai_service.add_log(user_message, confirm_msg, "PDF Report Gen", "Success", 0)
            return jsonify({
                "response": confirm_msg,
                "type": "PDF Report Gen",
                "pdf_url": pdf_url,
                "filename": filename
            })
        except Exception as e:
            current_app.logger.error(f"Failed to generate report via chat: {e}")
            ai_service.add_log(user_message, f"Report failed: {e}", "PDF Report Gen", "Error", 0, error=str(e))
            return jsonify({"error": f"Failed to generate report: {e}"}), 500

    config = ai_service.load_config()
    
    # 1. Check if RAG is enabled and see if there are matching chunks
    context = ""
    if config.get("rag_enabled", True):
        matched_chunks = rag_service.retrieve_context(user_message, top_k=3)
        if matched_chunks:
            context = "\n\nRetrieved Knowledge Base Context:\n"
            for c in matched_chunks:
                context += f"--- (Source: {c['original_name']}) ---\n{c['text']}\n"

    # 2. Check if DB querying is enabled and if the query is DB-related
    # We will let the LLM decide if it needs to run a DB query or not by looking at keywords,
    # or by attempting SQL translation first for fleet-related queries.
    db_keywords = ["fleet", "vehicle", "driver", "trip", "active", "speed", "overspeed", "idle", "rfid", "telemetry"]
    is_db_query = config.get("allow_db", True) and any(kw in user_message.lower() for kw in db_keywords)
    
    try:
        if is_db_query:
            # Execute database search workflow
            success, response_text, tokens = ai_service.ask_database_question(user_message, config)
            r_type = "DB Query"
        else:
            # Standard conversational flow or RAG-based context
            prompt = user_message
            if context:
                prompt = (
                    f"Context documents provided below. Use this information if relevant to answer the user's question.\n"
                    f"{context}\n"
                    f"User question: {user_message}"
                )
            
            messages = [{"role": "user", "content": prompt}]
            success, response_text, tokens = ai_service.ask_ai(messages, config)
            r_type = "RAG / Conversational" if context else "Conversational"
            
        if success:
            ai_service.add_log(user_message, response_text, r_type, "Success", tokens)
            return jsonify({"response": response_text, "type": r_type})
        else:
            ai_service.add_log(user_message, "Failed request", r_type, "Error", 0, error=response_text)
            return jsonify({"error": response_text}), 500
            
    except Exception as e:
        ai_service.add_log(user_message, "System error", "Error", "Error", 0, error=str(e))
        return jsonify({"error": f"An unexpected system error occurred: {e}"}), 500


@ai_blueprint.route('/settings', methods=['GET'])
@role_required('admin')
def settings():
    config = ai_service.load_config()
    logs_data = ai_service.get_logs()
    
    # Securely mask the API key in the UI
    display_config = dict(config)
    if display_config.get("api_key"):
        key = display_config["api_key"]
        display_config["api_key"] = key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else "****"
        
    return render_template(
        'ai_settings.html', 
        config=display_config, 
        logs=logs_data.get("logs", []), 
        token_count=logs_data.get("token_count", 0),
        files=rag_service.metadata
    )


@ai_blueprint.route('/config/save', methods=['POST'])
@role_required('admin')
def save_config():
    # Load existing configuration to preserve unchanged fields (like unmasked API key)
    existing = ai_service.load_config()
    
    api_key = request.form.get('api_key', '').strip()
    # Check if the API key was replaced or remains masked
    if not api_key or '*' in api_key:
        api_key = existing.get('api_key', '')
        
    new_config = {
        "api_key": api_key,
        "model": request.form.get('model', 'gpt-4o'),
        "endpoint": request.form.get('endpoint', 'https://api.openai.com/v1').strip(),
        "system_prompt": request.form.get('system_prompt', '').strip(),
        "allow_db": request.form.get('allow_db') == 'on',
        "rag_enabled": request.form.get('rag_enabled') == 'on',
        "language": request.form.get('language', 'en')
    }
    
    if ai_service.save_config(new_config):
        return jsonify({"status": "success", "message": "AI settings successfully updated."})
    else:
        return jsonify({"status": "error", "message": "Failed to update configurations."}), 500


@ai_blueprint.route('/config/test', methods=['POST'])
@role_required('admin')
def test_config():
    existing = ai_service.load_config()
    
    api_key = request.form.get('api_key', '').strip()
    if not api_key or '*' in api_key:
        api_key = existing.get('api_key', '')
        
    test_cfg = {
        "api_key": api_key,
        "model": request.form.get('model', 'gpt-4o'),
        "endpoint": request.form.get('endpoint', 'https://api.openai.com/v1').strip()
    }
    
    success, message = ai_service.test_connection(test_cfg)
    if success:
        return jsonify({"status": "success", "message": message})
    else:
        return jsonify({"status": "error", "message": message})


@ai_blueprint.route('/config/fetch-models', methods=['POST'])
@role_required('admin')
def fetch_models():
    import requests
    
    # Support both JSON and Form-urlencoded request bodies
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form or {}
        
    endpoint = data.get('endpoint', '').strip()
    api_key = data.get('api_key', '').strip()
    
    existing = ai_service.load_config()
    
    # Fallback to existing saved credentials if input key is empty or masked
    if not api_key or '*' in api_key:
        api_key = existing.get('api_key', '')
        
    if not endpoint:
        endpoint = existing.get('endpoint', 'https://api.openai.com/v1')
        
    endpoint = endpoint.rstrip('/')
    
    # Provider-specific branching
    if "anthropic.com" in endpoint.lower():
        # Curated hardcoded Anthropic fallback list since Anthropic has no /models endpoint
        models = [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4",
            "claude-sonnet-4"
        ]
        return jsonify({"models": models})
        
    elif "localhost" in endpoint.lower() or "127.0.0.1" in endpoint.lower():
        # Ollama local tags
        url = f"{endpoint}/api/tags"
        try:
            r = requests.get(url, timeout=5.0)
            if r.status_code in (401, 403):
                return jsonify({"error": "invalid_key"}), 401
            r.raise_for_status()
            res_json = r.json()
            models_list = res_json.get("models", [])
            models = [m.get("name") for m in models_list if m.get("name")]
            return jsonify({"models": models})
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in (401, 403):
                    return jsonify({"error": "invalid_key"}), 401
            return jsonify({"error": "connection_failed"}), 400
        except Exception:
            return jsonify({"error": "connection_failed"}), 400
            
    else:
        # Standard OpenAI / Groq / Compatible endpoint
        url = f"{endpoint}/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        try:
            r = requests.get(url, headers=headers, timeout=5.0)
            if r.status_code in (401, 403):
                return jsonify({"error": "invalid_key"}), 401
            r.raise_for_status()
            res_json = r.json()
            models_list = res_json.get("data", [])
            models = [m.get("id") for m in models_list if m.get("id")]
            return jsonify({"models": models})
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in (401, 403):
                    return jsonify({"error": "invalid_key"}), 401
            return jsonify({"error": "connection_failed"}), 400
        except Exception:
            return jsonify({"error": "connection_failed"}), 400


@ai_blueprint.route('/rag/upload', methods=['POST'])
@role_required('admin')
def rag_upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
        
    if not allowed_file(file.filename):
        return jsonify({"error": "Allowed extensions are: .pdf, .docx, .txt"}), 400
        
    # Strictly validate file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0) # reset pointer
    
    if size > MAX_FILE_SIZE:
        return jsonify({"error": f"File exceeds maximum allowed size of 5MB"}), 400
        
    # Generate unique filename safely
    from datetime import datetime
    import secrets
    original_name = file.filename
    clean_name = secure_filename(original_name)
    random_prefix = secrets.token_hex(6)
    unique_filename = f"{random_prefix}_{clean_name}"
    
    dest_path = os.path.join(rag_service.kb_dir, unique_filename)
    
    try:
        file.save(dest_path)
        # Parse and index document
        rag_service.add_document(unique_filename, dest_path, original_name)
        return jsonify({"success": True, "filename": unique_filename})
    except Exception as e:
        return jsonify({"error": f"Failed to save and index document: {e}"}), 500


@ai_blueprint.route('/rag/files/<filename>', methods=['DELETE'])
@role_required('admin')
def rag_delete(filename):
    # Sanitize name to block path traversal
    filename = secure_filename(filename)
    if rag_service.delete_document(filename):
        return jsonify({"success": True, "message": "Document successfully deleted."})
    else:
        return jsonify({"error": "Document not found"}), 404


@ai_blueprint.route('/rag/reindex', methods=['POST'])
@role_required('admin')
def rag_reindex():
    try:
        rag_service.reindex_all()
        return jsonify({"success": True, "message": "Knowledge base successfully re-indexed."})
    except Exception as e:
        return jsonify({"error": f"Re-indexing failed: {e}"}), 500


# PDF Report Generation Logic and Endpoints

def generate_pdf_report_file(report_type, date_range, filters):
    # 1. Map date range to interval
    interval_map = {
        "today": "0 days",
        "week": "7 days",
        "month": "30 days"
    }
    interval_str = interval_map.get(date_range, "0 days")
    
    from models.database import get_conn
    conn = None
    cur = None
    rows = []
    headers = []
    title = ""
    
    try:
        conn = get_conn()
        conn.set_session(readonly=True, autocommit=False)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        if report_type == "trip_summary":
            title = "IVMS Fleet Trip Summary Report"
            headers = ["IMEI", "Vehicle Name", "Start Time", "End Time", "Distance (km)", "Avg Speed (km/h)", "Fuel Consumed (L)"]
            cur.execute("""
                SELECT 
                    t.imei, v.name as vehicle_name, 
                    to_char(t.start_time, 'YYYY-MM-DD HH24:MI') as start_str, 
                    to_char(t.end_time, 'YYYY-MM-DD HH24:MI') as end_str, 
                    ROUND(t.distance_km::numeric, 2) as distance, 
                    ROUND(t.avg_speed::numeric, 1) as avg_speed, 
                    ROUND(t.fuel_consumed::numeric, 2) as fuel
                FROM trip_summary t
                JOIN vehicles v ON t.imei = v.unique_id
                WHERE t.start_time >= CURRENT_DATE - CAST(%s AS INTERVAL)
                ORDER BY t.start_time DESC
                LIMIT 100
            """, (interval_str,))
            rows = [
                [r['imei'], r['vehicle_name'], r['start_str'], r['end_str'], str(r['distance']), str(r['avg_speed']), str(r['fuel'])]
                for r in cur.fetchall()
            ]
            
        elif report_type == "driver_activity":
            title = "IVMS Driver Session Activity Report"
            headers = ["Driver ID", "Driver Name", "Vehicle Name", "IMEI", "Login Time", "Logout Time"]
            cur.execute("""
                SELECT 
                    ds.driver_id, d.name as driver_name, v.name as vehicle_name, ds.imei,
                    to_char(ds.login_time, 'YYYY-MM-DD HH24:MI') as login_str, 
                    to_char(ds.logout_time, 'YYYY-MM-DD HH24:MI') as logout_str
                FROM driver_sessions ds
                LEFT JOIN drivers d ON ds.driver_id = d.driver_id
                LEFT JOIN vehicles v ON ds.imei = v.unique_id
                WHERE ds.login_time >= CURRENT_DATE - CAST(%s AS INTERVAL)
                ORDER BY ds.login_time DESC
                LIMIT 100
            """, (interval_str,))
            rows = [
                [r['driver_id'], r['driver_name'] or 'Unknown', r['vehicle_name'] or 'Unknown', r['imei'], r['login_str'], r['logout_str'] or 'Active Now']
                for r in cur.fetchall()
            ]
            
        elif report_type == "fleet_utilization":
            title = "IVMS Fleet Utilization Summary Report"
            headers = ["IMEI", "Vehicle Name", "Trips Run", "Total Distance (km)", "Total Fuel (L)", "Max Speed (km/h)"]
            cur.execute("""
                SELECT 
                    t.imei, v.name as vehicle_name, 
                    COUNT(*) as trips_count,
                    ROUND(SUM(t.distance_km)::numeric, 2) as total_distance, 
                    ROUND(SUM(t.fuel_consumed)::numeric, 2) as total_fuel,
                    ROUND(MAX(t.max_speed)::numeric, 1) as max_speed
                FROM trip_summary t
                JOIN vehicles v ON t.imei = v.unique_id
                WHERE t.start_time >= CURRENT_DATE - CAST(%s AS INTERVAL)
                GROUP BY t.imei, v.name
                ORDER BY total_distance DESC
                LIMIT 100
            """, (interval_str,))
            rows = [
                [r['imei'], r['vehicle_name'], str(r['trips_count']), str(r['total_distance']), str(r['total_fuel']), str(r['max_speed'])]
                for r in cur.fetchall()
            ]
            
        elif report_type == "alerts":
            title = "IVMS System Alerts & Events Report"
            headers = ["IMEI", "Vehicle Name", "Event Type", "Event Value", "Timestamp"]
            cur.execute("""
                SELECT 
                    a.imei, v.name as vehicle_name, a.event_type, 
                    ROUND(a.value::numeric, 2) as val,
                    to_char(a.timestamp, 'YYYY-MM-DD HH24:MI') as time_str
                FROM analytics_events a
                JOIN vehicles v ON a.imei = v.unique_id
                WHERE a.timestamp >= CURRENT_DATE - CAST(%s AS INTERVAL)
                ORDER BY a.timestamp DESC
                LIMIT 100
            """, (interval_str,))
            rows = [
                [r['imei'], r['vehicle_name'], r['event_type'], str(r['val']), r['time_str']]
                for r in cur.fetchall()
            ]
            
        cur.close()
        conn.close()
    except Exception as e:
        if cur:
            try: cur.close()
            except: pass
        if conn:
            try: 
                conn.rollback()
                conn.close()
            except: pass
        raise e

    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    file_uuid = str(uuid.uuid4())
    filename = f"fleet_report_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    filepath = os.path.join(reports_dir, f"{file_uuid}.pdf")
    
    doc = SimpleDocTemplate(filepath, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=6
    )
    
    meta_style = ParagraphStyle(
        'ReportMeta',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#6b7280'),
        spaceAfter=20
    )
    
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC) | Date Range Filter: Last {date_range}", meta_style))
    
    if not rows:
        no_data_style = ParagraphStyle(
            'NoData',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#ef4444'),
            spaceAfter=20
        )
        story.append(Paragraph("No data found for this query", no_data_style))
    else:
        table_data = [headers] + rows
        col_count = len(headers)
        col_width = 540 / col_count
        col_widths = [col_width] * col_count
        
        cell_style = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=8, leading=10)
        header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.white, fontName='Helvetica-Bold')
        
        formatted_table_data = []
        for r_idx, row in enumerate(table_data):
            formatted_row = []
            for c_idx, cell in enumerate(row):
                st = header_style if r_idx == 0 else cell_style
                formatted_row.append(Paragraph(str(cell), st))
            formatted_table_data.append(formatted_row)
            
        t = Table(formatted_table_data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1f2937')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f9fafb'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ]))
        story.append(t)
        
    doc.build(story)
    return filename, file_uuid


@ai_blueprint.route('/report/generate', methods=['POST'])
@role_required('user')
def generate_report():
    data = request.get_json() or {}
    report_type = data.get('report_type', 'trip_summary')
    date_range = data.get('date_range', 'today')
    filters = data.get('filters', {})
    
    allowed_types = {"trip_summary", "driver_activity", "fleet_utilization", "alerts"}
    allowed_ranges = {"today", "week", "month"}
    
    if report_type not in allowed_types or date_range not in allowed_ranges:
        return jsonify({"error": "Invalid report_type or date_range"}), 400
        
    try:
        filename, file_uuid = generate_pdf_report_file(report_type, date_range, filters)
        pdf_url = f"/ai/report/download/{file_uuid}"
        return jsonify({
            "pdf_url": pdf_url,
            "filename": filename
        })
    except Exception as e:
        current_app.logger.error(f"Report generation endpoint failed: {e}")
        return jsonify({"error": f"Failed to generate report: {e}"}), 500


@ai_blueprint.route('/report/download/<uuid_str>', methods=['GET'])
@role_required('user')
def download_report(uuid_str):
    # Strictly validate uuid format to block injection attacks
    try:
        uuid.UUID(uuid_str)
    except ValueError:
        return jsonify({"error": "Invalid report identifier"}), 400
        
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    filepath = os.path.join(reports_dir, f"{uuid_str}.pdf")
    
    if not os.path.exists(filepath):
        return jsonify({"error": "Report not found"}), 404
        
    filename = f"fleet_report_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    
    # Secure clean-up after serving the file
    @after_this_request
    def remove_file(response):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            current_app.logger.error(f"Error removing temp report file: {e}")
        return response
        
    return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/pdf')

