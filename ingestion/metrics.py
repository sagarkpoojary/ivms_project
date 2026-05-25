from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Ingestion Metrics
ACTIVE_SESSIONS = Gauge('ivms_ingestion_active_sessions', 'Number of active TCP sessions')
PACKETS_RECEIVED = Counter('ivms_ingestion_packets_total', 'Total number of AVL packets received')
RECORDS_RECEIVED = Counter('ivms_ingestion_records_total', 'Total number of AVL records decoded')
MALFORMED_PACKETS = Counter('ivms_ingestion_errors_total', 'Total number of malformed packets', ['error_type'])
AUTH_FAILURES = Counter('ivms_ingestion_auth_failures_total', 'Total unauthorized IMEI attempts')

# Database Metrics
DB_QUEUE_SIZE = Gauge('ivms_db_queue_size', 'Current size of the async DB insertion queue')
DB_WRITE_LATENCY = Histogram('ivms_db_write_latency_seconds', 'Latency of database write operations')
TELEMETRY_LAG = Histogram('ivms_telemetry_lag_seconds', 'Lag between device timestamp and server reception')

# Analytics Metrics
ANALYTICS_LATENCY = Histogram('ivms_analytics_processing_seconds', 'Time taken to process analytics per imei')
EVENTS_GENERATED = Counter('ivms_events_total', 'Total system events generated', ['severity', 'category'])

# WebSocket Metrics
WS_ACTIVE_CLIENTS = Gauge('ivms_ws_active_clients', 'Number of active WebSocket clients')
WS_MESSAGES_BROADCAST = Counter('ivms_ws_broadcast_total', 'Total messages broadcasted via WS')

# Hardening / Backpressure & Rate Limit Metrics
BACKPRESSURE_THROTTLING = Counter('ivms_backpressure_throttling_total', 'Total number of backpressure socket throttling events')
RECONNECT_THROTTLED = Counter('ivms_reconnect_throttled_total', 'Total number of reconnect storm throttled client IPs')

# Custom Observability Diagnostics Metrics
CODEC_MISMATCH = Counter('ivms_codec_mismatch_total', 'Total number of codec mismatch failures')
RECONCILIATION_LAG = Histogram('ivms_reconciliation_lag_seconds', 'Authoritative reconciliation latency')
WS_RECONNECTS = Counter('ivms_websocket_reconnects_total', 'Total number of WS client reconnects')
REDIS_LATENCY = Histogram('ivms_redis_latency_seconds', 'Redis cache read/write latency')
SOCKET_CHURN = Counter('ivms_socket_churn_total', 'Total number of sockets disconnected abruptly')
ACTIVE_PRODUCTION_DEVICES = Gauge('ivms_active_production_devices', 'Number of active production fleet devices')
ACTIVE_TESTING_DEVICES = Gauge('ivms_active_testing_devices', 'Number of active testing/simulated devices')
DEATHS_RECOVERED = Counter('ivms_deaths_recovered_total', 'Supervisor recoveries of dead tasks', ['task_name'])

def start_metrics_server(port=9090):
    start_http_server(port)
