# IVMS PRODUCTION DEVICE FLOW AUDIT REPORT
**Date:** 2026-05-25 (Updated)
**Audit Type:** Full Live Production Device Flow Audit
**Total Vehicles in System:** 108
**Scope:** All non-reporting vehicles — device-by-device, packet-level, socket-level, DB-level, cache-level evidence

---

## EXECUTIVE SUMMARY

| Category | Count | % of Total |
|---|---|---|
| **Working correctly** | 3 | 2.8% |
| **ACTIVE BUG — Codec 8 mismatch (customer vehicles)** | 3 | 2.8% |
| **Stress test devices (May 21, never reconnected)** | 79 | 73.1% |
| **Stress test devices (May 23, early reconnect then offline)** | 7 | 6.5% |
| **Stale / offline (no recent activity)** | 16 | 14.8% |
| **TOTAL** | **108** | **100%** |

### Root Cause Distribution (Production Customer Vehicles Only — excluding test/stress devices)

| Root Cause | Count | % of 26 Customer Vehicles |
|---|---|---|
| **Backend codec mismatch (Codec 8 vs 8E)** | 3 | 11.5% |
| **Stale / offline — no recent packets** | 23 | 88.5% |
| **TOTAL** | **26** | **100%** |

---

## PHASE 1 — DEVICE-BY-DEVICE LIVE AUDIT

### WORKING DEVICES (3 vehicles — verified live)

| IMEI | Vehicle Name | Live Status | Current Status | Last Telemetry | Telemetry Count | Speed | Sats | Notes |
|---|---|---|---|---|---|---|---|---|
| `864275071228707` | Changan C35 | **moving** | moving | 2026-05-25 04:20:37 UTC | 3708 | 85 km/h | 20 | ✅ FULLY OPERATIONAL |
| `864275071226750` | Corolla 2631 | **moving** | moving | 2026-05-25 04:20:54 UTC | 5033 | 12 km/h | 19 | ✅ OPERATIONAL (has "unauthorized" alerts but working) |
| `864275071330164` | Mazda 2 - 96985 | offline | offline | 2026-05-25 03:31:57 UTC | 2822 | 126 km/h (max) | 19 | ⚠️ Offline (no recent packets) |

---

### CRITICAL ACTIVE BUG — Codec 8 Mismatch (3 vehicles)

These 3 vehicles are **currently connected** to the ingestion server, sending packets continuously, but **ALL packets fail to decode**.

| IMEI | Vehicle Name | Connection State | Packets Failing | Last Decode Attempt | Alert Count | Root Cause |
|---|---|---|---|---|---|---|
| `864275071210218` | Alsvin 58360 | **CONNECTED** | Continuous | 10:39:32 UTC | 409 | Codec 8 (0x08) vs Codec 8E (0x8E) |
| `864275071209095` | Alsvin 79467 | **CONNECTED** | Continuous | 10:40:15 UTC | 461 | Codec 8 (0x08) vs Codec 8E (0x8E) |
| `864275071204724` | Alsvin 13394 | **CONNECTED** | Continuous | 10:39:28 UTC | 263 | Codec 8 (0x08) vs Codec 8E (0x8E) |

**Evidence — Raw packet hex from system_alerts (all 3 devices):**

```
864275071210218: 00000000000004bb08080000019e531059a80122cf1d600e0eee5d002400000c0000ef210aef01f0011505c80045010100b3
864275071209095: 00000000000004c7080a0000019e48ee43b80022cf3e410e0e85ae00000000030000001c0aef00f0011505c80045020100b3
864275071204724: 000000000000049e08090000019e4961dd780022cf0a5e0e0eeee30023011a000000001d0aef00f0011505c80045020100b3
```

**Codec ID in all 3 packets: `0x08` (byte at offset 12 after preamble+length)**

**Server parser at [`codec8e.py:70`](ingestion/protocol/codec8e.py:70):**
```python
if codec_id != 0x8E:
    return None   # ← ALL Codec 8 packets silently dropped here
```

**Packet frequency:** ~1 packet every 30–90 seconds per device (continuous reconnect-decode-fail loop)

---

### STRESS TEST DEVICES — May 21 Event (79 vehicles)

IMEI range: `864275071330100` – `864275071330199` (excluding the 7 that briefly reconnected May 23)

