import redis
import json
import os
from services.traccar_service import try_traccar_get

class TelemetryService:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "redis")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)

    def get_live_status(self, imei):
        """Fetch live status from Redis (new ingestion) or fallback to Traccar."""
        # 1. Try Local Redis (Direct Teltonika Ingestion)
        try:
            data = self.redis_client.get(f"live:{imei}")
            if data:
                return json.loads(data)
        except Exception:
            pass
        
        # 2. Fallback to Traccar (Legacy/Other Devices)
        # In a real system, we might cache this mapping
        try:
            r, _ = try_traccar_get("api/devices", params={"uniqueId": imei})
            if r.status_code == 200:
                devices = r.json()
                if devices:
                    device = devices[0]
                    # Fetch position
                    pos_r, _ = try_traccar_get("api/positions", params={"deviceId": device['id']})
                    if pos_r.status_code == 200:
                        positions = pos_r.json()
                        if positions:
                            return self._format_traccar_to_unified(device, positions[0])
        except:
            pass
        return None

    def get_all_live(self, allowed_imeis=None):
        """Returns unified live data for all allowed vehicles."""
        # 1. Get all from Redis
        keys = self.redis_client.keys("live:*")
        local_data = {}
        if keys:
            for key in keys:
                imei = key.split(":")[1]
                if allowed_imeis is None or imei in allowed_imeis:
                    local_data[imei] = json.loads(self.redis_client.get(key))

        # 2. Get the rest from Traccar
        # This is more complex because we need to filter
        return local_data

    def _format_traccar_to_unified(self, device, position):
        """Converts Traccar position format to our unified Teltonika-style format."""
        return {
            "imei": device.get("uniqueId"),
            "timestamp": position.get("deviceTime"),
            "latitude": position.get("latitude"),
            "longitude": position.get("longitude"),
            "speed": position.get("speed"),
            "angle": position.get("course"),
            "altitude": position.get("altitude"),
            "satellites": position.get("attributes", {}).get("sat", 0),
            "bat_v": position.get("attributes", {}).get("batteryLevel", 0) / 10.0 if "batteryLevel" in position.get("attributes", {}) else 0
        }

telemetry_service = TelemetryService()
