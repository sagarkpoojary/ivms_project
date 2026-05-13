from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Ingestion Metrics
ACTIVE_SESSIONS = Gauge('teltonika_active_sessions', 'Number of active TCP sessions')
PACKETS_RECEIVED = Counter('teltonika_packets_received_total', 'Total number of AVL packets received')
RECORDS_RECEIVED = Counter('teltonika_records_received_total', 'Total number of AVL records decoded')
MALFORMED_PACKETS = Counter('teltonika_malformed_packets_total', 'Total number of malformed packets')

# Database Metrics
DB_QUEUE_SIZE = Gauge('teltonika_db_queue_size', 'Current size of the async DB insertion queue')
DB_WRITE_LATENCY = Histogram('teltonika_db_write_latency_seconds', 'Latency of database write operations')

def start_metrics_server(port=9090):
    start_http_server(port)