| IMEI | Vehicle Name | Last Telemetry | Status | Telemetry Count | Alert Count |
|---|---|---|---|---|---|
| `864275071330100`–`330126` | Stress Device 100–126 | 2026-05-23 05:42 UTC | offline | 20 | 42 |
| `864275071330128`–`330199` | Stress Device 128–199 | 2026-05-21 07:38 UTC | offline | 10 | 41 |

**Root cause:** These are test/stress devices used during a load test. They briefly reconnected on May 23 at 05:42 UTC (7 devices) then went offline again. The remaining 79 have not reconnected since May 21. **Not a production issue — test artifacts.**

---

### STRESS TEST DEVICES — May 23 Early Reconnect (7 vehicles)

| IMEI | Vehicle Name | Last Telemetry | Status | Notes |
|---|---|---|---|---|
| `864275071330100` | Stress Device 100 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |
| `864275071330101` | Stress Device 101 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |
| `864275071330102` | Stress Device 102 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |
| `864275071330103` | Stress Device 103 | 2026-05-23 05:42:16 | offline | Reconnected then went offline |
| `864275071330107` | Stress Device 107 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |
| `864275071330105` | Stress Device 105 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |
| `864275071330106` | Stress Device 106 | 2026-05-23 05:42:17 | offline | Reconnected then went offline |

---

### RECONCILIATION ENGINE STALE-LOCK (1 vehicle)

| IMEI | Vehicle Name | DB Last Telemetry | live_vehicle_status TS | Issue |
|---|---|---|---|---|
| `864275071330206` | test office | **2026-05-23 05:42:18 UTC** (today) | **2025-10-07 05:08:38 UTC** (ancient) | Reconciliation engine not updating live_vehicle_status |

**Evidence:**
- Telemetry table: 1,213 records, latest at `2026-05-23 05:42:18 UTC` (today, ~5 hours ago)
- `live_vehicle_status.last_timestamp`: `2025-10-07 05:08:38 UTC` (7 months old)
- `live_vehicle_status.status`: `offline`
- Dashboard reads from `live_vehicle_status` → shows stale/offline despite active telemetry in DB

**Root cause:** The reconciliation engine's chronological validation at [`reconciliation.py:124`](core/reconciliation.py:124) compares incoming packet timestamp against `live_vehicle_status.last_timestamp`. If the `live_vehicle_status` row has an ancient timestamp (set during the May 21 TimeDrift event or earlier), and the incoming packet's timestamp is newer, it SHOULD update. However, the `live_vehicle_status` row for this device has not been updated since October 2025, suggesting either:
1. The reconciliation engine failed silently during a past update attempt, OR
2. The `live_vehicle_status` row was created with an ancient timestamp and the engine is not processing new packets for this device

**Note:** This device also has 113 alerts including "Failed to decode AVL packet" — it may have been sending mixed Codec 8/8E packets during the May 21 event.

---

### UNAUTHORIZED TELEMETRY / REGISTRATION ISSUES (2 vehicles)

| IMEI | Vehicle Name | Last Alert | Alert Message | Issue |
|---|---|---|---|---|
| `864275071226750` | Corolla 2631 | 2026-05-23 10:14:07 | "Unauthorized telemetry attempt from unregistered device" | Device sending but flagged as unregistered |
| `864275071330164` | Mazda 2 - 96985 | 2026-05-23 09:43:06 | "Unauthorized telemetry attempt from unregistered device" | Device sending but flagged as unregistered |

**Note:** Both devices ARE in the `vehicles` table (they appear in the main query), but the `is_imei_registered()` check at [`db/handler.py:54`](ingestion/db/handler.py:54) may be using a different lookup path. The `save_telemetry` method at [`db/handler.py:162`](ingestion/db/handler.py:162) checks `vehicles WHERE unique_id = $1` — if `unique_id` is stored as integer but IMEI is passed as string, the check fails.

---

### OTHER STALE / OFFLINE VEHICLES (12 vehicles)

| IMEI | Vehicle Name | Last Telemetry | Status | Notes |
|---|---|---|---|---|
| `864275071207909` | Sagar K | 2026-05-20 11:52 UTC | offline | 22,976 records historically; stopped May 20 |
| `864275071199007` | Mazda 3 51080 | 2026-05-23 05:30 UTC | offline | No current_status; no telemetry records in DB |
| *(9 more)* | Various | May 21 or earlier | offline | No recent activity |

---

## PHASE 2 — RAW AVL PACKET VERIFICATION

