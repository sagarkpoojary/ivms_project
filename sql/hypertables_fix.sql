-- Convert event tables to hypertables for enterprise scalability
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'system_events') THEN
        PERFORM create_hypertable('system_events', 'created_at', if_not_exists => TRUE);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'analytics_events') THEN
        PERFORM create_hypertable('analytics_events', 'timestamp', if_not_exists => TRUE);
    END IF;
END $$;

-- Set Retention Policies
SELECT add_retention_policy('system_events', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('analytics_events', INTERVAL '180 days', if_not_exists => TRUE);
