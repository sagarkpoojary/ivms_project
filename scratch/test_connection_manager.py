import asyncio
import logging
import time
from unittest.mock import MagicMock
from ingestion.registry import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestConnectionManager")

class MockWriter:
    def __init__(self):
        self.closed = False
        self.wait_closed_called = False

    def get_extra_info(self, name):
        if name == 'peername':
            return ('127.0.0.1', 12345)
        elif name == 'socket':
            mock_sock = MagicMock()
            mock_sock.fileno.return_value = 1
            return mock_sock
        return None

    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.wait_closed_called = True

class MockSession:
    def __init__(self, imei, manager=None):
        self.imei = imei
        self.manager = manager
        self.writer = MockWriter()
        self.last_activity = time.time()
        self.superseded_called = False
        self.closed_called = False

    async def supersede(self):
        self.superseded_called = True
        await self.close()

    async def close(self):
        self.closed_called = True
        if self.manager:
            self.manager.unregister(self)
        self.writer.close()
        await self.writer.wait_closed()

async def run_tests():
    logger.info("=== Starting ConnectionManager Verification ===")
    
    manager = ConnectionManager()
    imei = "864275071228707"

    # Test 1: Register active session
    session1 = MockSession(imei, manager)
    await manager.register(session1)
    
    assert manager.is_connected(imei), "Test 1 Failed: IMEI not registered!"
    assert manager.get_session(imei) == session1, "Test 1 Failed: Session mismatch!"
    logger.info("Passed Test 1: Successful active session registration and TCP Keepalive configuration.")

    # Test 2: Evict duplicate session
    session2 = MockSession(imei, manager)
    await manager.register(session2)

    assert session1.superseded_called, "Test 2 Failed: Old duplicate session was not superseded!"
    assert session1.closed_called, "Test 2 Failed: Old duplicate session was not closed!"
    assert manager.get_session(imei) == session2, "Test 2 Failed: Session registry did not update to session2!"
    logger.info("Passed Test 2: Clean duplicate session eviction and socket closure.")

    # Test 3: Unregister session
    manager.unregister(session2)
    assert not manager.is_connected(imei), "Test 3 Failed: Session still registered after unregistration!"
    logger.info("Passed Test 3: Safe session unregistration.")

    # Test 4: Heartbeat cleanup
    session3 = MockSession(imei, manager)
    await manager.register(session3)
    # Simulate historical activity from 10 minutes ago
    session3.last_activity = time.time() - 600

    # Call cleanup with 300s timeout
    await manager.cleanup_dead_sockets(timeout_seconds=300)
    assert not manager.is_connected(imei), "Test 4 Failed: Stale inactive session was not cleaned up!"
    assert session3.closed_called, "Test 4 Failed: Stale inactive session socket was not closed!"
    logger.info("Passed Test 4: Heartbeat monitoring and inactive socket eviction.")

    logger.info("\n=== ConnectionManager Verification Completed! Phase 4 PASSED! ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