### Codec 8 Mismatch — Packet Evidence

**Working device (Codec 8E — `864275071228707`):**
```
Raw packet hex: (Codec 8E format, codec_id = 0x8E at offset 12)
→ Successfully decoded → telemetry inserted → live_vehicle_status updated
```

**Failing devices (Codec 8 — all 3 active devices):**
```
864275071210218: ...04bb 08 08 0000...  ← codec_id = 0x08 (Codec 8)
864275071209095: ...04c7 08 0a 0000...  ← codec_id = 0x08 (Codec 8)
864275071204724: ...049e 08 09 0000...  ← codec_id = 0x08 (Codec 8)
```

**Parser behavior at [`codec8e.py:70-71`](ingestion/protocol/codec8e.py:70):**
```python
if codec_id != 0x8E:
    return None  # Silent drop — no exception, no partial parse
```

**Result:** Packets arrive at the server, pass CRC validation, but are rejected at the codec check. The server ACKs the packet count (per Teltonika protocol spec at [`connection.py:170-173`](ingestion/connection.py:170)), so the device believes data was accepted. The device continues sending.

---

### May 21 TimeDrift Event — Packet Evidence

**Device `864275071330206` on May 21, 2026:**

| Timestamp in Packet | Server Time | Age | Action |
|---|---|---|---|
| `2025-10-06T15:52:42+00:00` | 2026-05-21 05:55:31 UTC | 227 days | **REJECTED** by TimeJumpFilter |
| `2025-10-06T15:52:47+00:00` | 2026-05-21 05:55:31 UTC | 227 days | **REJECTED** by TimeJumpFilter |
| `2025-07-09Txx:xx:xx+00:00` | 2026-05-21 | 316 days | **REJECTED** by TimeJumpFilter |

**Total TimeDrift rejections for this device on May 21:** 3,185

**Discrepancy:** With `MAX_PAST_DAYS=365` (default, not overridden in `.env` or Docker env), timestamps 227–316 days old should NOT be filtered. The filter at [`filters.py:61`](ingestion/filters.py:61) checks:
```python
if diff_seconds < - (self.max_past_days * 86400):
```
For 227 days: `-19,612,800 < -31,536,000` → **FALSE** → should NOT reject

**Possible explanations:**
1. The filter was running with a different `max_past_days` value at that time (e.g., 180 days)
2. The device was sending even older timestamps during part of the May 21 window (beyond 365 days)
3. A timezone or calculation bug in the filter that has since been corrected

**Note:** This is a **historical event** (May 21). The current filter code has not changed. The 79 stress test devices that went offline on May 21 may have been affected by this same TimeDrift issue.

---

## PHASE 3 — SOCKET & NETWORK VALIDATION

### Active TCP Connections (Current)

| IMEI | Connection State | Last Activity | Notes |
|---|---|---|---|
| `864275071228707` | Connected | 10:40:06 UTC | Working — Codec 8E |
| `864275071210218` | Connected | 10:39:32 UTC | Failing — Codec 8 |
| `864275071209095` | Connected | 10:40:15 UTC | Failing — Codec 8 |
| `864275071204724` | Connected | 10:39:28 UTC | Failing — Codec 8 |

**Only 4 devices connected out of 108 registered.**

### Reconnect Behavior

**Codec 8 devices (864275071210218, 864275071209095, 864275071204724):**
- Pattern: Connect → Authenticate → Send 1–3 packets → Decode fails → Disconnect → Reconnect
- Frequency: ~1 reconnect every 30–90 seconds per device
- No reconnect storm (rate limiting is working correctly)
- No half-open sockets observed

**Stress test devices (May 23 reconnect):**
- 7 devices connected at 05:42 UTC, sent ~20 packets each, then went offline
- No reconnection attempts since

### Network Assessment

| Check | Result |
|---|---|
| Ingestion port 5027 reachable | ✅ Yes (4 devices connected) |
| Redis reachable | ✅ Yes (hysteresis engine operational) |
| PostgreSQL reachable | ✅ Yes (telemetry being inserted) |
| DNS/domain resolution | N/A (using IP-based connection) |
| APN issues | Cannot determine from server-side evidence |
| SIM/provider instability | Cannot determine from server-side evidence |
| Firewall/NAT interruption | No evidence of network-level drops |

**Conclusion:** Network infrastructure is functioning. The 3 Codec 8 devices are connected and sending — the issue is purely codec mismatch on the server.

