import json
import uuid
import time
import logging
from flask import request, g, jsonify

logger = logging.getLogger("ivms.audit")

class StructuredLoggingMiddleware:
    """
    Structured Logging & Request Correlation ID Middleware.
    Ensures every request carries a unique X-Request-ID, captures request/response
    metadata, and logs structured JSON logs to standard output/logs.
    """
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        @app.before_request
        def before_request():
            g.start_time = time.time()
            
            # Extract correlation ID from header, or generate a clean UUID4
            correlation_id = request.headers.get('X-Request-ID') or request.headers.get('X-Correlation-ID')
            if not correlation_id:
                correlation_id = str(uuid.uuid4())
            g.correlation_id = correlation_id

        @app.after_request
        def after_request(response):
            # Calculate latency in milliseconds
            duration = 0.0
            if hasattr(g, 'start_time'):
                duration = round((time.time() - g.start_time) * 1000.0, 2)

            correlation_id = getattr(g, 'correlation_id', 'unknown')
            
            # Inject correlation ID header in response
            response.headers['X-Request-ID'] = correlation_id
            
            # Calculate response size safely to avoid Werkzeug direct passthrough errors
            try:
                if response.direct_passthrough:
                    response_size = response.calculate_content_length() or 0
                else:
                    response_size = response.calculate_content_length() or len(response.get_data())
            except Exception:
                response_size = 0

            # Structured JSON payload
            log_payload = {
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                "correlation_id": correlation_id,
                "remote_ip": request.remote_addr,
                "method": request.method,
                "path": request.path,
                "query_params": request.args.to_dict(),
                "status_code": response.status_code,
                "response_size_bytes": response_size,
                "latency_ms": duration,
                "user_agent": request.user_agent.string
            }
            
            # Write structured log to standard audit pipeline
            logger.info(json.dumps(log_payload))
            return response
            
        @app.errorhandler(Exception)
        def handle_exception(e):
            duration = 0.0
            if hasattr(g, 'start_time'):
                duration = round((time.time() - g.start_time) * 1000.0, 2)
                
            correlation_id = getattr(g, 'correlation_id', 'unknown')
            
            error_payload = {
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                "correlation_id": correlation_id,
                "remote_ip": request.remote_addr,
                "method": request.method,
                "path": request.path,
                "status_code": 500,
                "latency_ms": duration,
                "error_type": e.__class__.__name__,
                "error_message": str(e),
                "severity": "CRITICAL"
            }
            logger.error(json.dumps(error_payload))
            
            # Re-raise or return structured 500 JSON response
            return jsonify({"status": "error", "message": "An internal server error occurred", "correlation_id": correlation_id}), 500
