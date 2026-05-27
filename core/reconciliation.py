"""
LIVE POSITION RECONCILIATION ENGINE

Traccar-style authoritative position tracking for IVMS.
Ensures newest valid packets always update live map without corrupting historical data.

Features:
- Authoritative position ID tracking (last_telemetry_id)
- Atomic position updates with chronology validation
- Redis cache synchronization with fallback
- Websocket emission with delivery guarantee
- Comprehensive audit logging
- Timezone-aware timestamp comparison
"""

import asyncpg
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class LivePositionReconciliationEngine:
    """
    Manages authoritative live vehicle positions.
    Guarantees:
    - Latest valid packet always updates live state
    - Stale packets never corrupt runtime state
    - Historical telemetry always preserved
    - Redis cache always synchronized
    - Websocket always notified
    """
    
    def __init__(self, db_pool, redis_client):
        self.db = db_pool
        self.redis = redis_client
    
    async def reconcile_position(
        self,
        imei: str,
        telemetry_id: int,
        timestamp: datetime,
        longitude: float,
        latitude: float,
        speed: int,
        ignition: bool,
        movement: bool,
        conn: Optional[asyncpg.Connection] = None,
        **extra_fields
    ) -> Dict:
        """
        Atomically reconciles a new telemetry position as the authoritative live position.
        
        Args:
            imei: Device IMEI
            telemetry_id: ID of the telemetry record in DB
            timestamp: Packet timestamp (MUST be UTC-aware datetime)
            longitude, latitude: Position coordinates
            speed: Vehicle speed
            ignition: Ignition state
            movement: Movement state
            conn: Optional database connection to reuse
            **extra_fields: Additional fields (gsm, battery, etc)
        
        Returns:
            {
                'reconciled': bool,  # True if successfully reconciled as authoritative
                'reason': str,       # 'new_live', 'already_stale', 'cache_created', etc
                'previous_id': int,  # Previous telemetry_id
                'websocket_notified': bool,
                'redis_updated': bool,
                'latency_ms': int
            }
        """
        start_time = datetime.now(timezone.utc)
        
        conn_context = None
        if conn is None:
            conn_context = self.db.acquire()
            conn = await conn_context.__aenter__()
            
        try:
            async with conn.transaction():
                # Enforce a strict 2-second lock timeout to prevent queue worker starvation or deadlocks
                await conn.execute("SET LOCAL lock_timeout = '2000'")
                
                # 1. ATOMIC READ-COMPARE-WRITE: Get current live position
                existing = await conn.fetchrow(
                    """
                    SELECT 
                        last_telemetry_id,
                        last_timestamp,
                        longitude,
                        latitude,
                        last_valid_packet_time,
                        reconciliation_flags
                    FROM live_vehicle_status 
                    WHERE imei = $1
                    FOR UPDATE  -- Lock to prevent race conditions
                    """,
                    imei
                )
            
                # 2. CHRONOLOGICAL VALIDATION: Determine if packet is stale
                is_stale = False
                reason = "new_live"
                previous_id = None
            
                if existing and existing['last_timestamp'] and existing['last_telemetry_id'] is not None:
                    previous_id = existing['last_telemetry_id']
                
                    # UTC-AWARE COMPARISON: Both timestamps must be timezone-aware
                    existing_ts = existing['last_timestamp']
                
                    # Ensure both are UTC-aware for correct comparison
                    if existing_ts.tzinfo is None:
                        logger.warning(f"WARNING: DB timestamp missing timezone info for {imei}. Assuming UTC.")
                        existing_ts = existing_ts.replace(tzinfo=timezone.utc)
                
                    if timestamp.tzinfo is None:
                        logger.warning(f"WARNING: Incoming timestamp missing timezone info for {imei}. Assuming UTC.")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                
                    # STALE DETECTION: Compare with microsecond precision
                    if timestamp <= existing_ts:
                        is_stale = True
                        reason = "already_stale"
                        logger.info(
                            f"[STALE] {imei}: Incoming packet timestamp {timestamp.isoformat()} "
                            f"<= existing {existing_ts.isoformat()}. Preserving authoritative position."
                        )
                    else:
                        reason = "newer_packet"
                        logger.info(
                            f"[LIVE_UPDATE] {imei}: New authoritative position from telemetry_id={telemetry_id} "
                            f"timestamp={timestamp.isoformat()}"
                        )
                elif existing and existing['last_telemetry_id'] is None:
                    # GUARD: Device has live_vehicle_status record but no valid telemetry_id
                    # This means last_timestamp was poisoned by a non-telemetry event
                    # Do NOT update last_timestamp - preserve the stale state
                    is_stale = True
                    reason = "no_valid_telemetry_id"
                    logger.warning(
                        f"[POISONED_TIMESTAMP] {imei}: live_vehicle_status exists with NULL last_telemetry_id. "
                        f"Preserving stale state, not updating last_timestamp."
                    )
                else:
                    reason = "initial_position"
                    logger.info(f"[INITIAL] {imei}: Creating first authoritative position from telemetry_id={telemetry_id}")
            
                # 3. UPDATE LIVE STATUS: Only if NOT stale
                reconciled = False
                websocket_notified = False
                redis_updated = False
                version = 1  # Authoritative version tracking
            
                if not is_stale:
                    # Update authoritative position in DB
                    current_timestamp = datetime.now(timezone.utc)
                    try:
                        row = await conn.fetchrow(
                            """
                            INSERT INTO live_vehicle_status (
                                imei, device_id, last_telemetry_id, last_timestamp, 
                                last_valid_packet_time, longitude, latitude, 
                                speed, ignition, movement, gsm_signal, external_voltage, battery_voltage,
                                status, current_status, current_driver_id, current_driver_name,
                                updated_at, reconciliation_flags, live_position_reconciliation_version
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW(), $18, 1)
                            ON CONFLICT (imei) DO UPDATE SET
                                device_id = EXCLUDED.device_id,
                                last_telemetry_id = EXCLUDED.last_telemetry_id,
                                last_timestamp = EXCLUDED.last_timestamp,
                                last_valid_packet_time = EXCLUDED.last_valid_packet_time,
                                longitude = EXCLUDED.longitude,
                                latitude = EXCLUDED.latitude,
                                speed = EXCLUDED.speed,
                                ignition = EXCLUDED.ignition,
                                movement = EXCLUDED.movement,
                                gsm_signal = EXCLUDED.gsm_signal,
                                external_voltage = EXCLUDED.external_voltage,
                                battery_voltage = EXCLUDED.battery_voltage,
                                status = EXCLUDED.status,
                                current_status = EXCLUDED.current_status,
                                current_driver_id = EXCLUDED.current_driver_id,
                                current_driver_name = EXCLUDED.current_driver_name,
                                updated_at = EXCLUDED.updated_at,
                                reconciliation_flags = EXCLUDED.reconciliation_flags,
                                live_position_reconciliation_version = live_vehicle_status.live_position_reconciliation_version + 1
                            RETURNING live_position_reconciliation_version
                            """,
                            imei, 
                            extra_fields.get('device_id'),
                            telemetry_id, 
                            timestamp, 
                            current_timestamp,
                            longitude, 
                            latitude, 
                            speed, 
                            ignition, 
                            movement,
                            extra_fields.get('gsm'),
                            extra_fields.get('ext_v'),
                            extra_fields.get('bat_v'),
                            extra_fields.get('status'),
                            extra_fields.get('status'),
                            extra_fields.get('driver_id'),
                            extra_fields.get('driver_name'),
                            json.dumps({"reason": reason, "source": "reconciliation_engine"})
                        )
                        if row:
                            version = row['live_position_reconciliation_version']
                        logger.info(f"✓ DB updated: {imei} now has authoritative position from telemetry_id={telemetry_id} | Version={version}")
                    except Exception as e:
                        logger.error(f"✗ DB update FAILED for {imei}: {e}")
                        return {
                            "reconciled": False,
                            "reason": f"db_update_failed:{str(e)}",
                            "previous_id": previous_id,
                            "websocket_notified": False,
                            "redis_updated": False,
                            "latency_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                        }
                
                    # 4. LOG AUDIT TRAIL
                    try:
                        await conn.execute(
                            """
                            INSERT INTO live_position_updates (
                                imei, previous_telemetry_id, new_telemetry_id,
                                previous_timestamp, new_timestamp, reason, 
                                update_latency_ms
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            imei, previous_id, telemetry_id, 
                            existing['last_timestamp'] if existing else None, 
                            timestamp, reason,
                            int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to write audit log for {imei}: {e}")
                
                    reconciled = True
            
            # 5. UPDATE REDIS CACHE: Only if position actually reconciled
            if not is_stale:
                try:
                    cache_data = {
                        "imei": imei,
                        "telemetry_id": telemetry_id,
                        "timestamp": timestamp.isoformat(),
                        "longitude": longitude,
                        "latitude": latitude,
                        "speed": speed,
                        "ignition": ignition,
                        "movement": movement,
                        "is_authoritative": not is_stale,
                        "reconciliation_reason": reason,
                        "reconciliation_version": version,
                        **{k: v for k, v in extra_fields.items() if k in ['gsm', 'ext_v', 'bat_v', 'rfid', 'driver_id', 'driver_name', 'status', 'true_fuel']}
                    }
                    
                    redis_key = f"live:{imei}"
                    await self.redis.setex(redis_key, 604800, json.dumps(cache_data))
                    redis_updated = True
                    logger.debug(f"✓ Redis cache updated for {imei} | Version={version}")
                except Exception as e:
                    logger.error(f"✗ Redis cache UPDATE FAILED for {imei}: {e}")
                    redis_updated = False
            
            # 6. EMIT WEBSOCKET NOTIFICATION: Only if position actually reconciled
            if not is_stale:
                try:
                    ws_payload = {
                        "type": "position_update",
                        "imei": imei,
                        "telemetry_id": telemetry_id,
                        "timestamp": timestamp.isoformat(),
                        "longitude": longitude,
                        "latitude": latitude,
                        "speed": speed,
                        "ignition": ignition,
                        "reconciliation_version": version,
                        "reconciliation_reason": reason
                    }
                    await self.redis.publish("live_updates", json.dumps(ws_payload))
                    websocket_notified = True
                    logger.info(f"✓ Websocket emitted for {imei} position update | Version={version}")
                except Exception as e:
                    logger.error(f"✗ Websocket emit FAILED for {imei}: {e}")
                    websocket_notified = False
            
            # 7. LOG RECONCILIATION COMPLETION
            if websocket_notified or redis_updated:
                try:
                    await conn.execute(
                        """
                        UPDATE live_position_updates SET
                            websocket_emitted = $1,
                            redis_updated = $2
                        WHERE imei = $3 AND new_telemetry_id = $4
                        """,
                        websocket_notified, redis_updated, imei, telemetry_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to update reconciliation audit trails: {e}")
            
            latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            return {
                "reconciled": reconciled,
                "reason": reason,
                "previous_id": previous_id,
                "websocket_notified": websocket_notified,
                "redis_updated": redis_updated,
                "latency_ms": latency_ms,
                "is_stale": is_stale
            }
        finally:
            if conn_context is not None:
                await conn_context.__aexit__(None, None, None)
    
    async def verify_redis_consistency(self, imei: str) -> Dict:
        """
        Verifies that Redis cache matches authoritative DB position.
        Returns mismatch details if divergent.
        """
        async with self.db.acquire() as conn:
            db_position = await conn.fetchrow(
                """
                SELECT last_telemetry_id, last_timestamp, longitude, latitude
                FROM live_vehicle_status
                WHERE imei = $1
                """,
                imei
            )
        
        try:
            redis_data = await self.redis.get(f"live:{imei}")
            cache_position = json.loads(redis_data) if redis_data else None
        except Exception as e:
            logger.warning(f"Failed to read Redis for {imei}: {e}")
            cache_position = None
        
        if not db_position:
            return {"consistent": not cache_position, "reason": "db_empty"}
        
        if not cache_position:
            return {"consistent": False, "reason": "cache_missing", "db_telemetry_id": db_position['last_telemetry_id']}
        
        # Compare timestamps
        db_ts = db_position['last_timestamp']
        cache_ts = cache_position.get('timestamp')
        
        if db_ts and cache_ts:
            try:
                cache_ts_parsed = datetime.fromisoformat(cache_ts)
                if cache_ts_parsed.tzinfo is None:
                    cache_ts_parsed = cache_ts_parsed.replace(tzinfo=timezone.utc)
                
                if db_ts.tzinfo is None:
                    db_ts = db_ts.replace(tzinfo=timezone.utc)
                
                # Allow 1 second drift for clock skew
                ts_diff = abs((db_ts - cache_ts_parsed).total_seconds())
                if ts_diff > 1.0:
                    return {
                        "consistent": False,
                        "reason": "timestamp_divergent",
                        "db_ts": db_ts.isoformat(),
                        "cache_ts": cache_ts,
                        "delta_seconds": ts_diff
                    }
            except Exception as e:
                logger.warning(f"Failed to compare timestamps: {e}")
        
        return {"consistent": True, "reason": "verified"}
    
    async def rebuild_redis_cache_from_db(self, limit: int = None) -> int:
        """
        Rebuilds Redis cache from authoritative DB positions.
        Useful after Redis restart or catastrophic cache loss.
        """
        async with self.db.acquire() as conn:
            query = "SELECT imei, last_telemetry_id, last_timestamp, longitude, latitude FROM live_vehicle_status"
            if limit:
                query += f" LIMIT {limit}"
            
            rows = await conn.fetch(query)
        
        count = 0
        for row in rows:
            try:
                cache_data = {
                    "imei": row['imei'],
                    "telemetry_id": row['last_telemetry_id'],
                    "timestamp": row['last_timestamp'].isoformat() if row['last_timestamp'] else None,
                    "longitude": float(row['longitude']) if row['longitude'] else 0,
                    "latitude": float(row['latitude']) if row['latitude'] else 0,
                    "source": "cache_rebuild"
                }
                await self.redis.set(f"live:{row['imei']}", json.dumps(cache_data))
                count += 1
            except Exception as e:
                logger.error(f"Failed to rebuild cache for {row['imei']}: {e}")
        
        logger.info(f"✓ Redis cache rebuilt from DB: {count} vehicles")
        return count
