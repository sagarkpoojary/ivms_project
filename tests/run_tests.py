import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_vehicle_records import (
    test_valid_vehicle_requires_real_name_and_unique_id,
    test_blank_vehicle_slot_is_not_valid,
    test_missing_vehicle_identity_is_not_valid
)

if __name__ == "__main__":
    print("Running vehicle record unit tests...")
    try:
        test_valid_vehicle_requires_real_name_and_unique_id()
        test_blank_vehicle_slot_is_not_valid()
        test_missing_vehicle_identity_is_not_valid()
        print("✓ All vehicle record tests passed successfully!")
    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        sys.exit(1)
