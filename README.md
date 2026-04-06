# IVMS (In-Vehicle Monitoring System) Project

**Version:** 2.0 (Cloud Native)
**Tech Stack:** Python (Flask), Traccar (Backend), Google Firestore (NoSQL DB), Bootstrap 5

---

## 🚀 Overview
IVMS is a professional Fleet Management System designed for B2B logistics and tracking operations. It serves as a powerful frontend application integrated with a **Traccar** GPS tracking backend.

Unlike a standard Traccar web UI, this IVMS offers:
*   **Multi-Tier Hierarchy:** Super Admin -> Main Admin -> Company Admin -> User.
*   **Subscription Management:** Control features (limits, dashboard widgets, reports) based on plans (Normal, Silver, Gold, Premium).
*   **Advanced Reporting:** Custom logic for trip merging, stop thresholds (idling vs. parked), and combined route history.
*   **PWA Support:** Installable on mobile devices with native-like feel.

---
key for postgree 
 sudo -u postgres psql << 'EOF'
CREATE USER ivmsuser WITH PASSWORD 'ivms_secure_2026';
CREATE DATABASE ivmsdb OWNER ivmsuser;
GRANT ALL PRIVILEGES ON DATABASE ivmsdb TO ivmsuser;
\q
EOF
## 🔑 Key Features
1.  **Dashboard:** Live fleet status (Online/Offline/Moving), embedded maps, and big data visualization.
2.  **Reports:**
    *   **Trips:** Detailed trip logs with custom stop threshold merging.
    *   **Stops:** Analysis of parking vs. idling duration.
    *   **Combined:** Visual route mapping overlayed with events.
3.  **User Manager:** Hierarchical User creating with limit enforcement (e.g., "Max 10 vehicles").
4.  **Notifications:** Rule engine for Overspeed, Geofence, and Ignition alerts (Web & Email).
5.  **Cloud Database:** Fully migrated to **Google Firestore** for infinite scalability.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
*   Python 3.10+
*   Google Firebase Project
*   Traccar Server (Self-hosted or Cloud)

### 2. Environment Setup
```bash
# Clone repository
git clone <your-repo-url>
cd ivms_project

# Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Install Dependencies
pip install -r requirements.txt
```

### 3. Firebase Configuration
1.  Create a project on [Firebase Console](https://console.firebase.google.com).
2.  Enable **Firestore Database** (Native Mode).
3.  Generate a **Service Account Key** (JSON) from Project Settings -> Service Accounts.
4.  Save it as `serviceAccountKey.json` in the project root.

### 4. Running the App
```bash
python3 app.py
```
Access the application at: `http://localhost:5000`

---

## 🗄️ Database Structure (Firestore)

| Collection | Doc ID | Description |
| :--- | :--- | :--- |
| **users** | `email` | User profile, role, hierarchy (parent_email), and plan details. |
| **vehicles** | `unique_id` (IMEI) | Vehicle metadata, driver info, and owner mapping. |
| **system_config** | `settings`, `plans` | Global server configs and Pricing Plan definitions. |

---

## 👥 User Roles & Hierarchy

| Role | Access Level |
| :--- | :--- |
| **Super Admin** | **God Mode.** Can manage all companies, plans, and server settings. |
| **Main Admin** | **Reseller / Large Corp.** Can create sub-admins and users. Subject to plan limits. |
| **Admin** | **Company Manager.** Can add vehicles and drivers. Only sees their own assets. |
| **User** | **Viewer.** Read-only access to assigned vehicles. |

---

## 📞 API Integration
The system communicates with Traccar via REST API.
*   **Authorization:** Session-based (Cookies) managed by `app.py`.
*   **Endpoints:** Proxies requests to Traccar for raw data (`/api/devices`, `/api/reports/*`) but allows post-processing logic in Python.

**Note:** To enable proxying and automatic admin commands, configure master Traccar admin credentials in Firestore under `system_config` → `traccar_settings` with keys `admin_email` and `admin_pass`, or set environment variables `TRACCAR_ADMIN_EMAIL` and `TRACCAR_ADMIN_PASS`. Also set `active_ip` to your Traccar host (e.g., `172.16.1.26:8082`).

## 🐞 Debugging Tips
- Use the debug endpoints to verify configuration and connectivity:
  - `GET /api/debug/traccar` — returns `traccar_host`, whether master credentials exist, and a quick login/session check (admin only).
  - `GET /api/debug/device/<uid>` — fetches raw device and position data from Traccar via the proxy.
- Check server-side logs (Flask `current_app.logger`) for detailed errors when Traccar is unreachable or auth fails.

---

## 📄 License
Private Proprietary Software.
Copyright © 2025 Concept Groups.
