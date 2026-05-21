-- ENTERPRISE DATA GOVERNANCE & RETENTION POLICIES
-- Goal: Prevent unbounded DB growth and maintain performance.

-- 1. Telemetry Retention (Strict 90-day hot storage)
SELECT add_retention_policy('telemetry', INTERVAL '90 days', if_not_exists => TRUE);

-- 2. Analytics Events Retention (180 days)
SELECT add_retention_policy('analytics_events', INTERVAL '180 days', if_not_exists => TRUE);

-- 3. Security Audit Retention (1 year for compliance)
SELECT add_retention_policy('security_audit', INTERVAL '1 year', if_not_exists => TRUE);

-- 4. System Events (60 days)
SELECT add_retention_policy('system_events', INTERVAL '60 days', if_not_exists => TRUE);

-- 5. Compression Policies (Compress older than 7 days)
SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('analytics_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('security_audit', INTERVAL '30 days', if_not_exists => TRUE);

-- 6. Maintenance History (Permanent, no retention policy - move to archive manually if needed)
-- CREATE TABLE maintenance_archive AS SELECT * FROM maintenance_history WHERE 1=0;

-- 7. Automated Cleanup Procedure for Non-Hypertable metadata
CREATE OR REPLACE PROCEDURE cleanup_stale_metadata()
LANGUAGE plpgsql
AS $$
BEGIN
    -- Delete stale websocket sessions older than 24h
    DELETE FROM live_vehicle_status WHERE last_update < NOW() - INTERVAL '24 hours';
    
    -- Delete old unacknowledged notifications (if needed)
    -- DELETE FROM notification_queue WHERE created_at < NOW() - INTERVAL '30 days';
    
    COMMIT;
END;
$$;
