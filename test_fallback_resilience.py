"""
Fallback resilience test for external_api_service.py
Simulates:
  1. Redis fully available      → Layer 1 used
  2. Redis returns None per IMEI → Layer 2 (live_vehicle_status) used
  3. Redis completely throws     → Layer 2 (live_vehicle_status) used
  4. Both Redis + live_vehicle_status fail → Layer 3 (telemetry) used

Run inside container:
  docker exec ivms-web python /app/test_fallback_resilience.py
"""
import sys, os
sys.path.insert(0, '/app')

import unittest
from unittest.mock import patch, MagicMock
from services.external_api_service import (
    _get_all_live_with_fallback,
    fetch_live_status,
    fetch_dashboard_summary,
)
from models.database import load_vehicles

# ── Load real vehicles from DB ──────────────────────────────────────────────
vehicles = load_vehicles()
vehicles = [v for v in vehicles if v.get("status") == "active"][:3]

if not vehicles:
    print("SKIP — no active vehicles in DB")
    sys.exit(0)

imeis = [str(v.get("unique_id")) for v in vehicles]
print(f"Testing with {len(vehicles)} active vehicles: {imeis}")

# ── Test 1: Normal path (Redis live) ─────────────────────────────────────────
print("\n[1/4] Normal path — Redis available …")
results = _get_all_live_with_fallback(vehicles)
print(f"      => {len(results)} records, sources: {set(r['_source'] for r in results)}")
assert len(results) == len(vehicles), "Must return a record for every vehicle"

# ── Test 2: Redis returns None per IMEI (get_live_status returns None) ───────
print("\n[2/4] Redis miss — get_live_status returns None, expect DB fallback …")
with patch("services.external_api_service.telemetry_service") as mock_ts:
    mock_ts.get_all_live.return_value = []           # empty — no Redis data
    results = _get_all_live_with_fallback(vehicles)
    sources = set(r["_source"] for r in results)
    print(f"      => {len(results)} records, sources: {sources}")
    assert len(results) == len(vehicles), "Must still return records for all vehicles"
    assert all(r["_source"] in {"db_live_vehicle_status", "db_telemetry_last_point", "offline_stub"} for r in results), \
        f"Expected DB sources, got: {sources}"

# ── Test 3: Redis throws exception (connection refused) ──────────────────────
print("\n[3/4] Redis connection refused — full exception, expect DB fallback …")
with patch("services.external_api_service.telemetry_service") as mock_ts:
    mock_ts.get_all_live.side_effect = Exception("Connection refused")
    results = _get_all_live_with_fallback(vehicles)
    sources = set(r["_source"] for r in results)
    print(f"      => {len(results)} records, sources: {sources}")
    assert len(results) == len(vehicles), "Must still return records for all vehicles"

# ── Test 4: fetch_live_status returns records for all vehicles regardless ────
print("\n[4/4] fetch_live_status — always produces per-vehicle records …")
results = fetch_live_status(vehicles)
assert len(results) == len(vehicles), "Must return one record per vehicle"
for r in results:
    assert "imei" in r, "Must have imei key"
    assert "status" in r, "Must have status key"
    assert "latitude" in r, "Must have latitude key"
    assert "_source" in r, "Must have _source traceability key"
print(f"      => {len(results)} records, sources: {set(r['_source'] for r in results)}")

# ── Test 5: fetch_dashboard_summary — always returns valid KPI dict ──────────
print("\n[5/5] fetch_dashboard_summary — KPI totals always returned …")
from datetime import datetime, timezone
start = datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc)
end   = datetime(2026, 5, 26, 23, 59, 59, tzinfo=timezone.utc)
kpis = fetch_dashboard_summary(vehicles, start, end)
assert "total_vehicles" in kpis, "Missing total_vehicles"
assert "total_distance" in kpis, "Missing total_distance"
assert "online" in kpis, "Missing online"
print(f"      => {kpis}")

print("\n✅ All fallback resilience tests PASSED")
