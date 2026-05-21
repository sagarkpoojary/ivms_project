-- Enterprise Database Hardening & Optimization Script
-- Target: TimescaleDB / PostgreSQL 15

-- 1. Create Missing Performance Indexes
CREATE INDEX IF NOT EXISTS idx_telemetry_imei_time ON telemetry (imei, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_events_imei_time ON analytics_events (imei, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_system_events_time ON system_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_driver_sessions_driver_time ON driver_sessions (driver_id, login_time DESC);
CREATE INDEX IF NOT EXISTS idx_rfid_events_imei_time ON rfid_events (imei, "timestamp" DESC);

-- 2. Optimize Telemetry Hypertables (ensure it's actually a hypertable)
-- Note: 'create_hypertable' might fail if already a hypertable, so we check first.
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'telemetry') THEN
        PERFORM create_hypertable('telemetry', 'timestamp', if_not_exists => TRUE);
    END IF;
END $$;

-- 3. Set Retention Policies (Enterprise Standard: 90 days for raw telemetry)
SELECT add_retention_policy('telemetry', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('system_events', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('analytics_events', INTERVAL '180 days', if_not_exists => TRUE);

-- 4. Enable Compression (Enterprise Standard: compress after 7 days)
ALTER TABLE telemetry SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'imei'
);
SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);

-- 5. Vacuum and Analyze for fresh stats
ANALYZE telemetry;
ANALYZE trip_summary;
ANALYZE system_events;
ANALYZE analytics_events;
