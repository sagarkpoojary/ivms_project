-- 1. Enable Continuous Aggregates
-- Daily Summary for Distance and Speed
CREATE MATERIALIZED VIEW IF NOT EXISTS fleet_daily_summary
WITH (timescaledb.continuous) AS
SELECT 
    imei,
    time_bucket('1 day', timestamp) as day,
    MAX(speed) as max_speed,
    AVG(speed) as avg_speed,
    COUNT(*) as points_count
FROM telemetry
GROUP BY imei, day
WITH NO DATA;

-- 2. Set Refresh Policy (Refresh every hour for data older than 2 hours)
SELECT add_continuous_aggregate_policy('fleet_daily_summary',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '2 hours',
    schedule_interval => INTERVAL '1 hour');

-- 3. Monthly Aggregate (Based on Daily for efficiency)
CREATE MATERIALIZED VIEW IF NOT EXISTS fleet_monthly_summary
WITH (timescaledb.continuous) AS
SELECT 
    imei,
    time_bucket('1 month', day) as month,
    MAX(max_speed) as max_speed,
    AVG(avg_speed) as avg_speed,
    SUM(points_count) as total_points
FROM fleet_daily_summary
GROUP BY imei, month
WITH NO DATA;

-- 4. Set Refresh Policy for Monthly
SELECT add_continuous_aggregate_policy('fleet_monthly_summary',
    start_offset => INTERVAL '1 year',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');
