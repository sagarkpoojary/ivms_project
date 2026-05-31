# IVMS MOBILE-READY API CATALOG & INVENTORY

---

This catalog documents the entire API surface of the IVMS production system, assessing each endpoint's readiness and suitability for Google Flutter mobile applications.

## 1. Comprehensive Endpoint Inventory

### 1.1. Core Infrastructure & Device Metadata

#### `GET /health`
* **Description:** Basic service-level uptime health check.
* **Authentication:** None (Public)
* **Request Payload:** None
* **Response Payload:** `{"status": "ok"}`
* **Pagination & Filtering:** None
* **Rate Limiting:** None
* **Mobile Suitability:** **Excellent**. Used by mobile clients for edge latency and connectivity checks.

#### `GET /api/devices`
* **Description:** Returns basic registered vehicle metadata for a tenant.
* **Authentication:** Bearer JWT token fallback to Flask Session cookie.
* **Request Parameters:** `uid` (Optional, string)
* **Response Payload:**
  ```json
  [
    {
      "unique_id": "868575043159851",
      "name": "Heavy Truck 01",
      "parent_email": "saga@csloman.com"
    }
  ]
  ```
* **Pagination & Filtering:** Filter by single `uid` (IMEI) parameter. No pagination.
* **Rate Limiting:** Yes (`60/minute` enforced via `slowapi`).
* **Mobile Suitability:** **Good**. Serves as the primary metadata provider, though it should be combined with status information in a single query.

#### `GET /api/v2/devices`
* **Description:** Lists registered devices joined with active device profile information.
* **Authentication:** Bearer JWT or Session cookie.
* **Request Parameters:** `environment` (Optional, default: 'production')
* **Response Payload:**
  ```json
  [
    {
      "id": 142,
      "unique_id": "868575043159851",
      "name": "Heavy Truck 01",
      "profile_id": 4,
      "profile_name": "Standard Logistics Truck",
      "telemetry_environment": "production"
    }
  ]
  ```
* **Pagination & Filtering:** Filter by `environment`. No pagination.
* **Rate Limiting:** None
* **Mobile Suitability:** **Good**. Useful for admin configuration panels.

---

### 1.2. Real-Time Status & Streaming

#### `GET /api/v2/live-status`
* **Description:** Fetches current real-time fleet statuses directly from the high-speed Redis cache.
* **Authentication:** Bearer JWT or Session cookie.
* **Request Parameters:** `environment` (Optional, default: 'production')
* **Response Payload:**
  ```json
  [
    {
      "imei": "868575043159851",
      "status": "moving",
      "speed": 62,
      "latitude": 23.5859,
      "longitude": 58.4059,
      "ignition": true,
      "movement": true,
      "timestamp": "2026-05-30T09:12:00Z"
    }
  ]
  ```
* **Pagination & Filtering:** Omitted (Fetches all allowed tenant devices). No pagination.
* **Rate Limiting:** None
* **Mobile Suitability:** **Excellent**. Instant cache retrieval (<5ms response time) is highly efficient for rendering mobile fleet summaries.

#### `WebSocket /ws/live`
* **Description:** Real-time WebSockets update channel.
* **Authentication:** JWT Access Token passed via URL query parameter: `/ws/live?token=...`
* **Connection Logic:** Stream-based. Broadcasts coordinate frames with a 100ms deduplication delay.
* **Response Payload:** Real-time telemetry events.
* **Mobile Suitability:** **Excellent**. Directly supported by Flutter WebSockets client libraries. Requires persistent socket monitoring in Dart.

---

### 1.3. Playbacks & Reports

#### `GET /api/v1/reports/history/{imei}`
* **Description:** Fetches historical telemetry points for map path playbacks.
* **Authentication:** Bearer JWT or Session cookie.
* **Request Parameters:** `start` (datetime), `end` (datetime)
* **Response Payload:**
  ```json
  [
    {"latitude": 23.5859, "longitude": 58.4059, "speed": 62, "ignition": true, "timestamp": "2026-05-30T08:00:00Z"}
  ]
  ```
