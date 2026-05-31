# IVMS MOBILE DEVELOPMENT ROADMAP

---

This document presents a structured, 4-phase development roadmap to design, build, and deploy the native Android and iOS mobile applications for the IVMS enterprise platform using Google Flutter.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        IVMS MOBILE ROADMAP                             │
├────────────────────────────────────────────────────────────────────────┤
│ PHASE 1: CORE MOBILE APP (Weeks 1 - 4)                                 │
│  - JWT Auth Gateway, Map SDK, Live Tracking, Redis Cache Sync         │
├────────────────────────────────────────────────────────────────────────┤
│ PHASE 2: OPERATIONS (Weeks 5 - 8)                                      │
│  - Driver Profiles, RFID Timelines, Maintenance, Service Tickets       │
├────────────────────────────────────────────────────────────────────────┤
│ PHASE 3: INTELLIGENCE (Weeks 9 - 12)                                   │
│  - AI Copilot API Port, Multilingual RAG, Safety Scorecards           │
├────────────────────────────────────────────────────────────────────────┤
│ PHASE 4: ENTERPRISE & GO-LIVE (Weeks 13 - 16)                          │
│  - FCM Push Broker, Offline Cache, App Store & Play Store Deployments  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 – Core Mobile App (Weeks 1 - 4)

* **Objective:** Establish the foundation, secure authentication flows, and implement real-time tracking on the live map.

### 1.1. Backend Preparation
* **JWT Authentication Gateways:** Build `/api/v2/auth/login` and `/api/v2/auth/refresh` endpoints in the FastAPI gateway to support stateless secure logins.
* **API Optimization:** Create a consolidated `/api/v2/mobile/dashboard` endpoint to fetch fleet statuses, active counts, and today's alert metrics in a single database request.
* **WebSocket Authentication:** Verify WebSocket `/ws/live` capability to accept Bearer tokens passed via query parameters.

### 1.2. Flutter Mobile Engineering
* **Project Bootstrap:** Initialize Google Flutter utilizing a clean architecture pattern (BLoC or Riverpod for state management).
* **Secure Storage:** Integrate `flutter_secure_storage` to handle hardware-level token caching (Keychain/Keystore).
* **Live Map Integration:** Embed open-source OpenStreetMap (via `flutter_map`) or Google Maps Flutter SDK.
* **Real-Time Trackers:** Build the Dart WebSocket listener to consume deduplicated vehicle updates from `/ws/live`, implementing smooth marker interpolation (moving markers seamlessly across coordinate shifts).

### 1.3. Verification Gates
* Successful login and token caching.
* Map renders fluid marker updates without stuttering or memory leaks over a 1-hour active tracking session.

---

## Phase 2 – Operations & Fleet Management (Weeks 5 - 8)

* **Objective:** Integrate operational management features, including driver registries, RFID sessions, and maintenance service tickets.

### 2.1. Backend Preparation
* **API Adjustments:** Verify `/api/v2/ops/drivers`, `/api/v2/ops/site-visits`, and `/api/v2/ops/service-tickets` endpoints support appropriate tenant validation.
* **Camera Uplinks:** Add a REST endpoint to accept driver profile picture uploads from mobile cameras, saving images locally or to tenant object storage.

### 2.2. Flutter Mobile Engineering
* **Driver Directory:** Build card lists showing active driver assignments, allowing CRUD operations directly in the field.
* **RFID Attendance Timeline:** Build a timeline tracker showing real-time driver logins, RFID card scanning logs, and unauthorized access alerts.
* **Geofence Operations:** Render circular geofenced zones on the map and display entry/exit logs.
* **Service Tickets:** Build form modules allowing supervisors to submit, update, and resolve maintenance service tickets from their phones.

### 2.3. Verification Gates
* Real-time driver profile updates successfully persist to the TimescaleDB.
* Geofence boundary overlays render correctly on iOS and Android devices.

---

## Phase 3 – Intelligence & Analytics (Weeks 9 - 12)

* **Objective:** Port the AI Copilot to mobile and integrate safety and efficiency scorecards.

### 3.1. Backend Preparation
* **FastAPI AI Bridge:** Port `/ai/chat` logic from Flask to the FastAPI router, authenticating queries via Bearer JWT tokens.
* **Streaming Responses:** Implement async JSON streaming for AI outputs to prevent HTTP timeouts over mobile networks.
* **Multilingual RAG:** Enhance RAG capabilities using multilingual sentence embeddings to improve TF-IDF accuracy for Arabic and Hindi RAG document queries.

### 3.2. Flutter Mobile Engineering
* **AI Copilot Chat Widget:** Design a premium glassmorphic chat interface with auto-scrolling, quick-reply pills, and support for rendering tables and markdown formatting.
* **Analytics Scorecards:** Build custom gauges and graphs representing driver safety scores, overspeed events, harsh braking, and fuel consumption trends.
* **Simplified Playbacks:** Re-implement historical route playbacks utilizing the RDP simplified history route, restricting playbacks to lightweight animations.

### 3.3. Verification Gates
* The AI Copilot responds correctly to complex multilingual queries (English, Arabic, Hindi) in under 3 seconds.
* SVG charts render fluidly without frame drops.

---

## Phase 4 – Enterprise & Go-Live (Weeks 13 - 16)

* **Objective:** Implement push notifications, establish offline resilience, and publish to the app stores.

### 4.1. Backend Preparation
* **FCM Registration Endpoint:** Build `/api/v2/notifications/register-token` to store client device tokens.
* **Notification Dispatch Worker:** Implement a Celery-backed worker in the database layer to automatically trigger FCM pushes upon overspeed, geofence breaches, or insurance expiry warnings.

### 4.2. Flutter Mobile Engineering
* **FCM Notification Handlers:** Integrate native push notification handlers for foreground, background, and terminated app states.
* **Offline Database Cache:** Integrate a local SQLite database (`sqflite` plugin) to cache recent alerts and vehicle metadata, allowing users to view recent fleet information without internet connectivity.
* **App Store Publishing:** Set up deployment pipelines on Apple App Store Connect and Google Play Console.

### 4.3. Verification Gates
* Push notifications arrive on the device within 2 seconds of a background telemetry violation.
* Offline mode functions seamlessly when internet connectivity is disabled, falling back to cached SQLite records.
