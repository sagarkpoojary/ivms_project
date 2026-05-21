import logging
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class MotionHysteresisEngine:
    SPEED_START = 5.0
    DURATION_START = 10.0  # seconds
    SPEED_STOP = 2.0
    DURATION_STOP = 30.0   # seconds

    def __init__(self, cache_client):
        self.cache = cache_client

    async def get_state(self, imei) -> dict:
        """Fetches the active motion state cache from Redis with error resiliency fallback."""
        key = f"motion_state:{imei}"
        try:
            raw = await self.cache.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Redis connection failure in hysteresis get_state for {imei}: {e}")
        return {
            "state": "idle",
            "pending_state": None,
            "pending_since": None
        }

    async def save_state(self, imei, state_dict):
        """Saves the motion state cache to Redis with error resiliency fallback."""
        key = f"motion_state:{imei}"
        try:
            await self.cache.set(key, json.dumps(state_dict))
        except Exception as e:
            logger.warning(f"Redis connection failure in hysteresis save_state for {imei}: {e}")

    async def evaluate_state(self, imei, speed, ignition, timestamp) -> str:
        """
        Evaluates and transitions the vehicle's status based on speed, ignition, and duration.
        Returns the consolidated state: 'moving', 'idle', 'ignition_off', or 'offline'.
        """
        # Ensure timestamp is datetime
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        def to_utc_naive(dt):
            if dt is None:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.replace(tzinfo=None)
        
        # 1. Ignition is OFF: Instant transition to ignition_off, bypass all hysteresis
        if not ignition:
            state_dict = {
                "state": "ignition_off",
                "pending_state": None,
                "pending_since": None
            }
            await self.save_state(imei, state_dict)
            return "ignition_off"

        # 2. Ignition is ON: Run Hysteresis state machine
        state_data = await self.get_state(imei)
        current_state = state_data.get("state", "idle")
        pending_state = state_data.get("pending_state")
        pending_since_str = state_data.get("pending_since")
        
        pending_since = None
        if pending_since_str:
            try:
                pending_since = to_utc_naive(datetime.fromisoformat(pending_since_str))
            except Exception:
                pass

        new_state = current_state
        current_time = to_utc_naive(timestamp)

        # Rule A: Speed > 5 km/h -> Intending to transition to 'moving'
        if speed > self.SPEED_START:
            if current_state == "moving":
                # Already moving: Reset pending state
                pending_state = None
                pending_since = None
            else:
                # Transitioning to moving
                if pending_state == "moving_pending" and pending_since:
                    duration = (current_time - pending_since).total_seconds()
                    if duration >= self.DURATION_START:
                        new_state = "moving"
                        pending_state = None
                        pending_since = None
                        logger.info(f"Hysteresis [Transition]: {imei} transitioned from {current_state} to MOVING (sustained {speed} km/h for {duration:.1f}s)")
                else:
                    pending_state = "moving_pending"
                    pending_since = current_time

        # Rule B: Speed < 2 km/h -> Intending to transition to 'idle'
        elif speed < self.SPEED_STOP:
            if current_state == "idle" or current_state == "ignition_off":
                # Already idle or engine was off: Reset pending state
                pending_state = None
                pending_since = None
                new_state = "idle" # If engine is ON and speed is low, must be idle
            else:
                # Transitioning to idle
                if pending_state == "stopped_pending" and pending_since:
                    duration = (current_time - pending_since).total_seconds()
                    if duration >= self.DURATION_STOP:
                        new_state = "idle"
                        pending_state = None
                        pending_since = None
                        logger.info(f"Hysteresis [Transition]: {imei} transitioned from {current_state} to IDLE (sustained standstill for {duration:.1f}s)")
                else:
                    pending_state = "stopped_pending"
                    pending_since = current_time

        # Rule C: In the speed buffer zone [2.0, 5.0] km/h
        else:
            # Maintain previous pending state or current state
            pass

        # Update motion state cache
        updated_state = {
            "state": new_state,
            "pending_state": pending_state,
            "pending_since": pending_since.isoformat() if pending_since else None
        }
        await self.save_state(imei, updated_state)
        
        return new_state
