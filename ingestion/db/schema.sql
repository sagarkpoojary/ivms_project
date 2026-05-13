-- Devices Table
CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    imei VARCHAR(15) UNIQUE NOT NULL,
    name VARCHAR(100),
    model VARCHAR(50) DEFAULT 'FMC130',
    last_connected TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Telemetry Table (Raw Data)
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
    raw_packet TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Live Vehicle Status (Latest position and state)
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
    external_voltage DECIMAL(5, 2),
    battery_voltage DECIMAL(5, 2),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Driver Events (Alerts, RFID, etc.)
CREATE TABLE IF NOT EXISTS driver_events (
    id BIGSERIAL PRIMARY KEY,
    imei VARCHAR(15) REFERENCES devices(imei),
    event_type VARCHAR(50),
    event_value VARCHAR(255),
    timestamp TIMESTAMP WITH TIME ZONE,
    longitude DECIMAL(11, 8), latitude DECIMAL(11, 8),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_telemetry_imei_timestamp ON telemetry(imei, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_devices_imei ON devices(imei);
