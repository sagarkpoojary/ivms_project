import logging
import time
import asyncio
import socket
import sys
from ingestion import metrics

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

    def unregister(self, session):
        """Safely removes a session from registry if it matches."""
        if session.imei and self._sessions.get(session.imei) == session:
            del self._sessions[session.imei]
            metrics.ACTIVE_SESSIONS.set(len(self._sessions))

    def get_session(self, imei):
        """Returns the active DeviceSession for the given IMEI."""
        return self._sessions.get(imei)

    def is_connected(self, imei) -> bool:
        """Returns True if there is an active physical TCP connection."""
        return imei in self._sessions

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