* **Pagination & Filtering:** Native route simplification (`simplify_route`) is applied to prune redundant points. No pagination.
* **Rate Limiting:** None
* **Mobile Suitability:** **Excellent**. The `simplify_route` processing significantly reduces the payload size, making it safe for mobile memory capacities.

#### `GET /api/v1/reports/trips/{imei}`
* **Description:** Fetches comprehensive trip summaries (times, geofences, speeds, distances).
* **Authentication:** Bearer JWT or Session cookie.
* **Request Parameters:** `start` (datetime), `end` (datetime)
* **Response Payload:** Summarized trip arrays.
* **Pagination & Filtering:** None
* **Rate Limiting:** None
* **Mobile Suitability:** **Requires Changes**. Large dates can return huge datasets. Enforce a maximum query range constraint (e.g. 7 days limit) for mobile requests.

#### `POST /api/v1/reports/export/history/{imei}`
* **Description:** Asynchronously compiles telemetry history to a CSV file.
* **Authentication:** Bearer JWT or Session cookie.
* **Request Parameters:** `start`, `end`
* **Response Payload:** `{"status": "success", "filename": "export_868575_2026.csv"}`
* **Mobile Suitability:** **Unsuitable**. Mobile apps must not compile or download raw CSV text files. Historical data should be consumed via interactive lightweight widgets.

---

### 1.4. Operations, Drivers & Geofencing

#### `GET /api/v2/ops/sites`
* **Description:** Lists geofenced operations sites for the tenant.
* **Authentication:** Bearer JWT or Session cookie.
* **Mobile Suitability:** **Excellent**. Used to render operational boundaries on maps.

#### `POST /api/v2/ops/sites`
* **Description:** Creates a circular geofence boundary.
* **Authentication:** Bearer JWT or Session cookie (Admins only).
* **Request Payload:** `site_id` (string), `name` (string), `latitude` (float), `longitude` (float), `radius` (integer)
* **Mobile Suitability:** **Good**. Allows admins to mark sites in the field using their device's GPS.

#### `GET /api/v2/ops/drivers`
* **Description:** Lists all registered RFID drivers.
* **Authentication:** Bearer JWT or Session cookie.
* **Mobile Suitability:** **Excellent**. Serves as the driver directory source.

#### `GET /api/v2/ops/driver-attendance`
* **Description:** Returns real-time active driver login timelines.
* **Authentication:** Bearer JWT or Session cookie.
* **Mobile Suitability:** **Excellent** for monitoring which driver is currently in which vehicle.

#### `GET /api/v2/ops/service-tickets`
* **Description:** Lists service and maintenance requests for tenant vehicles.
* **Authentication:** Bearer JWT or Session cookie.
* **Mobile Suitability:** **Good**. Ready for maintenance dashboard integrations.

---

## 2. API Readiness Matrix

