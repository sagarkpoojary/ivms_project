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

from core.logging import setup_logging
setup_logging(level=logging.INFO)
logger = logging.getLogger("IngestionMain")

class IngestionServer:
    def __init__(self):
        self.port = int(os.getenv("INGESTION_PORT", 5027))
        self.db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        self.registry = SessionRegistry()
        self.db_queue = asyncio.Queue(maxsize=10000)
        self.db_handler = DBHandler(self.db_url)
        self.is_running = True
        
        # Partitioned worker pool configuration (Strict Per-Device Sequencing)
        self.num_partitions = 5
        self.partition_queues = [asyncio.Queue(maxsize=2000) for _ in range(self.num_partitions)]

    async def queue_router(self):
        """Reads from main db_queue and routes packets consistently to partition queues by IMEI."""
        logger.info("Queue router started.")
        while self.is_running:
            try:
                item = await self.db_queue.get()
                metrics.DB_QUEUE_SIZE.set(self.db_queue.qsize())
                
                if item.get('type') == 'alert':
                    # Consistently route all system alerts to partition 0
                    await self.partition_queues[0].put(item)
                else:
                    imei = item.get('imei')
                    if imei:
                        partition_idx = hash(imei) % self.num_partitions
                        await self.partition_queues[partition_idx].put(item)
                    else:
                        await self.partition_queues[0].put(item)
                        
                self.db_queue.task_done()
            except Exception as e:
                logger.error(f"Queue Router Error: {e}")
                await asyncio.sleep(0.1)

    async def db_worker(self, worker_id):
        """
        Processes telemetry records from a dedicated partition queue.
        Implements sequential processing, batching, exponential retry, and DLQ.
        """
        logger.info(f"Database worker {worker_id} started.")
        # Create a dedicated connection pool handler for this worker to maximize database connection utilization
        db_handler = DBHandler(self.db_url)
        await db_handler.connect()
        
        queue = self.partition_queues[worker_id]
        
        while self.is_running:
            try:
                item = await queue.get()
                
                if item.get('type') == 'alert':
                    await db_handler.log_alert(
                        item.get('severity', 'INFO'), 
                        item.get('component', 'System'), 
                        item.get('message', ''), 
                        item.get('imei')
                    )
                    queue.task_done()
                    continue

                imei = item['imei']
                records = item['records']
                raw_payload = item.get('raw')
                
                # Retry policy with exponential backoff
                max_retries = 3
                success = False
                db_err = None
                
                for attempt in range(1, max_retries + 1):
                    try:
                        start_time = time.time()
                        await db_handler.save_telemetry(imei, records)
                        metrics.DB_WRITE_LATENCY.observe(time.time() - start_time)
                        
                        if records:
                            lag = time.time() - records[-1]['timestamp'].timestamp()
                            metrics.TELEMETRY_LAG.observe(lag)
                        
                        success = True
                        break
                    except Exception as err:
                        db_err = err
                        logger.error(f"Worker {worker_id} (Attempt {attempt}/{max_retries}) - Failed to save telemetry for {imei}: {err}")
                        if attempt < max_retries:
                            # Exponential backoff: 2, 4, 8 seconds
                            await asyncio.sleep(2 ** attempt)
                
                if not success:
                    # Exceeded retries: dump to Dead-Letter Queue (DLQ) file
                    logger.critical(f"Worker {worker_id} - Packet for {imei} EXCEEDED RETRIES! Routing to DLQ.")
                    await self.write_to_dlq(imei, item, str(db_err))
                
                queue.task_done()
            except Exception as e:
                logger.error(f"DB Worker {worker_id} Error: {e}")
                await asyncio.sleep(1)
                
        try:
            await db_handler.disconnect()
        except: pass

    async def write_to_dlq(self, imei, item, error_msg):
        """Dumps failed telemetry payload to local JSONL DLQ file for persistence."""
        try:
            import json
            from datetime import datetime
            dlq_entry = {
                'imei': imei,
                'timestamp': datetime.utcnow().isoformat(),
                'error': error_msg,
                'payload': {
                    'records': [
                        {
                            **r,
                            'timestamp': r['timestamp'].isoformat() if hasattr(r['timestamp'], 'isoformat') else str(r['timestamp'])
                        } for r in item.get('records', [])
                    ],
                    'raw': item.get('raw'),
                    'received_at': item.get('received_at')
                }
            }
            # Append entry to local dlq.jsonl file safely
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._append_to_dlq_file, dlq_entry)
        except Exception as e:
            logger.error(f"Failed to write to DLQ file: {e}")

    def _append_to_dlq_file(self, entry):
        import json
        with open("/app/dlq.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

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
        """Periodically checks and marks devices as offline if they exceed the dynamic timeouts."""
        ign_on_timeout = Config.IGNITION_ON_TIMEOUT_SECONDS
        ign_off_timeout = Config.IGNITION_OFF_TIMEOUT_SECONDS
        logger.info(f"Offline reconciliation worker started (dynamic timeouts | Ignition ON: {ign_on_timeout}s | Ignition OFF: {ign_off_timeout}s)")
        while self.is_running:
            try:
                count = await self.db_handler.reconcile_offline_devices(
                    ign_on_timeout,
                    ign_off_timeout
                )
                if count > 0:
                    logger.info(f"Reconciled {count} offline devices")
                
                # Check every 5 seconds for aggressive offline detection
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Offline Reconciliation Error: {e}")
                await asyncio.sleep(5)

    async def stats_logger(self):
        while self.is_running:
            metrics = self.registry.get_metrics()
            logger.info(f"STATUS: {metrics['active_devices']} active devices | Queue Size: {self.db_queue.qsize()}")
            await asyncio.sleep(60)

    async def socket_cleanup_worker(self):
        """Periodically terminates half-open and inactive device sockets."""
        logger.info("Socket cleanup worker started.")
        while self.is_running:
            try:
                # Evict sockets inactive for more than 5 minutes
                await self.registry.cleanup_dead_sockets(timeout_seconds=300)
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Socket Cleanup Worker Error: {e}")
                await asyncio.sleep(10)

    async def run(self):
        # Start Prometheus metrics server
        metrics.start_metrics_server(9090)
        logger.info("Prometheus metrics server started on port 9090")

        # Blocking cache rehydration from database on boot
        try:
            logger.info("Connecting DB Handler and executing blocking cache rehydration on boot...")
            await self.db_handler.connect()
            count = await self.db_handler.rebuild_cache_from_db()
            logger.info(f"✓ Cache rehydration complete: {count} live positions sync'd to Redis.")
        except Exception as e:
            logger.critical(f"✗ Cache rehydration FAILED on boot: {e}")

        # Start TCP Server
        server = await asyncio.start_server(self.handle_connection, '0.0.0.0', self.port)
        addr = server.sockets[0].getsockname()
        logger.info(f"Ingestion Server listening on {addr}")

        # Start background tasks
        router_task = asyncio.create_task(self.queue_router())
        worker_tasks = [asyncio.create_task(self.db_worker(i)) for i in range(self.num_partitions)]
        stats_task = asyncio.create_task(self.stats_logger())
        cache_task = asyncio.create_task(self.cache_rebuilder())
        reconciliation_task = asyncio.create_task(self.offline_reconciliation_worker())
        cleanup_task = asyncio.create_task(self.socket_cleanup_worker())

        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    server = IngestionServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
