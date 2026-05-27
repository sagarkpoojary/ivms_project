import os
from flask import request, jsonify, render_template, redirect, url_for, session, current_app
from werkzeug.utils import secure_filename
from auth.utils import role_required
from ai_module import ai_blueprint
from ai_module.services.ai_service import ai_service
from ai_module.services.rag_service import rag_service

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
