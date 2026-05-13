import logging
import time
import asyncio
from ingestion import metrics

logger = logging.getLogger(__name__)

class SessionRegistry:
    def __init__(self):
        self._sessions = {} # imei -> session object
        self._stats = {
            'total_connections': 0,
            'malformed_packets': 0,
            'total_records_ingested': 0
        }

    def register(self, session):
        if session.imei:
            # Handle existing session (kill old one)
            old_session = self._sessions.get(session.imei)
            if old_session and old_session != session:
                logger.warning(f"Duplicate connection for {session.imei}. Killing old session.")
                # We schedule the old session for closure
                asyncio.create_task(old_session.supersede())
            
            self._sessions[session.imei] = session
            self._stats['total_connections'] += 1
            metrics.ACTIVE_SESSIONS.set(len(self._sessions))

    def unregister(self, session):
        if session.imei and self._sessions.get(session.imei) == session:
            del self._sessions[session.imei]
            metrics.ACTIVE_SESSIONS.set(len(self._sessions))

    def get_session(self, imei):
        return self._sessions.get(imei)

    def get_metrics(self):
        return {
            'active_devices': len(self._sessions),
            'total_connections': self._stats['total_connections'],
            'uptime': time.time()
        }
        
    def list_active_imeis(self):
        return list(self._sessions.keys())