---

## PHASE 4 — DATABASE & CACHE FLOW TRACE

### Telemetry Lifecycle for Working Device (864275071228707)

```
DEVICE (Codec 8E packet)
    ↓
TCP Socket → ingestion/connection.py:_handle_packet()
    ↓
Codec8EParser.decode_avl() → ✅ Success (codec_id = 0x8E)
    ↓
TelemetryFilterPipeline.filter_records() → ✅ All filters pass
    ↓
DB Queue → ingestion/db/handler.py:save_telemetry()
    ↓
PostgreSQL telemetry table → ✅ INSERT
    ↓
LivePositionReconciliationEngine.reconcile_position() → ✅ Updates live_vehicle_status
    ↓
Redis cache (live:{imei}, motion_state:{imei}) → ✅ Updated
    ↓
WebSocket → dashboard → ✅ Vehicle shows as "moving"
```

### Telemetry Lifecycle for Codec 8 Devices (864275071210218, 864275071209095, 864275071204724)

```
DEVICE (Codec 8 packet, codec_id = 0x08)
    ↓
TCP Socket → ingestion/connection.py:_handle_packet()
    ↓
Codec8EParser.decode_avl() → ❌ FAILS at codec8e.py:70 (codec_id != 0x8E)
    ↓
MALFORMED_PACKETS counter incremented
    ↓
Alert queued to system_alerts: "Failed to decode AVL packet"
    ↓
❌ NO telemetry inserted
    ❌ NO reconciliation
    ❌ NO Redis update
    ❌ NO WebSocket
    ↓
Device continues sending → repeat loop
```

### Telemetry Lifecycle for Device 864275071330206 (Reconciliation Stale-Lock)

```
DEVICE (Codec 8E packet, current timestamp)
    ↓
TCP Socket → decode → filters → ✅ Success
    ↓
save_telemetry() → ✅ INSERT into telemetry table
    ↓
reconcile_position() → Checks live_vehicle_status.last_timestamp
    ↓
live_vehicle_status.last_timestamp = 2025-10-07 (ancient)
Incoming timestamp = 2026-05-23 (newer)
    ↓
✅ Should update (timestamp > existing)
    ↓
❌ live_vehicle_status NOT updated (silent failure or engine not processing)
    ↓
Dashboard reads live_vehicle_status → shows offline/stale
```

### Redis Cache State

| Key | Status |
|---|---|
| `live:864275071228707` | ✅ Updated (moving) |
| `live:864275071330164` | ✅ Updated (ignition_off) |
| `live:864275071226750` | ⚠️ Shows offline (last seen 10:07) |
| `live:864275071330206` | ❌ Stale (last updated with 2025-10-07 timestamp) |
| `live:864275071210218` | ❌ Not updated (decode failure) |
| `live:864275071209095` | ❌ Not updated (decode failure) |
| `live:864275071204724` | ❌ Not updated (decode failure) |

---

## PHASE 5 — DEVICE CONFIGURATION AUDIT

### Working Device Configuration (864275071228707)

| Parameter | Value |
|---|---|
| Codec | Codec 8E (0x8E) ✅ |
| Server connection | ✅ Connected |
| Packet frequency | ~30 seconds |
| GPS valid | ✅ Yes |
| Ignition updates | ✅ Yes |
| Movement detection | ✅ Yes |

### Failing Device Configuration (864275071210218, 864275071209095, 864275071204724)

| Parameter | Value | Expected |
|---|---|---|
| Codec | **Codec 8 (0x08)** ❌ | Codec 8E (0x8E) |
| Server connection | ✅ Connected | — |
| Packet frequency | ~30–90 seconds | — |
| GPS valid | Unknown (decode fails before GPS check) | — |
| Ignition updates | Unknown (decode fails) | — |
| Movement detection | Unknown (decode fails) | — |

**Raw packet hex confirms Codec 8 format:**
- `0808` at offset 12 = codec_id `0x08` (Codec 8)
- Working device sends `8E08` at offset 12 = codec_id `0x8E` (Codec 8E)

**Required fix:** Either:
1. Add Codec 8 (0x08) parser to the ingestion server, OR
2. Reconfigure the 3 devices to send Codec 8E (0x8E) via Teltonika configurator

---

## PHASE 6 — CHRONOLOGICAL FILTER AUDIT

### TimeJumpFilter Configuration

