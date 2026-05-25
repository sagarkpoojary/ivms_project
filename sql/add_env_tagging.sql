-- Migration: Production Isolation & Telemetry Archiving
-- Purpose: Add telemetry environment tags, classify test/simulated devices, and archive stale stress telemetry.
-- Date: 2026-05-25

-- 1. Add telemetry_environment column to vehicles and live_vehicle_status tables
ALTER TABLE vehicles 
ADD COLUMN IF NOT EXISTS telemetry_environment VARCHAR(20) DEFAULT 'production';

ALTER TABLE live_vehicle_status 
ADD COLUMN IF NOT EXISTS telemetry_environment VARCHAR(20) DEFAULT 'production';

-- 2. Tag simulated stress test devices
UPDATE vehicles 
SET telemetry_environment = 'simulated' 
WHERE name LIKE '%Stress Device%';

UPDATE live_vehicle_status 
SET telemetry_environment = 'simulated' 
WHERE imei IN (SELECT unique_id FROM vehicles WHERE telemetry_environment = 'simulated');

-- 3. Tag office testing device
UPDATE vehicles 
SET telemetry_environment = 'testing' 
WHERE unique_id = '864275071330206';

UPDATE live_vehicle_status 
SET telemetry_environment = 'testing' 
WHERE imei = '864275071330206';

-- 4. Create archiving table for stale test telemetry
CREATE TABLE IF NOT EXISTS telemetry_archive (
    LIKE telemetry INCLUDING ALL
);

-- Create partition or indexes for archive table if they do not exist
CREATE INDEX IF NOT EXISTS idx_telemetry_archive_imei_ts ON telemetry_archive(imei, timestamp DESC);

-- 5. Copy all simulated/testing devices telemetry to archive
INSERT INTO telemetry_archive 
SELECT t.* FROM telemetry t
JOIN vehicles v ON t.imei = v.unique_id
WHERE v.telemetry_environment IN ('simulated', 'testing')
ON CONFLICT DO NOTHING;

-- 6. Delete archived records from primary telemetry hypertable
DELETE FROM telemetry 
WHERE imei IN (
    SELECT unique_id FROM vehicles 
    WHERE telemetry_environment IN ('simulated', 'testing')
);

-- 7. Clean up stale simulated/testing audit logs to optimize updates table
DELETE FROM live_position_updates 
WHERE imei IN (
    SELECT unique_id FROM vehicles 
    WHERE telemetry_environment IN ('simulated', 'testing')
);

SELECT 'Production Isolation & Archiving Migration Completed successfully' AS status;
