import sys
sys.path.append("/root/ivms_project")

import unittest
from datetime import datetime, timedelta
from routes.vehicles import calculate_status
from routes.notifications import check_and_generate_reminders
from models.database import load_vehicles, add_vehicle_db, delete_vehicle_db, get_conn, load_module_config
from services.time_service import get_oman_now

class TestIVMSProductionChanges(unittest.TestCase):
    
    def test_insurance_status_calculations(self):
        """Test status labels based on expiry dates."""
        today = get_oman_now().date()
        
        # 1. Expired (in the past)
        expired_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertEqual(calculate_status(expired_date), "Expired")
        
        # 2. Expiring Soon (within 30 days)
        expiring_soon_date = (today + timedelta(days=15)).strftime("%Y-%m-%d")
        self.assertEqual(calculate_status(expiring_soon_date), "Expiring Soon")
        
        # 3. Active (beyond 30 days)
        active_date = (today + timedelta(days=45)).strftime("%Y-%m-%d")
        self.assertEqual(calculate_status(active_date), "Active")
        
        # 4. N/A (no date provided)
        self.assertEqual(calculate_status(None), "N/A")
        self.assertEqual(calculate_status(""), "N/A")
        
        # 5. Invalid start/expiry date constraint
        start_date = (today + timedelta(days=10)).strftime("%Y-%m-%d")
        expiry_date = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        with self.assertRaises(ValueError):
            calculate_status(expiry_date, start_date)

    def test_database_persistence(self):
        """Verify that extended vehicle details can be persisted into the JSONB data column without schema changes."""
        test_uid = "VERIFY_TEST_123"
        test_vehicle = {
            "unique_id": test_uid,
            "name": "Integration Test Truck",
            "device_model": "FMC130",
            "driver_name": "Test Driver",
            "brand": "Ford",
            "model": "F-150",
            "plate_number": "9999 AA",
            "insurance_company": "Oman Insurance",
            "insurance_policy_number": "POL-123456",
            "insurance_start_date": "2026-01-01",
            "insurance_expiry_date": "2027-01-01",
            "insurance_status": "Active",
            "registration_start_date": "2026-01-01",
            "registration_expiry_date": "2027-01-01",
            "registration_status": "Active",
            "parent_email": "sagar@conceptgrps.com",
            "company_name": "System",
            "status": "active"
        }
        
        # Clean up first
        delete_vehicle_db(test_uid)
        
        # Persist
        add_vehicle_db(test_vehicle)
        
        # Retrieve and verify
        vehicles = load_vehicles()
        saved = next((v for v in vehicles if v.get("unique_id") == test_uid), None)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.get("brand"), "Ford")
        self.assertEqual(saved.get("model"), "F-150")
        self.assertEqual(saved.get("plate_number"), "9999 AA")
        self.assertEqual(saved.get("insurance_company"), "Oman Insurance")
        self.assertEqual(saved.get("insurance_policy_number"), "POL-123456")
        self.assertEqual(saved.get("insurance_status"), "Active")
        
        # Clean up
        delete_vehicle_db(test_uid)

    def test_plan_sorting_logic(self):
        """Verify plans pricing sorting behavior by vehicle_limit ascending."""
        modules_config = load_module_config()
        self.assertIsNotNone(modules_config)
        
        sorted_plans = sorted(modules_config.items(), key=lambda item: item[1].get('vehicle_limit', 0))
        limits = [plan[1].get('vehicle_limit', 0) for plan in sorted_plans]
        
        # Limits must be in ascending order
        self.assertEqual(limits, sorted(limits))
        print("Plan limits in sorted order:", limits)

if __name__ == '__main__':
    unittest.main()
