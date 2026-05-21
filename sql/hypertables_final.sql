-- Fixing primary keys and converting to hypertables
BEGIN;

-- analytics_events
ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS analytics_events_pkey;
ALTER TABLE analytics_events ADD PRIMARY KEY (id, "timestamp");
SELECT create_hypertable('analytics_events', 'timestamp', if_not_exists => TRUE);

-- system_events
ALTER TABLE system_events DROP CONSTRAINT IF EXISTS system_events_pkey;
ALTER TABLE system_events ADD PRIMARY KEY (id, created_at);
SELECT create_hypertable('system_events', 'created_at', if_not_exists => TRUE);

-- Add retention policies
SELECT add_retention_policy('system_events', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('analytics_events', INTERVAL '180 days', if_not_exists => TRUE);

COMMIT;
