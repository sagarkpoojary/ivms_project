import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class CommandEngine:
    """
    Handles queuing and dispatching commands to Teltonika devices.
    """
    def __init__(self, db_pool, redis_cache):
        self.db_pool = db_pool
        self.cache = redis_cache

    async def queue_command(self, imei, command_type, payload=None):
        """Queues a command in the database and triggers dispatch."""
        async with self.db_pool.acquire() as conn:
            device = await conn.fetchrow("SELECT id FROM devices WHERE imei = $1", imei)
            if not device:
                raise Exception(f"Device {imei} not found")

            command_id = await conn.fetchval(
                """INSERT INTO command_queue (device_id, imei, command_type, command_payload, status)
                   VALUES ($1, $2, $3, $4, 'pending') RETURNING id""",
                device['id'], imei, command_type, payload
            )
            
            # Publish to Redis to notify the ingestion worker holding this device's socket
            await self.cache.client.publish(f"device_commands:{imei}", json.dumps({
                "command_id": command_id,
                "type": command_type,
                "payload": payload
            }))
            
            return command_id

    async def mark_sent(self, command_id):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE command_queue SET status = 'sent', sent_at = NOW() WHERE id = $1",
                command_id
            )

    async def mark_acknowledged(self, command_id, response=None):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE command_queue SET status = 'acknowledged', 
                   acknowledged_at = NOW(), response_payload = $1 WHERE id = $2""",
                response, command_id
            )
