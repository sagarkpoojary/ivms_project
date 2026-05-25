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

                if item.get('type') == 'disconnect':
                    imei = item['imei']
                    try:
                        await db_handler.mark_device_offline(imei)
                    except Exception as err:
                        logger.error(f"Worker {worker_id} - Failed to mark device {imei} offline: {err}")
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
        logger.info("Stats logger task started.")
        db_handler = DBHandler(self.db_url)
        await db_handler.connect()
        
        while self.is_running:
            try:
                active_imeis = self.registry.list_active_imeis()
                
                # Count production vs testing active connections from database
                prod_count = 0
                test_count = 0
                
                if active_imeis:
                    async with db_handler.pool.acquire() as conn:
                        rows = await conn.fetch("""
                            SELECT telemetry_environment, COUNT(*) as cnt 
                            FROM vehicles 
                            WHERE unique_id = ANY($1)
                            GROUP BY telemetry_environment
                        """, active_imeis)
                        for r in rows:
                            if r['telemetry_environment'] == 'production':
                                prod_count = r['cnt']
                            elif r['telemetry_environment'] in ['simulated', 'testing']:
                                test_count += r['cnt']
                
                metrics.ACTIVE_PRODUCTION_DEVICES.set(prod_count)
                metrics.ACTIVE_TESTING_DEVICES.set(test_count)
                
                logger.info(
                    f"STATUS: {len(active_imeis)} active devices (Production: {prod_count}, Test/Simulated: {test_count}) "
                    f"| Queue Size: {self.db_queue.qsize()}"
                )
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Stats Logger Error: {e}")
                await asyncio.sleep(60)
                
        try:
            await db_handler.disconnect()
        except: pass

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

    async def reconciliation_watchdog(self):
        """
        Watchdog task that runs every 5 minutes to detect and heal discrepancies
        between the telemetry table and the live_vehicle_status table.
        """
        logger.info("Reconciliation watchdog task started.")
        db_handler = DBHandler(self.db_url)
        await db_handler.connect()
        
        while self.is_running:
            try:
                async with db_handler.pool.acquire() as conn:
                    import json
                    discrepant_vehicles = await conn.fetch("""
                        SELECT 
                            v.unique_id as imei,
                            t.id as telemetry_id,
                            t.timestamp,
                            t.longitude,
                            t.latitude,
                            t.speed,
                            t.io_elements
                        FROM vehicles v
                        JOIN LATERAL (
                            SELECT id, timestamp, longitude, latitude, speed, io_elements 
                            FROM telemetry 
                            WHERE imei = v.unique_id 
                            ORDER BY timestamp DESC 
                            LIMIT 1
                        ) t ON TRUE
                        LEFT JOIN live_vehicle_status ls ON v.unique_id = ls.imei
                        WHERE v.status = 'active' AND (
                            ls.last_timestamp IS NULL 
                            OR t.timestamp > ls.last_timestamp
                        )
                    """)
                    
                    if discrepant_vehicles:
                        logger.warning(f"[WATCHDOG] Found {len(discrepant_vehicles)} vehicles with reconciliation discrepancies! Healing...")
                        for v in discrepant_vehicles:
                            imei = v['imei']
                            t_id = v['telemetry_id']
                            ts = v['timestamp']
                            lon = v['longitude']
                            lat = v['latitude']
                            speed = v['speed'] or 0.0
                            io = json.loads(v['io_elements']) if isinstance(v['io_elements'], str) else v['io_elements']
                            
                            ignition = str(io.get(239, io.get(1, '0'))) == '1'
                            movement = str(io.get(240, '0')) == '1'
                            gsm = int(io.get(21, 0))
                            ext_v = float(io.get(66, 0)) / 1000.0
                            bat_v = float(io.get(67, 0)) / 1000.0
                            rfid = str(io.get(78, ''))
                            
                            # Parse true fuel
                            can_fuel_pct = float(io.get(84)) if io.get(84) is not None else None
                            can_fuel_consumed = float(io.get(85)) if io.get(85) is not None else None
                            analog_fuel_mv = float(io.get(9)) if io.get(9) is not None else None
                            
                            true_fuel = None
                            if can_fuel_consumed is not None:
                                true_fuel = can_fuel_consumed
                            elif can_fuel_pct is not None:
                                true_fuel = (can_fuel_pct / 100.0) * 60.0
                            elif analog_fuel_mv is not None:
                                true_fuel = (analog_fuel_mv / 10000.0) * 60.0
                                
                            driver_id = None
                            driver_name = None
                            if rfid and rfid != '0':
                                driver = await conn.fetchrow("SELECT driver_id, name FROM drivers WHERE rfid_tag = $1", str(rfid))
                                if driver:
                                    driver_id = driver['driver_id']
                                    driver_name = driver['name']
                            
                            # Re-evaluate state
                            status = await db_handler.hysteresis.evaluate_state(imei, speed, ignition, ts)
                            
                            # Run reconciliation
                            res = await db_handler.reconciliation_engine.reconcile_position(
                                imei=imei,
                                device_id=None,
                                telemetry_id=t_id,
                                timestamp=ts,
                                longitude=lon,
                                latitude=lat,
                                speed=int(speed),
                                ignition=ignition,
                                movement=movement,
                                conn=conn,
                                gsm=gsm,
                                ext_v=ext_v,
                                bat_v=bat_v,
                                rfid=rfid,
                                driver_id=driver_id,
                                driver_name=driver_name,
                                status=status,
                                true_fuel=true_fuel
                            )
                            logger.info(f"[WATCHDOG] Healed {imei} position. Result: {res['reason']}")
                
                await asyncio.sleep(300)
            except Exception as e:
                logger.error(f"[WATCHDOG_ERROR] {e}")
                await asyncio.sleep(60)
        try:
            await db_handler.disconnect()
        except: pass

    async def supervisor_loop(self):
        """Monitors background tasks and automatically restarts them if they fail."""
        logger.info("Supervisor loop started.")
        tasks = {
            "router": (self.queue_router, []),
            "stats": (self.stats_logger, []),
            "cache": (self.cache_rebuilder, []),
            "reconciliation": (self.offline_reconciliation_worker, []),
            "cleanup": (self.socket_cleanup_worker, []),
            "watchdog": (self.reconciliation_watchdog, [])
        }
        
        for i in range(self.num_partitions):
            tasks[f"worker_{i}"] = (self.db_worker, [i])
            
        running_tasks = {}
        for name, (func, args) in tasks.items():
            running_tasks[name] = asyncio.create_task(func(*args))
            
        last_q_size = 0
        last_activity_time = time.time()
        
        while self.is_running:
            try:
                await asyncio.sleep(5)
                
                # Starvation Check
                q_size = self.db_queue.qsize()
                if q_size > 0:
                    if q_size == last_q_size:
                        if time.time() - last_activity_time > 30:
                            logger.critical(f"WARNING: Database Queue Starvation Detected! Main queue size: {q_size} has been stuck for 30s.")
                    else:
                        last_activity_time = time.time()
                else:
                    last_activity_time = time.time()
                last_q_size = q_size
                
                # Supervisor Restart Loop
                for name, task in list(running_tasks.items()):
                    if task.done():
                        try:
                            exc = task.exception()
                        except Exception as get_exc_err:
                            exc = get_exc_err
                        logger.critical(f"CRITICAL: Task {name} has DIED! Exception: {exc}. Restarting...")
                        func, args = tasks[name]
                        running_tasks[name] = asyncio.create_task(func(*args))
                        if hasattr(metrics, 'DEATHS_RECOVERED'):
                            metrics.DEATHS_RECOVERED.labels(task_name=name).inc()
            except Exception as e:
                logger.error(f"Supervisor Error: {e}")

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

        # Start background tasks via Supervisor
        supervisor_task = asyncio.create_task(self.supervisor_loop())

        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    server = IngestionServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")

