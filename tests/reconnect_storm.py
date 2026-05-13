import asyncio
import struct
import time
import random
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ReconnectStorm")

TARGET_HOST = "localhost"
TARGET_PORT = 5027
CONCURRENT_DEVICES = 500
PACKETS_PER_DEVICE = 5

async def simulate_device(imei):
    """Simulates a single Teltonika device connection and handshake."""
    try:
        reader, writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
        
        # 1. Handshake (00 0F + IMEI)
        imei_bytes = imei.encode()
        handshake = struct.pack('>H', len(imei_bytes)) + imei_bytes
        writer.write(handshake)
        await writer.drain()
        
        ack = await reader.read(1)
        if ack != b'\x01':
            logger.error(f"Handshake failed for {imei}")
            writer.close(); await writer.wait_closed()
            return
        
        # 2. Send some mock AVL data
        for i in range(PACKETS_PER_DEVICE):
            # Mock Codec8E packet structure (simplified)
            # Preamble (4), Data Len (4), Codec (1), Rec Count (1), ...
            # For this test, we just want to stress the connection handling
            # In a real fuzzer, we'd send valid binary frames.
            await asyncio.sleep(random.uniform(0.1, 1.0))
            
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        logger.error(f"Device {imei} error: {e}")

async def run_storm():
    """Triggers a massive reconnection storm."""
    logger.info(f"Starting reconnect storm with {CONCURRENT_DEVICES} devices...")
    start_time = time.time()
    
    tasks = []
    for i in range(CONCURRENT_DEVICES):
        imei = f"358245{i:09d}"
        tasks.append(simulate_device(imei))
    
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    logger.info(f"Storm completed in {duration:.2f}s")

if __name__ == "__main__":
    asyncio.run(run_storm())
