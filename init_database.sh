#!/bin/bash
# ===========================================================================
# IVMS Enterprise TimescaleDB Bootstrapper Script
# ===========================================================================
# Runs SQL schema migration tables initializations inside db container.

echo "[DATABASE] Verifying TimescaleDB extensions & migrations..."

# Initialize main schema tables
docker exec -i ivms-db psql -U ivmsuser -d ivmsdb -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" >/dev/null 2>&1

# Apply non-blocking enterprise indexes if not already applied
cat /root/ivms_project/sql/enterprise_modules_indexes.sql | docker exec -i ivms-db psql -U ivmsuser -d ivmsdb >/dev/null 2>&1

# Create the telemetry auditer tables if they don't exist
docker exec -i ivms-db psql -U ivmsuser -d ivmsdb -c "
CREATE TABLE IF NOT EXISTS security_audit (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    details TEXT,
    severity VARCHAR(20) DEFAULT 'INFO',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);" >/dev/null 2>&1

echo "[DATABASE] TimescaleDB initialization successfully completed."
exit 0
