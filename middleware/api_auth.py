import time
import functools
from flask import request, jsonify, g
from config import Config
from models.api_access_log import log_api_access
from prometheus_client import Counter, Histogram

# Initialize Prometheus Metrics for Observability (Phase 8)
EXT_API_REQUESTS = Counter(
    'ivms_external_api_requests_total',
    'Total external API requests',
    ['endpoint', 'method', 'status_code']
)
EXT_API_LATENCY = Histogram(
    'ivms_external_api_latency_seconds',
    'Latency of external API requests in seconds',
    ['endpoint']
)
EXT_API_AUTH_FAILURES = Counter(
    'ivms_external_api_auth_failures_total',
    'Total failed auth attempts',
    ['ip_address']
)
EXT_API_ERRORS = Counter(
    'ivms_external_api_errors_total',
    'Total external API errors',
    ['endpoint', 'error_type']
)

def api_token_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        start_time = time.time()
        
        # Capture remote IP safely (handling proxies)
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()
            
        endpoint = request.path
        method = request.method
        
        # Token validation
        auth_header = request.headers.get('Authorization')
        token_valid = False
        token_used = None
        
        if auth_header:
            try:
                parts = auth_header.split()
                if len(parts) == 2 and parts[0].lower() == 'bearer':
                    token_used = parts[1]
                    if token_used == Config.ODOO_REPORT_TOKEN:
                        token_valid = True
            except Exception:
                pass
                
        if not token_valid:
            # Increment failed auth metric
            EXT_API_AUTH_FAILURES.labels(ip_address=ip_address).inc()
            
            # Log failure to DB
            duration = (time.time() - start_time) * 1000.0
            log_api_access(
                ip_address=ip_address,
                endpoint=endpoint,
                method=method,
                status_code=401 if not auth_header else 403,
                duration_ms=duration,
                response_size=0,
                error_message="Unauthorized access: Invalid or missing bearer token",
                token_used=token_used
            )
            
            EXT_API_REQUESTS.labels(
                endpoint=endpoint, 
                method=method, 
                status_code=401 if not auth_header else 403
            ).inc()
            
            return jsonify({"status": "error", "message": "Unauthorized"}), 401 if not auth_header else 403

        # Execute target route
        try:
            g.start_time = start_time
            g.ip_address = ip_address
            g.token_used = token_used
            
            response = f(*args, **kwargs)
            
            # Parse status code and response size
            status_code = 200
            resp_obj = response
            
            if isinstance(response, tuple):
                resp_obj = response[0]
                if len(response) > 1:
                    status_code = response[1]
            
            # Calculate response length
            try:
                if hasattr(resp_obj, 'get_data'):
                    response_size = len(resp_obj.get_data())
                elif hasattr(resp_obj, 'response'):
                    response_size = sum(len(chunk) for chunk in resp_obj.response)
                else:
                    response_size = len(str(resp_obj).encode('utf-8'))
            except:
                response_size = 0
                
            duration = (time.time() - start_time) * 1000.0
            EXT_API_LATENCY.labels(endpoint=endpoint).observe(duration / 1000.0)
            
            # Log access to DB
            log_api_access(
                ip_address=ip_address,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                duration_ms=duration,
                response_size=response_size,
                error_message=None,
                token_used=token_used
            )
            
            EXT_API_REQUESTS.labels(
                endpoint=endpoint, 
                method=method, 
                status_code=status_code
            ).inc()
            
            return response
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            duration = (time.time() - start_time) * 1000.0
            EXT_API_ERRORS.labels(endpoint=endpoint, error_type=type(e).__name__).inc()
            
            log_api_access(
                ip_address=ip_address,
                endpoint=endpoint,
                method=method,
                status_code=500,
                duration_ms=duration,
                response_size=0,
                error_message=str(e),
                token_used=token_used
            )
            
            EXT_API_REQUESTS.labels(
                endpoint=endpoint, 
                method=method, 
                status_code=500
            ).inc()
            
            return jsonify({"status": "error", "message": "Internal Server Error"}), 500
            
    return decorated
