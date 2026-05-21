import asyncio
import logging
from datetime import datetime, timedelta, timezone
from ingestion.filters import TelemetryFilterPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestFilterPipeline")

def test_pipeline():
    pipeline = TelemetryFilterPipeline()
    imei = "864275071228707"
    server_now = datetime.now(timezone.utc)
    
    # 1. Base Valid Record
    valid_record = {
        'timestamp': server_now,
        'longitude': 58.3829,
        'latitude': 23.5880,
        'satellites': 10,
        'speed': 50,
    }
    
    # 2. Test Invalid Coordinate (0,0)
    record_invalid_coords = {
        **valid_record,
        'longitude': 0.0,
        'latitude': 0.0,
    }
    res = pipeline.filter_records(imei, [record_invalid_coords])
    assert len(res) == 0, "CoordinateFilter failed to reject 0,0!"
    logger.info("Success: CoordinateFilter successfully rejected 0,0 coordinates.")
    
    # 3. Test Impossible Speed
    record_high_speed = {
        **valid_record,
        'speed': 250, # Config MAX_SPEED_THRESHOLD is 180
    }
    res = pipeline.filter_records(imei, [record_high_speed])
    assert len(res) == 0, "SpeedFilter failed to reject speed of 250 km/h!"
    logger.info("Success: SpeedFilter successfully rejected impossible speed of 250 km/h.")
    
    # 4. Test Time Jump (Future)
    record_future_time = {
        **valid_record,
        'timestamp': server_now + timedelta(hours=2),
    }
    res = pipeline.filter_records(imei, [record_future_time])
    assert len(res) == 0, "TimeJumpFilter failed to reject future timestamp!"
    logger.info("Success: TimeJumpFilter successfully rejected future timestamp.")
    
    # 5. Test Time Drift (Past)
    from config import Config
    max_past_days = getattr(Config, 'MAX_PAST_DAYS', 30)
    record_ancient_time = {
        **valid_record,
        'timestamp': server_now - timedelta(days=max_past_days + 10),
    }
    res = pipeline.filter_records(imei, [record_ancient_time])
    assert len(res) == 0, "TimeJumpFilter failed to reject ancient timestamp!"
    logger.info("Success: TimeJumpFilter successfully rejected ancient timestamp.")

    # 6. Test Duplicate Record
    res = pipeline.filter_records(imei, [valid_record, valid_record])
    assert len(res) == 1, f"DuplicateFilter failed! Got {len(res)} records, expected 1."
    logger.info("Success: DuplicateFilter successfully pruned duplicate packets.")

    # 7. Test GPS Drift suppression while parked
    # Speed is 0, satellites = 2 (low precision), tiny coordinate jump (0.0001 deg)
    parked_base = {
        'timestamp': server_now,
        'longitude': 58.3829,
        'latitude': 23.5880,
        'satellites': 2,
        'speed': 0,
    }
    parked_drift = {
        'timestamp': server_now + timedelta(seconds=10),
        'longitude': 58.3830, # slightly drifted
        'latitude': 23.5881,
        'satellites': 2,
        'speed': 0,
    }
    res = pipeline.filter_records(imei, [parked_base, parked_drift], last_record=None)
    assert len(res) == 1, f"GpsDriftFilter failed to suppress coordinate drift! Got {len(res)}, expected 1."
    logger.info("Success: GpsDriftFilter successfully suppressed small coordinate drift when parked and satellites were low.")

    logger.info("\n=== All FilterHandler Pipeline rules verified successfully! Phase 2 PASSED! ===")

if __name__ == "__main__":
    test_pipeline()
