import redis
import json
import os
from datetime import datetime, timezone

class TelemetryService:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "redis")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)

    def get_live_status(self, imei):
        """Fetch live status from Redis with authoritative presence check (Phase 4)."""
        try:
            data = self.redis_client.get(f"live:{imei}")
            if data:
                status_dict = json.loads(data)
                # Heartbeat check
                ts_str = status_dict.get('timestamp')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        diff = (datetime.now(timezone.utc) - ts).total_seconds()
                        if diff > 900: # 15 minutes
                            status_dict['status'] = 'offline'
                    except:
                        pass
                return status_dict
        except Exception:
            pass
        return None

    def get_all_live(self, allowed_imeis=None):
        """Returns verified live data for allowed vehicles from Redis."""
        keys = self.redis_client.keys("live:*")
        results = []
        now = datetime.now(timezone.utc)
        
        if keys:
            for key in keys:
                imei = key.split(":")[1]
                if allowed_imeis is None or imei in allowed_imeis:
                    data = self.redis_client.get(key)
                    if data:
                        d = json.loads(data)
                        # Presence validation
                        ts_str = d.get('timestamp')
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                                if (now - ts).total_seconds() > 900:
                                    d['status'] = 'offline'
                            except: pass
                        results.append(d)
        return results

telemetry_service = TelemetryService()
