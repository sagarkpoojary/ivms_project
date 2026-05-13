-- Enterprise IVMS Schema
-- Version: 2.0 (Direct Ingestion)

-- 1. Device Profiles (Hardware/Protocol info)
CREATE TABLE IF NOT EXISTS device_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL, -- e.g., 'FMC130_Standard'
    protocol VARCHAR(50) DEFAULT 'codec8e',
    capabilities JSONB DEFAULT '{}', -- e.g., {"can_immobilize": true, "has_ble": true}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Configuration Templates (Phase 3)
CREATE TABLE IF NOT EXISTS config_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL, -- e.g., 'India_BSNL_Profile'
    description TEXT,
    apn_name VARCHAR(100),
    server_ip VARCHAR(50),
    server_port INTEGER,
    acquisition_settings JSONB, -- intervals, thresholds
    io_settings JSONB, -- enabled IDs, priorities
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Sim Cards
CREATE TABLE IF NOT EXISTS sim_cards (
    iccid VARCHAR(22) PRIMARY KEY,
    msisdn VARCHAR(20),
    operator VARCHAR(50), -- BSNL, Airtel, Ooredoo
    apn VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',
    last_balance_check TIMESTAMP WITH TIME ZONE
);

-- 4. Centralized Devices Table (Phase 2)
CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    imei VARCHAR(15) UNIQUE NOT NULL,
    name VARCHAR(100),
    profile_id INTEGER REFERENCES device_profiles(id),
    iccid VARCHAR(22) REFERENCES sim_cards(iccid),
    template_id INTEGER REFERENCES config_templates(id),
    firmware_version VARCHAR(50),
    last_ip VARCHAR(50),
    status VARCHAR(20) DEFAULT 'offline', -- online, offline, dormant
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP WITH TIME ZONE
);

-- 5. Command Queue (Phase 4)
CREATE TABLE IF NOT EXISTS command_queue (
    id BIGSERIAL PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    imei VARCHAR(15) REFERENCES devices(imei),
    command_type VARCHAR(50) NOT NULL, -- setparam, reboot, getgps
    command_payload TEXT,
    status VARCHAR(20) DEFAULT 'pending', -- pending, sent, acknowledged, failed
    retries INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP WITH TIME ZONE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    response_payload TEXT
);

-- 6. Telemetry (Historical Data)
CREATE TABLE IF NOT EXISTS telemetry (
    id BIGSERIAL PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    imei VARCHAR(15) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    priority INTEGER,
    longitude DECIMAL(11, 8),
    latitude DECIMAL(11, 8),
    altitude INTEGER,
    angle INTEGER,
    satellites INTEGER,
    speed INTEGER,
    event_id INTEGER,
    io_elements JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Live Vehicle Status (Real-time Cache in SQL)
CREATE TABLE IF NOT EXISTS live_vehicle_status (
    imei VARCHAR(15) PRIMARY KEY REFERENCES devices(imei),
    device_id INTEGER REFERENCES devices(id),
    last_timestamp TIMESTAMP WITH TIME ZONE,
    longitude DECIMAL(11, 8),
    latitude DECIMAL(11, 8),
    speed INTEGER,
    ignition BOOLEAN,
    movement BOOLEAN,
    gsm_signal INTEGER,
    external_voltage DECIMAL(10, 3),
    battery_voltage DECIMAL(10, 3),
    io_status JSONB, -- Full latest IO state
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_telemetry_imei_ts ON telemetry(imei, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_command_pending ON command_queue(imei, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);

-- Seed Data
INSERT INTO device_profiles (name, protocol) VALUES ('Teltonika_FMC130_Default', 'codec8e') ON CONFLICT DO NOTHING;