| Endpoint Route | Mobile Ready | Changes Required / Notes |
| :--- | :---: | :--- |
| `GET /health` | **YES** | None. |
| `GET /api/devices` | **YES** | Omit redundant telemetry profile relations if not requested. |
| `GET /api/v2/devices` | **YES** | None. |
| `GET /api/v2/live-status` | **YES** | Optimize status flags mapping for mobile. |
| `WebSocket /ws/live` | **YES** | Flutter can connect by supplying JWT in query parameters. |
| `GET /api/v1/reports/history/{imei}` | **YES** | Highly performant due to built-in Ramer-Douglas-Peucker simplification. |
| `GET /api/v1/reports/trips/{imei}` | **NO** | Add query limit constraints (max 30 trips per call). |
| `GET /api/v1/reports/events/{imei}` | **YES** | Enforce a strict `LIMIT 100`. |
| `GET /api/v1/reports/daily-summary/{imei}` | **YES** | Clean daily aggregations. |
| `POST /api/v1/reports/export/history/{imei}`| **NO** | CSV generation is resource-intensive; omit from mobile apps. |
| `GET /api/v2/ops/sites` | **YES** | None. |
| `POST /api/v2/ops/sites` | **YES** | None. |
| `GET /api/v2/ops/drivers` | **YES** | None. |
| `POST /api/v2/ops/drivers` | **YES** | Integrate device camera permissions for profile photos. |
| `GET /api/v2/ops/site-visits` | **YES** | None. |
| `GET /api/v2/ops/service-tickets` | **YES** | None. |
| `GET /api/v2/ops/driver-attendance` | **YES** | None. |
| `GET /api/v2/ops/rfid-timeline` | **YES** | None. |
| `POST /api/v1/commands/send` | **YES** | Fully operational for sending MQTT/TCP commands. |
| `GET /api/v2/analytics/fleet-efficiency` | **YES** | Renders safety score statistics. |
| `GET /api/v2/analytics/driver-score` | **YES** | Renders active driver leaderboards. |
| `GET /api/v2/analytics/events` | **YES** | Includes color-coded alert severity scales. |
| `GET /api/v2/diagnostics/live-position/{imei}`| **NO** | Restricted diagnostics; hide from mobile clients. |
| `GET /api/v2/diagnostics/live-update-audit/{imei}`| **NO** | Internal admin operations tool; omit. |

---

## 3. Highlighting API Gaps & Vulnerabilities

### 3.1. Missing APIs for Mobile UI
* **Push Notification Registries:** Complete absence of endpoints to register, update, or revoke Firebase Cloud Messaging (FCM) or Apple Push Notification service (APNs) device tokens (`POST /api/v2/notifications/register-token`).
* **Unified Dashboard Aggregation:** Mobile requires a consolidated, single-query API endpoint returning active/offline counts, today's distances, safety violations, and open service tickets (`GET /api/v2/mobile/dashboard`) to optimize network requests and battery life.
* **Dedicated Authentication API:** No standalone route exists in the API gateway specifically designed for user login (`POST /auth/token`) that verifies credentials and issues access/refresh JWT tokens directly, bypassing browser cookies.

### 3.2. Duplicate APIs (Web SSR vs. FastAPI)
* **Fleet Listings:**
  * Duplicate 1: `GET /api/devices` (FastAPI router returning clean metadata)
  * Duplicate 2: `GET /api/v2/devices` (FastAPI router returning metadata joined with profile structures)
  * Duplicate 3: `GET /api/v1/reports/live-status` (Flask router serving live states to Odoo integration)
* **Resolution:** Standardize the mobile application to consume **only** `GET /api/v2/devices` and `GET /api/v2/live-status` from the FastAPI Gunicorn container, avoiding Flask blueprints completely.

### 3.3. Legacy & Internal-Only APIs
* **Diagnostics Suite:** Endpoints such as `/api/v2/diagnostics/live-position/{imei}` and `/api/v2/diagnostics/live-update-audit/{imei}` are highly internal. They expose SQL reconciliation latency statistics, transaction locks, and previous vs. new telemetry IDs.
* **Risk:** These must be isolated. While authorized for `super_admin` and `main_admin` roles, they expose unnecessary internal database schemas and structural data that could lead to reconnaissance exploits if intercepted. They must be explicitly locked out of mobile client access.

### 3.4. APIs Exposing Unnecessary Fields
* **Raw Packets Exposure:** The `/api/v2/diagnostics/packets/{imei}` endpoint exposes the raw hex-encoded TCP packets (`raw_packet`) along with extensive decoded nested dictionaries.
* **Payload Bloat:** Exposing raw hexadecimal packets consumes large amounts of bandwidth. Mobile clients have no use for hex payloads. The database serialization schema for mobile-facing routes must strictly filter out raw telemetry streams.
