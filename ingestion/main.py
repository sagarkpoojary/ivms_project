import asyncio
import logging
import os
import signal
from dotenv import load_dotenv

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.connection import DeviceSession
from ingestion.registry import SessionRegistry
from ingestion.db.handler import DBHandler
from ingestion import metrics
from config import Config
import time

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("IngestionMain")

class IngestionServer:
    def __init__(self):
        self.port = int(os.getenv("INGESTION_PORT", 5027))
        self.db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        self.registry = SessionRegistry()
        self.db_queue = asyncio.Queue(maxsize=10000)
        self.db_handler = DBHandler(self.db_url)
        self.is_running = True

    async def db_worker(self):
        """Processes telemetry records from the queue and saves to DB in batches."""
        logger.info("Database worker started.")
        await self.db_handler.connect()
        
        while self.is_running:
            try:
                # Wait for data from the queue
                item = await self.db_queue.get()
                metrics.DB_QUEUE_SIZE.set(self.db_queue.qsize())
                
                if item.get('type') == 'alert':
                    await self.db_handler.log_alert(
                        item.get('severity', 'INFO'), 
                        item.get('component', 'System'), 
                        item.get('message', ''), 
                        item.get('imei')
                    )
                else:
                    imei = item['imei']
                    records = item['records']
                    
                    # Measure latency
                    start_time = time.time()
                    await self.db_handler.save_telemetry(imei, records)
                    metrics.DB_WRITE_LATENCY.observe(time.time() - start_time)
                
                self.db_queue.task_done()
            except Exception as e:
                logger.error(f"DB Worker Error: {e}")
                await asyncio.sleep(1)

    async def handle_connection(self, reader, writer):
        session = DeviceSession(reader, writer, self.db_queue, self.registry)
        await session.run()

    async def cache_rebuilder(self):
        """Periodically syncs PostgreSQL live_vehicle_status to Redis."""
        logger.info("Cache rebuilder task started.")
        while self.is_running:
            try:
                # Initial or periodic sync
                count = await self.db_handler.rebuild_cache_from_db()
                if count > 0:
                    logger.info(f"Rebuilt Redis cache for {count} vehicles from PostgreSQL")
                
                # Sync every 30 minutes to ensure consistency
                await asyncio.sleep(1800)
            except Exception as e:
                logger.error(f"Cache Rebuilder Error: {e}")
                await asyncio.sleep(60)

    async def offline_reconciliation_worker(self):
        """Periodically checks and marks devices as offline if they exceed the timeout."""
        logger.info(f"Offline reconciliation worker started (timeout: {Config.ONLINE_TIMEOUT_SECONDS}s)")
        while self.is_running:
            try:
                count = await self.db_handler.reconcile_offline_devices(Config.ONLINE_TIMEOUT_SECONDS)
                if count > 0:
                    logger.info(f"Reconciled {count} offline devices")
                
                # Check every 30 seconds
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Offline Reconciliation Error: {e}")
                await asyncio.sleep(30)

    async def stats_logger(self):
        while self.is_running:
            metrics = self.registry.get_metrics()
            logger.info(f"STATUS: {metrics['active_devices']} active devices | Queue Size: {self.db_queue.qsize()}")
            await asyncio.sleep(60)

    async def run(self):
        # Start Prometheus metrics server
        metrics.start_metrics_server(9090)
        logger.info("Prometheus metrics server started on port 9090")

        # Start TCP Server
        server = await asyncio.start_server(self.handle_connection, '0.0.0.0', self.port)
        addr = server.sockets[0].getsockname()
        logger.info(f"Ingestion Server listening on {addr}")

        # Start background tasks
        worker_task = asyncio.create_task(self.db_worker())
        stats_task = asyncio.create_task(self.stats_logger())
        cache_task = asyncio.create_task(self.cache_rebuilder())
        reconciliation_task = asyncio.create_task(self.offline_reconciliation_worker())

        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    server = IngestionServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
