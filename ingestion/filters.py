import logging
import time
from datetime import datetime, timezone
from config import Config
from ingestion import metrics

logger = logging.getLogger(__name__)

class BaseFilter:
    """Abstract Base Class for all Telemetry Filters."""
    def filter(self, imei, record, last_record=None) -> bool:
        raise NotImplementedError

class CoordinateFilter(BaseFilter):
    """Rejects coordinates that are exactly 0,0 or out of range, falling back to last_record if available."""
    def filter(self, imei, record, last_record=None) -> bool:
        lat = record.get('latitude', 0.0)
        lng = record.get('longitude', 0.0)
        
        is_invalid = (lat == 0.0 or lng == 0.0) or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0)
        
        if is_invalid:
            if last_record and last_record.get('latitude') and last_record.get('longitude'):
                logger.info(f"[GPS_FALLBACK] Device {imei} sent invalid GPS coordinates ({lat}, {lng}). Inherited last valid position ({last_record['latitude']}, {last_record['longitude']}).")
                record['latitude'] = last_record['latitude']
                record['longitude'] = last_record['longitude']
                record['gps_fallback'] = True
                record['gps_valid'] = False
            else:
                logger.warning(f"[GPS_NULL] Device {imei} sent invalid GPS coordinates ({lat}, {lng}) and no last_record is available. Storing as NULL coordinates.")
                record['latitude'] = None
                record['longitude'] = None
                record['gps_fallback'] = False
                record['gps_valid'] = False
                
        return True

class SpeedFilter(BaseFilter):
    """Rejects speeds that are impossible or physically unrealistic (e.g. > 180 km/h)."""
    def __init__(self, max_speed=200):
        self.max_speed = max_speed

    def filter(self, imei, record, last_record=None) -> bool:
        speed = record.get('speed', 0)
        if speed > self.max_speed:
            logger.warning(f"FILTERED [Speed]: Impossible speed {speed} km/h (max: {self.max_speed}) for {imei}")
            return False
        return True

class TimeJumpFilter(BaseFilter):
    """Rejects timestamps that drift too far in the future or the past."""
    def __init__(self, max_future_seconds=1800, max_past_days=None):
        self.max_future_seconds = max_future_seconds
        self.max_past_days = int(max_past_days if max_past_days is not None else getattr(Config, 'MAX_PAST_DAYS', 365))

    def filter(self, imei, record, last_record=None) -> bool:
        ts = record.get('timestamp')
        if not ts:
            return False
        
        server_now = datetime.now(timezone.utc)
        
        # Calculate deviation
        diff_seconds = (ts - server_now).total_seconds()
        
        # Future drift check
        if diff_seconds > self.max_future_seconds:
            logger.warning(f"FILTERED [TimeJump]: Timestamp is in the future ({ts.isoformat()} vs Server: {server_now.isoformat()}) for {imei}")
            return False
            
        # Past drift check
        if diff_seconds < - (self.max_past_days * 86400):
            logger.warning(f"FILTERED [TimeDrift]: Timestamp is too old ({ts.isoformat()}) for {imei}")
            return False
            
        return True

class DuplicateFilter(BaseFilter):
    """Rejects records that duplicate the immediately preceding record's timestamp and position."""
    def filter(self, imei, record, last_record=None) -> bool:
        if not last_record:
            return True
            
        ts = record.get('timestamp')
        last_ts = last_record.get('timestamp')
        
        if ts == last_ts:
            lat = record.get('latitude')
            lng = record.get('longitude')
            last_lat = last_record.get('latitude')
            last_lng = last_record.get('longitude')
            
            if lat == last_lat and lng == last_lng:
                logger.debug(f"FILTERED [Duplicate]: Duplicate timestamp & position for {imei}")
                return False
        return True

class GpsDriftFilter(BaseFilter):
    """Rejects small coordinate jumps when stationary to suppress GPS drift."""
    def __init__(self, min_satellites=4, drift_distance_threshold=0.0002):
        self.min_satellites = min_satellites
        self.drift_threshold = drift_distance_threshold

    def filter(self, imei, record, last_record=None) -> bool:
        if not last_record:
            return True
            
        speed = record.get('speed', 0)
        sats = record.get('satellites', 0)
        
        # If the speed is 0 and satellites are low, check if coordinates changed minutely
        if speed == 0 and sats < self.min_satellites:
            lat = record.get('latitude', 0.0)
            lng = record.get('longitude', 0.0)
            last_lat = last_record.get('latitude', 0.0)
            last_lng = last_record.get('longitude', 0.0)
            
            dist = ((lat - last_lat)**2 + (lng - last_lng)**2)**0.5
            if 0 < dist < self.drift_threshold:
                logger.warning(f"FILTERED [GpsDrift]: Small coordinate jump ({dist:.6f}) suppressed while stationary for {imei}")
                return False
        return True

class TelemetryFilterPipeline:
    def __init__(self):
        self.filters = [
            CoordinateFilter(),
            SpeedFilter(max_speed=getattr(Config, 'MAX_SPEED_THRESHOLD', 180)),
            TimeJumpFilter(max_future_seconds=1800, max_past_days=None),
            DuplicateFilter(),
            GpsDriftFilter()
        ]

    def filter_records(self, imei, records, last_record=None):
        filtered = []
        current_last = last_record
        
        for r in records:
            passed = True
            for f in self.filters:
                try:
                    if not f.filter(imei, r, current_last):
                        passed = False
                        metrics.MALFORMED_PACKETS.labels(error_type=f.__class__.__name__).inc()
                        break
                except Exception as e:
                    logger.error(f"Filter error in {f.__class__.__name__}: {e}")
                    
            if passed:
                filtered.append(r)
                current_last = r
                
        return filtered