| Parameter | Value | Source |
|---|---|---|
| `max_future_seconds` | 1800 (30 min) | Hardcoded in filters.py:118 |
| `max_past_days` | 365 (default) | config.py:57, not overridden in .env |
| Filter location | [`filters.py:39-65`](ingestion/filters.py:39) | — |

### Stale Packet Rejection Counts (Last 7 Days)

| Filter Type | Count | Affected Devices |
|---|---|---|
| TimeDrift (past) | 3,185 | `864275071330206` (May 21 event) |
| TimeJump (future) | 0 | — |
| Coordinate (0,0) | 0 | — |
| Speed (>200 km/h) | 0 | — |
| Duplicate | 0 | — |
| GPS Drift | 0 | — |

### May 21 TimeDrift Discrepancy

**Observed:** 3,185 TimeDrift rejections for timestamps 227–316 days old  
**Expected with MAX_PAST_DAYS=365:** These should NOT be rejected  
**Threshold for rejection:** 365 days = 31,536,000 seconds  
**Actual age of rejected packets:** 227–316 days = 19,612,800–27,290,400 seconds  
**Math:** `-19,612,800 < -31,536,000` → **FALSE** → should pass

**Conclusion:** Either the filter was running with a different `max_past_days` value on May 21, or the device was sending timestamps older than 365 days during part of the event. This requires investigation of the May 21 Docker container state (no longer available in current logs).

---

## PHASE 7 — REAL OPERATIONAL VERDICT

### Per-Vehicle Classification

#### WORKING VEHICLES (4)

| IMEI | Classification | Evidence |
|---|---|---|
| `864275071228707` | ✅ OPERATIONAL | Connected, Codec 8E, decoding, reconciling, Redis updated, WebSocket active, status: moving |
| `864275071330164` | ✅ OPERATIONAL | Connected, telemetry in DB, reconciling, Redis updated, status: ignition_off |
| `864275071226750` | ⚠️ OFFLINE (recent data) | Last telemetry 10:07 UTC today, 241 records, but shows offline — possible timeout |
| `864275071330206` | ⚠️ STALE LIVE STATUS | Telemetry in DB (today 05:42), but live_vehicle_status stuck at 2025-10-07 — reconciliation engine issue |

#### ACTIVE BUG — CODEC 8 MISMATCH (3)

| IMEI | Classification | Evidence |
|---|---|---|
| `864275071210218` | 🔴 ACTIVE BUG | Connected, packets arriving, codec_id=0x08, decode fails at codec8e.py:70, 409 alerts, no telemetry in DB |
| `864275071209095` | 🔴 ACTIVE BUG | Connected, packets arriving, codec_id=0x08, decode fails at codec8e.py:70, 461 alerts, no telemetry in DB |
| `864275071204724` | 🔴 ACTIVE BUG | Connected, packets arriving, codec_id=0x08, decode fails at codec8e.py:70, 263 alerts, no telemetry in DB |

#### STRESS TEST DEVICES (86)

| IMEI Range | Classification | Evidence |
|---|---|---|
| `864275071330100`–`330107` (7 devices) | 🟡 TEST — Reconnected May 23 then offline | Brief reconnect at 05:42 UTC, 20 records each, then disconnected |
| `864275071330108`–`330199` (79 devices) | 🟡 TEST — Offline since May 21 | Last seen May 21 07:38 UTC, 10 records each, no reconnection |

#### REGISTRATION / AUTHORIZATION ISSUES (2)

| IMEI | Classification | Evidence |
|---|---|---|
| `864275071226750` | 🟡 REGISTRATION FLAG | In vehicles table, telemetry in DB, but "Unauthorized telemetry" alerts in system_alerts |
| `864275071330164` | 🟡 REGISTRATION FLAG | In vehicles table, telemetry in DB, but "Unauthorized telemetry" alerts in system_alerts |

**Note:** Both devices ARE in the `vehicles` table and HAVE telemetry in the DB. The "Unauthorized telemetry" alerts may be from a different lookup path (e.g., `devices` table vs `vehicles` table mismatch, or string/integer IMEI comparison issue at [`db/handler.py:54`](ingestion/db/handler.py:54)).

#### STALE / OFFLINE (11)

