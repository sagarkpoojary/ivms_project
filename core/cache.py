import redis.asyncio as redis
import os
import json
import logging

logger = logging.getLogger(__name__)

class LiveCache:
    """
    Redis-based cache for real-time vehicle status and session management.
    """
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "redis")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.client = None

    async def connect(self):
        if not self.client:
            self.client = await redis.from_url(f"redis://{self.host}:{self.port}")
            self.redis = self.client # Alias
            logger.info("Connected to Redis")

    async def update_status(self, imei, status_data):
        """Updates the live status of a vehicle."""
        await self.connect()
        key = f"live:{imei}"
        await self.client.set(key, json.dumps(status_data))
        # Publish to a channel for real-time websocket updates
        await self.client.publish("live_updates", json.dumps(status_data))

    async def get_status(self, imei):
        await self.connect()
        data = await self.client.get(f"live:{imei}")
        return json.loads(data) if data else None

    async def get_all_live(self):
        await self.connect()
        keys = await self.client.keys("live:*")
        if not keys: return []
        
        pipe = self.client.pipeline()
        for key in keys:
            pipe.get(key)
        results = await pipe.execute()
        
        return [json.loads(r) for r in results if r]

    async def disconnect(self):
        if self.client:
            await self.client.close()
