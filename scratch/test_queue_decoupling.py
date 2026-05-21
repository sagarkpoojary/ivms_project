import asyncio
import logging
import os
import json
from ingestion.main import IngestionServer
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestQueueDecoupling")

async def test_queue_decoupling():
    logger.info("=== Starting Queue-Based Ingestion Decoupling Verification ===")
    
    server = IngestionServer()
    server.is_running = True
    
    # 1. Clean DLQ file if exists
    dlq_path = "/app/dlq.jsonl"
    if os.path.exists(dlq_path):
        os.remove(dlq_path)

    # 2. Test consistent hashing routing (Strict Per-Device Sequencing)
    logger.info("--- Test 1: Consistent Hashing Partition Routing ---")
    imeis = ["864275071228707", "864275071228708", "864275071228709"]
    
    # Start the router task
    router_task = asyncio.create_task(server.queue_router())
    
    # Put records for different devices in self.db_queue
    for imei in imeis:
        await server.db_queue.put({
            'imei': imei,
            'records': [{'timestamp': 1716110000, 'speed': 20}],
            'raw': 'aabbcc',
            'received_at': 1716110000
        })
        
    await asyncio.sleep(0.5) # Allow router to process
    
    # Assert each IMEI consistently goes to the correct hashed partition queue
    for imei in imeis:
        expected_idx = hash(imei) % server.num_partitions
        queue = server.partition_queues[expected_idx]
        assert queue.qsize() > 0, f"Expected IMEI {imei} to reside in partition {expected_idx}!"
        logger.info(f"Passed: IMEI {imei} successfully routed to partition {expected_idx} (queue size: {queue.qsize()})")

    # Clean queues
    for q in server.partition_queues:
        while not q.empty():
            q.get_nowait()

    # 3. Test Ingestion Worker DLQ Failover (Database Write Failures)
    logger.info("--- Test 2: Ingestion Worker Failure Failover & DLQ dumping ---")
    
    # Create a mock failed database call (simulating DB down)
    bad_db_handler = AsyncMock()
    bad_db_handler.save_telemetry.side_effect = Exception("Database connection refused!")
    bad_db_handler.connect = AsyncMock()
    bad_db_handler.disconnect = AsyncMock()
    
    # Mock DBHandler constructor inside db_worker's local scope
    from unittest.mock import patch
    with patch('ingestion.main.DBHandler', return_value=bad_db_handler):
        # Spawn database worker for partition 0
        worker_task = asyncio.create_task(server.db_worker(0))
        
        # Put bad packet in partition 0 queue
        await server.partition_queues[0].put({
            'imei': "864275071228707",
            'records': [{'timestamp': 1716110000, 'speed': 50}],
            'raw': 'deaddata',
            'received_at': 1716110000
        })
        
        # Wait for worker retries (Attempt 1, 2, 3 takes ~2s, 4s...)
        # We wait 10 seconds to allow exponential retries (2s + 4s + 8s) to exceed limits and route to DLQ
        logger.info("Waiting for database worker to exhaust all 3 retries...")
        await asyncio.sleep(11)
        
        # Stop worker
        server.is_running = False
        worker_task.cancel()
        router_task.cancel()
        
    # Check if failed packet was dumped successfully to DLQ file
    assert os.path.exists(dlq_path), "Test 2 Failed: dlq.jsonl was not created!"
    
    with open(dlq_path, 'r') as f:
        line = f.readline()
        dlq_data = json.loads(line)
        assert dlq_data['imei'] == "864275071228707", "Test 2 Failed: Incorrect IMEI in DLQ entry!"
        assert dlq_data['payload']['raw'] == 'deaddata', "Test 2 Failed: Incorrect raw payload in DLQ!"
        assert "Database connection refused!" in dlq_data['error'], "Test 2 Failed: Missing database exception detail!"
        
    logger.info("Passed Test 2: Ingestion workers successfully exhausted exponential retries and failure-logged to DLQ!")
    
    # Clean up DLQ file
    if os.path.exists(dlq_path):
        os.remove(dlq_path)

    logger.info("\n=== Queue-Based Ingestion Decoupling Verified! Phase 5 PASSED! ===")

if __name__ == "__main__":
    asyncio.run(test_queue_decoupling())