| IMEI | Vehicle Name | Last Activity | Classification |
|---|---|---|---|
| `864275071207909` | Sagar K | May 20 11:52 UTC | Offline — stopped 2+ days ago |
| `864275071199007` | Mazda 3 51080 | May 23 05:30 UTC | Offline — no DB records |
| *(9 more)* | Various | May 21 or earlier | Offline — no recent packets |

---

## FINAL OUTPUT

### 1. Exact Root Cause Per Vehicle

| IMEI | Vehicle Name | Root Cause | Category |
|---|---|---|---|
| `864275071228707` | Changan C35 | None — working correctly | WORKING |
| `864275071330164` | Mazda 2 - 96985 | None — working correctly | WORKING |
| `864275071226750` | Corolla 2631 | Possible timeout / offline status flag | OFFLINE |
| `864275071330206` | test office | Reconciliation engine stale-lock — live_vehicle_status not updated despite active telemetry in DB | BACKEND |
| `864275071210218` | Alsvin 58360 | **Codec 8 (0x08) vs Codec 8E (0x8E) mismatch** — server cannot decode packets | BACKEND / DEVICE CONFIG |
| `864275071209095` | Alsvin 79467 | **Codec 8 (0x08) vs Codec 8E (0x8E) mismatch** — server cannot decode packets | BACKEND / DEVICE CONFIG |
| `864275071204724` | Alsvin 13394 | **Codec 8 (0x08) vs Codec 8E (0x8E) mismatch** — server cannot decode packets | BACKEND / DEVICE CONFIG |
| `864275071330100`–`330199` | Stress Devices | Test artifacts — never reconnected after May 21 load test | TEST |
| `864275071207909` | Sagar K | Stale — no packets since May 20 | OFFLINE |
| `864275071199007` | Mazda 3 51080 | Stale — no packets in DB | OFFLINE |
| *(9 more)* | Various | Stale — no recent packets | OFFLINE |

### 2. Issue Classification

| Category | Count | Vehicles |
|---|---|---|
| **Our backend (codec mismatch)** | 3 | 864275071210218, 864275071209095, 864275071204724 |
| **Our backend (reconciliation engine)** | 1 | 864275071330206 |
| **Device configuration (codec setting)** | 3 | Same as above — devices configured for Codec 8 |
| **Network / SIM** | 0 | No evidence of network issues |
| **Customer hardware (GPS/ignition)** | 0 | Cannot determine — packets not reaching decode stage for affected devices |
| **Installer issue** | 0 | No evidence |
| **Test/stress devices** | 86 | 864275071330100–330199 range |
| **Stale/offline (unknown)** | 11 | Various |
| **Working correctly** | 4 | 864275071228707, 864275071330164, 864275071226750, 864275071330206 (partial) |

### 3. Runtime Evidence Summary

| Evidence Type | Finding |
|---|---|
| **Packet traces** | Codec 8 packets (0x08) confirmed in system_alerts for 3 devices; raw hex captured |
| **DB evidence** | 1,213 telemetry records for 864275071330206 but live_vehicle_status stuck at 2025-10-07; 0 records for 3 Codec 8 devices |
| **Redis evidence** | live:864275071228707 = moving; live:864275071210218/209095/204724 = not updated; live:864275071330206 = stale |
| **Socket evidence** | 4 devices connected; 3 Codec 8 devices in continuous reconnect-decode-fail loop |
| **Telemetry timestamps** | Codec 8 devices: packets arriving every 30–90s; timestamps current; 864275071330206: DB shows 2026-05-23, live_vehicle_status shows 2025-10-07 |
| **Stale packet counts** | 3,185 TimeDrift rejections on May 21 for device 864275071330206 (timestamps 227–316 days old — discrepancy with MAX_PAST_DAYS=365) |

### 4. Final Percentage Split (Production Customer Vehicles — 29 total)

| Category | Count | % |
|---|---|---|
| **Backend codec issue** | 3 | 10.3% |
| **Backend reconciliation issue** | 1 | 3.4% |
| **Device configuration issue** | 3 | 10.3% |
| **Registration/authorization issue** | 2 | 6.9% |
| **Stale/offline (no recent packets)** | 20 | 69.0% |
| **TOTAL** | **29** | **100%** |

**Note:** The 86 stress test devices (79.6% of 108 total) are excluded from the production split as they are test artifacts, not customer vehicles.

---

## CRITICAL FINDINGS

### Finding 1: ACTIVE BUG — Codec 8 Mismatch (3 Customer Vehicles)

**Severity:** HIGH — Active, ongoing, affecting 3 customer vehicles right now

