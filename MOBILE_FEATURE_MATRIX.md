# IVMS WEB VS. MOBILE FEATURE MATRIX

---

This document outlines the comparative mapping between existing IVMS Web features and the proposed target states for the Google Flutter Android & iOS mobile applications. It establishes the current status, mobile readiness levels, and specific backend/frontend work required to bring these capabilities to mobile devices.

## 1. Core Feature Matrix

| Module | Web Status | Mobile Ready | Work Required |
| :--- | :--- | :---: | :--- |
| **1. Dashboard** | **Fully Operational**<br>Renders KPIs (vehicle status, today's distances, fuel costs) via Flask/Jinja templates. | **Partial** | **Backend:** Create a consolidated, low-latency mobile dashboard KPI aggregator endpoint (`/api/v2/mobile/dashboard`) to fetch active/offline counts, today's alerts, and open tickets in a single request.<br>**Frontend:** Design a modern glassmorphic dashboard layout with micro-animations and swipe-to-refresh. |
| **2. Fleet Overview** | **Fully Operational**<br>Lists active/inactive vehicles with telemetry status and current drivers. | **Yes** | **Backend:** None. Can fully leverage the existing `/api/v2/live-status` endpoint.<br>**Frontend:** Build a performant search-and-filter card list. Implement infinite scrolling or lazy loading for fleets with more than 100 vehicles. |
| **3. Vehicle Tracking** | **Fully Operational**<br>Displays active telemetry updates on a Leaflet map. | **Yes** | **Backend:** Reuse `/api/v2/live-status` and WebSocket `/ws/live` streams.<br>**Frontend:** Implement a background-optimized background thread inside Flutter to manage WebSocket streams, preventing screen lock timeouts. |
| **4. Live Map** | **Fully Operational**<br>Renders Leaflet-based live tracking, geofence site overlays, and marker animations. | **Yes** | **Backend:** Reuse `/ws/live` and `/api/v2/ops/sites`.<br>**Frontend:** Integrate **Flutter Map** (OpenStreetMap-based) or **Google Maps Flutter SDK**. Re-implement marker animation interpolation in Dart for smooth vehicle movements. |
| **5. Driver Registry** | **Fully Operational**<br>CRUD operations for drivers via Flask forms. | **Yes** | **Backend:** Can leverage existing `/api/v2/ops/drivers` REST endpoints.<br>**Frontend:** Build user-friendly card forms to add and edit driver details, with native camera integration for driver profile photo uploads. |
| **6. RFID Drivers** | **Fully Operational**<br>Monitors real-time RFID login/logout timeline and attendance. | **Yes** | **Backend:** Can leverage `/api/v2/ops/driver-attendance` and `/api/v2/ops/rfid-timeline`.<br>**Frontend:** Build a clean RFID timeline view showing active driver logs with color-coded badges for validated vs. unvalidated logins. |
| **7. Maintenance** | **Fully Operational**<br>Tracks vehicle service schedules, insurance statuses, and renewals. | **Partial** | **Backend:** Build a dedicated `/api/v2/mobile/maintenance` endpoint to list insurance/registration expiries.<br>**Frontend:** Implement high-contrast visual status badges ("Active", "Expiring Soon", "Expired") and push notification opt-in. |
| **8. Site Operations** | **Fully Operational**<br>Manages geo-fenced operations, coordinates, and radius settings. | **Yes** | **Backend:** Can reuse `/api/v2/ops/sites` and `/api/v2/ops/site-visits`.<br>**Frontend:** Render circular geofenced zones on the live map and list historical geofence arrival/departure lists. |
| **9. Service Tickets** | **Fully Operational**<br>CRUD for maintenance ticket creations and resolution audits. | **Yes** | **Backend:** Leverage existing `/api/v2/ops/service-tickets` endpoints.<br>**Frontend:** Form-driven design allowing admins to submit, update, and resolve maintenance service tickets directly from their mobile device. |
| **10. Reports** | **Fully Operational**<br>Renders heavy playback animations and compiles massive CSV/PDF reports via Celery. | **No** | **Backend:** Current report generation compiles large payloads that exhaust mobile memory. Backend must expose a compressed history endpoint or slice reports into manageable chunks (e.g. 500-point playbacks).<br>**Frontend:** Avoid PDF/CSV downloads on mobile. Render interactive, lightweight SVG charts and simplified playback animations instead. |
| **11. Analytics** | **Fully Operational**<br>Calculates driver safety scores and fleet fuel efficiency. | **Yes** | **Backend:** Leverage `/api/v2/analytics/fleet-efficiency` and `/api/v2/analytics/driver-score`.<br>**Frontend:** Design custom gauge charts to represent fleet health, driver scores, and efficiency trends (utilizing Flutter's `fl_chart` library). |
| **12. Alerts** | **Fully Operational**<br>Monitors today's overspeed, geofence breach, and RFID violations. | **Yes** | **Backend:** Leverage `/api/alerts` and `/api/v2/analytics/events`.<br>**Frontend:** Implement local SQLite-based notification caching to allow offline reviews of historical safety alerts. |
| **13. Notifications** | **Web-Only (Stated)**<br>Notification queues and system badges generated on web. | **No** | **Backend:** Major Gap. Must implement Firebase Cloud Messaging (FCM) integration, token registration endpoints, and a notification push worker to broadcast background alerts.<br>**Frontend:** Integrate native Android and iOS notification listeners. |
| **14. User Management** | **Fully Operational**<br>Manages user roles, tenant logins, and system configurations. | **Partial** | **Backend:** Build role management details into the `/auth/token` JWT response payload to enable clean client-side feature flagging.<br>**Frontend:** Render dynamic menus based on active roles (e.g., hiding maintenance ticket submissions for read-only 'user' roles). |
| **15. AI Copilot** | **Web-Only**<br>Lexical RAG and whitelisted SQL translation floating widget. | **No** | **Backend:** Port `/ai/chat` endpoint to FastAPI router. Support streaming JSON chunking or asynchronous WebSockets to prevent mobile timeout errors during database searches.<br>**Frontend:** Build a native conversational chat window with quick-reply suggestions. |
| **16. Settings** | **Fully Operational**<br>Configures system configurations, telemetry targets, and AI keys. | **No** | **Backend:** Expose setting modification routes via the API gateway.<br>**Frontend:** Restrict this module completely on mobile or reserve it exclusively for the `super_admin` role via a custom security policy. |
| **17. Plans & Pricing** | **Fully Operational**<br>Displays SaaS plans (Normal, Premium, Enterprise) with billing filters. | **Unsuitable** | **Work Required:** Unsuitable for native mobile rendering. To comply with Apple App Store and Google Play billing guidelines, SaaS pricing grids and subscriptions must be handled via standard web payment gateways. Recommend launching the mobile app as a utility tool for existing web subscribers only, omitting plans from mobile views. |

---

## 2. Web vs. Mobile Architecture Mapping

```
┌────────────────────────────────────────────────────────┐
│                   WEB ARCHITECTURE                     │
│  - Session: Cookie-based (itsdangerous state)         │
│  - Frontend: Jinja2 SSR, Leaflet.js, Raw WS            │
│  - Payload: Large, verbose web JSON collections        │
│  - Alerts: Local system alarms & Email queues          │
│  - AI: Integrated in Flask session-based blueprint     │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Mobile Transformation Gaps)
┌────────────────────────────────────────────────────────┐
│                 MOBILE ARCHITECTURE                    │
│  - Session: Stateless JWT (Bearer Authorization)        │
│  - Frontend: Google Flutter Native, Native Maps SDK    │
│  - Payload: Paginated, compressed, optimized JSON      │
│  - Alerts: FCM & APNs Background Push Notifications    │
│  - AI: Asynchronous FastAPI REST/WebSocket endpoints   │
└────────────────────────────────────────────────────────┘
```

---

## 3. Specific Work Required for Mobile Adaptability

### 3.1. Network & Footprint Optimization
Mobile networks are variable and resource-constrained.
* **Problem:** Web APIs currently return raw arrays containing thousands of items (e.g. `/api/v2/telemetry/{imei}` returning all raw database columns).
* **Fix:** Enforce strict pagination queries (e.g., `LIMIT 50 OFFSET 0`) on all history and event listing endpoints. Optimize serialization models to omit unnecessary fields (such as raw, decoded bytes of AVL frames) before dispatching JSON payloads to mobile.

### 3.2. Background Execution & Battery Health
* **Problem:** Continuous WebSocket socket streaming drains mobile batteries within hours and gets terminated by mobile OS schedulers when the app is backgrounded.
* **Fix:** Implement a hybrid syncing strategy. When the mobile app is in the foreground, use WebSocket connections for active map tracks. When backgrounded, terminate the WebSocket and rely entirely on Firebase Push Notifications to notify the user of critical overspeed or geofence violations.
