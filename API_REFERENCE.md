# IVMS Enterprise Versioned API Reference

All requests to the versioned `/api/v1/` endpoints must include the authentication header:
`Authorization: Bearer <ODOO_REPORT_TOKEN>`

## Endpoints

### 1. `GET /api/v1/reports/live-status`
- **Description**: Real-time position status of all active vehicles.
- **Parameters**: `compatibility=traccar` (Optional - outputs Traccar schema).
- **Format**: JSON list.

### 2. `GET /api/v1/reports/fleet-summary`
- **Description**: Daily fleet summaries (distances, fuel consumption, engine hours).
- **Parameters**: `from_date` (YYYY-MM-DD), `to_date` (YYYY-MM-DD).
- **Format**: JSON list.

### 3. `GET /api/v1/dashboard/summary`
- **Description**: Aggregated KPI stats for map widgets (online, moving, idle counts).
- **Parameters**: `from_date` (YYYY-MM-DD), `to_date` (YYYY-MM-DD).
- **Format**: JSON object.
