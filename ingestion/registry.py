import logging
import time
import asyncio
import socket
import sys
import json
from ingestion import metrics
from core.cache import LiveCache

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Stateful Connection Manager for Teltonika TCP Ingestion.
    Responsible for tracking active physical TCP sockets, handling duplicate connection
    cleanup, heartbeat tracking, keepalive configurations, and dead socket cleanup.
    """
    def __init__(self):
        self._sessions = {}  # imei -> DeviceSession
        self._stats = {
            'total_connections': 0,
            'superseded_connections': 0,
            'timed_out_connections': 0
        }
        self._lock = asyncio.Lock()
        self.cache = LiveCache()

    async def register(self, session):
        """
        Registers a new active DeviceSession.
        If an existing session is present, handles duplicate session cleanup.
        """
        if not session.imei:
            return
            
        async with self._lock:
            # Duplicate connection cleanup
            old_session = self._sessions.get(session.imei)
            if old_session and old_session != session:
                logger.warning(f"Duplicate connection detected for IMEI {session.imei}. Evicting old socket.")
                self._stats['superseded_connections'] += 1
                await old_session.supersede()

            self._sessions[session.imei] = session
            self._stats['total_connections'] += 1
            metrics.ACTIVE_SESSIONS.set(len(self._sessions))
            
            # Configure TCP Keepalive on the socket for half-open socket detection
            self.enable_tcp_keepalive(session.writer)

        # Centralized cluster-wide Redis active session registry registration
        try:
            await self.cache.connect()
            session_info = {
                "imei": session.imei,
                "peername": str(session.addr),
                "connected_at": session.connected_at,
                "last_activity": session.last_activity
            }
            await self.cache.client.setex(f"active_session:{session.imei}", 600, json.dumps(session_info))
            await self.cache.client.hset("distributed_active_sessions", session.imei, json.dumps(session_info))
            logger.info(f"✓ Registered active session for IMEI {session.imei} in distributed registry.")
        except Exception as e:
            logger.warning(f"Failed to register session in Redis for IMEI {session.imei}: {e}")

    async def update_heartbeat(self, session):
        """Updates the distributed session presence heartbeat in Redis with a 10-minute sliding TTL."""
        if not session.imei:
            return
        try:
            await self.cache.connect()
            session_info = {
                "imei": session.imei,
                "peername": str(session.addr),
                "connected_at": session.connected_at,
                "last_activity": session.last_activity
            }
            await self.cache.client.setex(f"active_session:{session.imei}", 600, json.dumps(session_info))
            await self.cache.client.hset("distributed_active_sessions", session.imei, json.dumps(session_info))
        except Exception as e:
            logger.warning(f"Failed to update session heartbeat in Redis for IMEI {session.imei}: {e}")

    def unregister(self, session):
        """Safely removes a session from registry if it matches."""
        if session.imei and self._sessions.get(session.imei) == session:
            del self._sessions[session.imei]
            metrics.ACTIVE_SESSIONS.set(len(self._sessions))
            # Clean up Redis presence asynchronously to not block synchronous callers
            asyncio.create_task(self._unregister_redis(session.imei))

    async def _unregister_redis(self, imei):
        try:
            await self.cache.connect()
            await self.cache.client.delete(f"active_session:{imei}")
            await self.cache.client.hdel("distributed_active_sessions", imei)
            logger.info(f"✓ Cleaned up active session for IMEI {imei} from distributed registry.")
        except Exception as e:
            logger.warning(f"Failed to remove session from Redis for IMEI {imei}: {e}")

    def get_session(self, imei):
        """Returns the active DeviceSession for the given IMEI."""
        return self._sessions.get(imei)

    def is_connected(self, imei) -> bool:
        """Returns True if there is an active physical TCP connection."""
        return imei in self._sessions

    async def is_connected_distributed(self, imei) -> bool:
        """Checks both local physical tracking and cluster-wide Redis active session registry."""
        if imei in self._sessions:
            return True
        try:
            await self.cache.connect()
            exists = await self.cache.client.exists(f"active_session:{imei}")
            return bool(exists)
        except Exception as e:
            logger.warning(f"Failed checking distributed presence in Redis: {e}")
            return False

    def enable_tcp_keepalive(self, writer):
        """Configures OS-level TCP keepalive probes for active half-open socket cleanup."""
        try:
            sock = writer.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # Configure Linux-specific TCP options for rapid half-open termination
                if sys.platform.startswith("linux"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)   # 60s idle before probes
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # 10s interval
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)     # 3 fails max
                logger.debug("Successfully configured TCP keepalive on active socket.")
        except Exception as e:
            logger.warning(f"Failed to configure TCP keepalive: {e}")

    async def cleanup_dead_sockets(self, timeout_seconds=300):
        """
        Periodically checks all active connections and terminates any sockets that
        exceed inactivity thresholds (heartbeat monitoring) or are in a half-open state.
        Also cleans up stale distributed sessions in Redis.
        """
        now = time.time()
        to_cleanup = []
        
        async with self._lock:
            for imei, session in list(self._sessions.items()):
                # Heartbeat timeout check
                if now - session.last_activity > timeout_seconds:
                    logger.warning(f"Heartbeat timeout triggered for IMEI {imei} (No activity for {now - session.last_activity:.1f}s)")
                    to_cleanup.append((imei, session))
                else:
                    # Check if socket is half-open / writer is closed
                    try:
                        sock = session.writer.get_extra_info('socket')
                        if sock and sock.fileno() == -1:
                            logger.warning(f"Half-open/broken socket detected for IMEI {imei}")
                            to_cleanup.append((imei, session))
                    except Exception:
                        to_cleanup.append((imei, session))

        for imei, session in to_cleanup:
            self._stats['timed_out_connections'] += 1
            await session.close()

        # Clean up stale distributed active sessions in Redis
        try:
            await self.cache.connect()
            all_sessions = await self.cache.client.hgetall("distributed_active_sessions")
            for r_imei, r_data in all_sessions.items():
                r_imei_str = r_imei.decode('utf-8')
                try:
                    data = json.loads(r_data.decode('utf-8'))
                    if now - data.get('last_activity', 0) > timeout_seconds:
                        await self.cache.client.hdel("distributed_active_sessions", r_imei_str)
                        await self.cache.client.delete(f"active_session:{r_imei_str}")
                        logger.info(f"✓ Cleaned up stale distributed registry session for IMEI {r_imei_str} (inactive for > {timeout_seconds}s).")
                except Exception:
                    await self.cache.client.hdel("distributed_active_sessions", r_imei_str)
        except Exception as e:
            logger.warning(f"Failed to clean up stale distributed sessions in Redis: {e}")
            
    def get_metrics(self):
        return {
            'active_devices': len(self._sessions),
            'total_connections': self._stats['total_connections'],
            'superseded_connections': self._stats['superseded_connections'],
            'timed_out_connections': self._stats['timed_out_connections'],
            'uptime': time.time()
        }

    def list_active_imeis(self):
        return list(self._sessions.keys())

# Maintain legacy class name alias for seamless compatibility
SessionRegistry = ConnectionManager