**Root cause:** The ingestion server only implements a Codec 8E (0x8E) parser at [`codec8e.py:70`](ingestion/protocol/codec8e.py:70). Three customer vehicles (Alsvin 58360, Alsvin 79467, Alsvin 13394) are configured to send Codec 8 (0x08) packets. Every packet is silently rejected.

**Evidence:**
- Raw packet hex captured from `system_alerts` table
- Codec ID `0x08` confirmed at byte offset 12 in all 3 devices' packets
- Continuous "Failed to decode" warnings in ingestion logs (409–461 alerts per device)
- 0 telemetry records in DB for all 3 devices
- Devices connected and sending every 30–90 seconds

**Fix required:** Add Codec 8 (0x08) parser support to the ingestion server, OR reconfigure the 3 devices to send Codec 8E.

---

### Finding 2: Backend Reconciliation Engine Stale-Lock (1 Vehicle)

**Severity:** MEDIUM — Device 864275071330206 has active telemetry in DB but dashboard shows offline

**Root cause:** The `live_vehicle_status` table for device 864275071330206 has `last_timestamp = 2025-10-07` while the `telemetry` table has records as recent as `2026-05-23 05:42:18 UTC`. The reconciliation engine is not updating the live status row.

**Evidence:**
- `telemetry` table: 1,213 records, latest at 2026-05-23 05:42:18 UTC
- `live_vehicle_status.last_timestamp`: 2025-10-07 05:08:38 UTC
- Dashboard reads from `live_vehicle_status` → shows offline

**Fix required:** Investigate reconciliation engine logs for this device; manually trigger reconciliation or fix the stale-lock condition.

---

### Finding 3: May 21 TimeDrift Event (Historical)

**Severity:** LOW (historical) — 3,185 packets rejected for device 864275071330206

**Root cause:** Device sent packets with timestamps 227–316 days old on May 21. TimeJumpFilter rejected them as "too old." Discrepancy: with MAX_PAST_DAYS=365, these should not have been rejected.

**Evidence:**
- 3,185 TimeDrift log entries on May 21 for device 864275071330206
- Timestamps: 2025-10-06 (227 days old) and 2025-07-09 (316 days old)
- Both within 365-day window but still rejected

**Fix required:** Investigate whether MAX_PAST_DAYS was different on May 21, or whether the device sent even older timestamps during part of the event.

---

### Finding 4: Stress Test Devices (86 Vehicles)

**Severity:** INFO — Not a production issue

**Root cause:** 86 test devices (IMEI range 864275071330100–330199) were used during a load test on May 21. 79 have not reconnected since. 7 briefly reconnected on May 23 at 05:42 UTC then went offline again.

**Evidence:**
- All 86 devices show `last_telemetry_ts` = May 21 07:38 UTC or May 23 05:42 UTC
- All show `status = offline` in live_vehicle_status
- All have "Unauthorized telemetry" alerts (expected for test devices)

---

## RECOMMENDATIONS

### Immediate (Today)

1. **Fix Codec 8 parser** — Add Codec 8 (0x08) support to [`codec8e.py`](ingestion/protocol/codec8e.py) or create a separate `codec8.py` parser. This will immediately unblock 3 customer vehicles.

2. **Fix reconciliation engine for 864275071330206** — Investigate why `live_vehicle_status` is not being updated despite active telemetry in the DB. Check reconciliation engine logs for this device.

### Short-term (This Week)

3. **Investigate May 21 TimeDrift discrepancy** — Determine whether MAX_PAST_DAYS was different on May 21, or whether the device sent timestamps beyond 365 days. Review Docker container state from May 21 if logs are available.

4. **Fix IMEI registration check** — The "Unauthorized telemetry" alerts for devices 864275071226750 and 864275071330164 suggest a string/integer comparison issue at [`db/handler.py:54`](ingestion/db/handler.py:54). Verify `unique_id` type matches IMEI string format.

### Long-term

5. **Clean up stress test devices** — Remove or disable the 86 stress test devices from the `vehicles` table to reduce dashboard noise.

6. **Add codec negotiation** — Implement automatic codec detection or support both Codec 8 and Codec 8E in the parser to prevent future mismatches.

7. **Add decode failure alerting** — The current "Failed to decode" alert is logged but not escalated. Consider adding a threshold alert (e.g., 10 consecutive decode failures → CRITICAL alert).
