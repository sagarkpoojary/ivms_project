-- MIGRATION: Live Position Reconciliation Engine
-- Purpose: Add authoritative position tracking to fix live map synchronization
-- Date: 2026-05-20
-- Version: 1.0

-- PHASE 1: Add authoritative position tracking columns to live_vehicle_status
-- These columns track which telemetry record is the definitive "live" position
ALTER TABLE live_vehicle_status 
ADD COLUMN IF NOT EXISTS last_telemetry_id BIGINT,
ADD COLUMN IF NOT EXISTS last_valid_packet_time TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS live_position_reconciliation_version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS reconciliation_flags JSONB DEFAULT '{}';

-- PHASE 2: Create index for faster position lookups
CREATE INDEX IF NOT EXISTS idx_live_vehicle_status_telemetry_id 
ON live_vehicle_status(imei, last_telemetry_id);

-- PHASE 3: Create chronological integrity table for audit logging
CREATE TABLE IF NOT EXISTS live_position_updates (
    id BIGSERIAL PRIMARY KEY,
    imei VARCHAR(15) NOT NULL,
    previous_telemetry_id BIGINT,
    new_telemetry_id BIGINT NOT NULL,
    previous_timestamp TIMESTAMP WITH TIME ZONE,
    new_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    was_stale BOOLEAN DEFAULT FALSE,
    reason VARCHAR(100), -- 'new_packet', 'recovered_from_cache', 'websocket_sync', etc.
    websocket_emitted BOOLEAN DEFAULT FALSE,
    redis_updated BOOLEAN DEFAULT FALSE,
    update_latency_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_live_position_updates_imei_ts 
ON live_position_updates(imei, created_at DESC);

-- PHASE 4: Create Redis cache health table for monitoring
CREATE TABLE IF NOT EXISTS redis_cache_health (
    id BIGSERIAL PRIMARY KEY,
    imei VARCHAR(15) NOT NULL,
    cache_status VARCHAR(20), -- 'consistent', 'stale', 'missing', 'divergent'
    db_timestamp TIMESTAMP WITH TIME ZONE,
    cache_timestamp TIMESTAMP WITH TIME ZONE,
    timestamp_delta_ms INTEGER,
    position_delta_m DECIMAL(10, 2),
    checker_run_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_redis_cache_health_check_run 
ON redis_cache_health(checker_run_at DESC);

-- PHASE 5: Create websocket sync tracking table
CREATE TABLE IF NOT EXISTS websocket_sync_log (
    id BIGSERIAL PRIMARY KEY,
    imei VARCHAR(15) NOT NULL,
    event_type VARCHAR(50), -- 'position_update', 'reconciliation', 'cache_rebuild', 'reconnect'
    websocket_clients_notified INTEGER,
    redis_publish_success BOOLEAN,
    timestamp_at_emit TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_websocket_sync_log_recent 
ON websocket_sync_log(created_at DESC, imei);

-- Migration complete
SELECT 'Live Position Reconciliation Engine Schema Initialized' AS status;
