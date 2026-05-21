from models.database import is_valid_vehicle_record


def test_valid_vehicle_requires_real_name_and_unique_id():
    assert is_valid_vehicle_record({
        "name": "Sagar K",
        "unique_id": "864275071207909",
        "device_model": "-",
        "driver_name": "test",
    })


def test_blank_vehicle_slot_is_not_valid():
    assert not is_valid_vehicle_record({
        "name": "-",
        "unique_id": "-",
        "device_model": "-",
        "driver_name": "-",
    })


def test_missing_vehicle_identity_is_not_valid():
    assert not is_valid_vehicle_record({})
