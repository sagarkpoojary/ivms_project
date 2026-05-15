import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.protocol.codec8e import Codec8EParser
from ingestion.db.handler import DBHandler

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ingestion.log")
    ]
)
logger = logging.getLogger("IngestionServer")

load_dotenv()

# Configuration
TCP_PORT = int(os.getenv("INGESTION_PORT", 5027))
DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

# Global state for monitoring
active_sessions = {}

async def handle_device_connection(reader, writer):
    addr = writer.get_extra_info('peername')
    logger.info(f"New connection from {addr}")
    
    imei = None
    try:
        # Step 1: Handshake (IMEI)
        # Device sends 2 bytes length + IMEI
        data = await asyncio.wait_for(reader.read(1024), timeout=30)
        if not data:
            return
            
        imei = Codec8EParser.parse_imei(data)
        
        db = DBHandler(DB_URL)
        await db.connect()
        
        if not imei:
            logger.warning(f"Invalid IMEI packet from {addr}: {data.hex()}")
            writer.write(b'\x00') # Reject
            await writer.drain()
            return
            
        # Phase 8: Strict Whitelist Enforcement
        if not await db.is_imei_registered(imei):
            logger.warning(f"SECURITY: Unauthorized connection attempt from unregistered IMEI {imei} at {addr}")
            await db.log_alert('SECURITY', 'Authentication', f"Unauthorized connection attempt from unregistered device {imei}", imei)
            writer.write(b'\x00') # Reject
            await writer.drain()
            return
            
        logger.info(f"Device authenticated: {imei} from {addr}")
        active_sessions[imei] = {
            'addr': addr,
            'connected_at': datetime.now(),
            'last_packet': datetime.now()
        }
        
        writer.write(b'\x01') # Accept
        await writer.drain()
        
        # Step 2: Receive AVL Data
        
        while True:
            # Preamble is 4 bytes, let's read the header first or just wait for data
            data = await asyncio.wait_for(reader.read(4096), timeout=300) # 5 min timeout
            if not data:
                logger.info(f"Connection closed by device {imei}")
                break
                
            active_sessions[imei]['last_packet'] = datetime.now()
            logger.debug(f"Received data from {imei}: {len(data)} bytes")
            
            # Simple check for Teltonika packet (preamble is 00 00 00 00)
            if data[:4] == b'\x00\x00\x00\x00':
                records = Codec8EParser.decode_avl(data)
                if records:
                    # Save to DB
                    await db.save_telemetry(imei, records)
                    
                    # ACK: Return number of records as 4-byte integer
                    num_records = len(records)
                    ack_packet = num_records.to_bytes(4, byteorder='big')
                    writer.write(ack_packet)
                    await writer.drain()
                    logger.info(f"ACK sent for {num_records} records to {imei}")
                else:
                    logger.warning(f"Malformed AVL data from {imei}")
            else:
                logger.debug(f"Heartbeat or non-AVL data from {imei}")

    except asyncio.TimeoutError:
        logger.warning(f"Connection timeout for {imei if imei else addr}")
    except Exception as e:
        logger.error(f"Error handling connection from {imei if imei else addr}: {e}", exc_info=True)
    finally:
        if imei in active_sessions:
            del active_sessions[imei]
        writer.close()
        await writer.wait_closed()
        logger.info(f"Connection closed for {imei if imei else addr}")

async def main():
    # Ensure DB schema is ready (in production this might be a migration)
    # For now we assume the user has run the schema.sql or we can try to run it here
    
    server = await asyncio.start_server(handle_device_connection, '0.0.0.0', TCP_PORT)
    addr = server.sockets[0].getsockname()
    logger.info(f"Ingestion Server listening on {addr}")

    # Monitor loop
    async def monitor():
        while True:
            logger.info(f"Monitoring: {len(active_sessions)} active device sessions")
            await asyncio.sleep(60)

    async with server:
        await asyncio.gather(server.serve_forever(), monitor())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopping...")
