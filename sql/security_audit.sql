-- Security & Audit Trail Tables (FIXED)
CREATE TABLE IF NOT EXISTS security_audit (
    id SERIAL,
    event_type TEXT NOT NULL,
    email TEXT,
    ip_address TEXT,
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, created_at)
);

-- Convert to hypertable for scalability
SELECT create_hypertable('security_audit', 'created_at', if_not_exists => TRUE);

-- Brute Force Protection Table
CREATE TABLE IF NOT EXISTS login_attempts (
    ip_address TEXT PRIMARY KEY,
    attempts INT DEFAULT 0,
    last_attempt TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_blocked BOOLEAN DEFAULT FALSE,
    blocked_until TIMESTAMP WITH TIME ZONE
);
