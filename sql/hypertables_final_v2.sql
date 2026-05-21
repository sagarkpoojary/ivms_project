-- Fixing primary keys and converting to hypertables with FK handling
BEGIN;

-- 1. Handle analytics_events (no FKs usually)
ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS analytics_events_pkey CASCADE;
ALTER TABLE analytics_events ADD PRIMARY KEY (id, "timestamp");
SELECT create_hypertable('analytics_events', 'timestamp', if_not_exists => TRUE);

-- 2. Handle system_events and its dependents
ALTER TABLE notification_queue DROP CONSTRAINT IF EXISTS notification_queue_event_id_fkey;
ALTER TABLE system_events DROP CONSTRAINT IF EXISTS system_events_pkey CASCADE;
ALTER TABLE system_events ADD PRIMARY KEY (id, created_at);
SELECT create_hypertable('system_events', 'created_at', if_not_exists => TRUE);

-- 3. Re-add FK (Note: pointing to a composite PK can be tricky, but since 'id' is unique, it's fine)
-- Actually, Postgres requires FK to point to a unique constraint or PK. 
-- Since we added (id, created_at) as PK, we should add a UNIQUE constraint on (id) if we want simple FK.
ALTER TABLE system_events ADD CONSTRAINT system_events_id_unique UNIQUE (id);
ALTER TABLE notification_queue ADD CONSTRAINT notification_queue_event_id_fkey 
    FOREIGN KEY (event_id) REFERENCES system_events(id);

-- 4. Add retention policies
SELECT add_retention_policy('system_events', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('analytics_events', INTERVAL '180 days', if_not_exists => TRUE);

COMMIT;
