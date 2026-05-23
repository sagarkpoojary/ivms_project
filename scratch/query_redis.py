import asyncio
import redis.asyncio as redis
import os
import json
from dotenv import load_dotenv

async def query():
    load_dotenv()
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    print(f"Connecting to Redis at {host}:{port}...")
    client = redis.from_url(f"redis://{host}:{port}", decode_responses=True)
    
    keys = await client.keys("live:*")
    print(f"--- Redis keys count: {len(keys)} ---")
    
    for key in keys[:50]: # Print first 50
        val = await client.get(key)
        print(f"{key}: {val}")
        
    print(f"\n--- Checking motion_state keys ---")
    m_keys = await client.keys("motion_state:*")
    print(f"--- motion_state keys count: {len(m_keys)} ---")
    for key in m_keys[:20]:
        val = await client.get(key)
        print(f"{key}: {val}")
        
    await client.close()

if __name__ == '__main__':
    asyncio.run(query())
