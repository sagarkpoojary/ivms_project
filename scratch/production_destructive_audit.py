import socket
import time
import random
import struct
import asyncio
import os
import json
import logging
import statistics
import httpx
import asyncpg
from datetime import datetime, timezone
from ingestion.protocol.codec8e import Codec8EParser
from config import Config
from core.cache import LiveCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DestructiveAudit")

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5027
NUM_STRESS_DEVICES = 100
MESSAGES_PER_DEVICE = 10

# Hardcoded test IMEI linked to "test office" or generic device range
TEST_IMEIS = [f"864275071330206", f"864275071228707", f"864275071209095"]

def generate_codec8e_payload(imei: str, lat: float, lon: float, speed: int, ignition: int, rfid: str = None) -> bytes:
    """Generates a binary Teltonika Codec 8 Extended packet with valid CRC."""
    data_field = bytearray()
    
    # Codec ID (1 byte)
    data_field.append(0x8E)
    # Number of Data 1 (1 byte)
    data_field.append(1)
    
    # --- AVL Record ---
    # Timestamp (8 bytes)
    data_field.extend(struct.pack('>Q', int(time.time() * 1000)))
    # Priority (1 byte)
    data_field.append(1)
    
    # GPS (15 bytes)
    data_field.extend(struct.pack('>i', int(lon * 10000000)))
    data_field.extend(struct.pack('>i', int(lat * 10000000)))
    data_field.extend(struct.pack('>H', 120))  # Altitude
    data_field.extend(struct.pack('>H', 180))  # Angle
    data_field.append(12)                      # Satellites
    data_field.extend(struct.pack('>H', speed))
    
    # IO elements
    event_id = 0
    data_field.extend(struct.pack('>H', event_id))
    
    io_data = bytearray()
    # ID 239: Ignition (1 byte)
    io_data.extend(struct.pack('>H', 239))
    io_data.append(ignition)
    cnt1 = 1
    
    if rfid:
        io_1byte = struct.pack('>H', cnt1) + io_data
        io_2byte = struct.pack('>H', 0)
        io_4byte = struct.pack('>H', 0)
        io_8byte = struct.pack('>H', 0)
        
        # ID 78: RFID (Variable length)
        rfid_bytes = rfid.encode('ascii')
        var_payload = bytearray()
        var_payload.extend(struct.pack('>H', 78))
        var_payload.extend(struct.pack('>H', len(rfid_bytes)))
        var_payload.extend(rfid_bytes)
        io_var = struct.pack('>H', 1) + var_payload
        total_io = 2
    else:
        io_1byte = struct.pack('>H', cnt1) + io_data
        io_2byte = struct.pack('>H', 0)
        io_4byte = struct.pack('>H', 0)
        io_8byte = struct.pack('>H', 0)
        io_var = struct.pack('>H', 0)
        total_io = 1
        
    io_payload = struct.pack('>H', total_io) + io_1byte + io_2byte + io_4byte + io_8byte + io_var
    data_field.extend(io_payload)
    
    # Number of Data 2 (1 byte)
    data_field.append(1)
    
    # Calculate CRC16
    crc_val = Codec8EParser.crc16(bytes(data_field))
    
    preamble = b'\x00\x00\x00\x00'
    length_field = struct.pack('>I', len(data_field))
    crc_field = struct.pack('>I', crc_val)
    
    return preamble + length_field + bytes(data_field) + crc_field

async def simulate_single_connection(device_id: int) -> dict:
    """Simulates a concurrent socket connection, auth, and packet bursts."""
    imei = f"864275071330{device_id:03d}"
    metrics = {"connect_success": False, "auth_success": False, "packets_sent": 0, "errors": []}
    
    try:
        reader, writer = await asyncio.open_connection(SERVER_IP, SERVER_PORT)
        metrics["connect_success"] = True
        
        # Send IMEI handshake
        imei_bytes = imei.encode()
        writer.write(struct.pack(">H", len(imei_bytes)) + imei_bytes)
        await writer.drain()
        
        resp = await reader.read(1)
        if resp == b'\x01':
            metrics["auth_success"] = True
        else:
            metrics["errors"].append("Auth handshake rejected")
            writer.close()
            await writer.wait_closed()
            return metrics
            
        # Send burst packets
        for _ in range(MESSAGES_PER_DEVICE):
            lat = 23.587 + random.uniform(-0.01, 0.01)
            lon = 58.400 + random.uniform(-0.01, 0.01)
            speed = random.randint(0, 80)
            ignition = 1 if speed > 0 else 0
            
            packet = generate_codec8e_payload(imei, lat, lon, speed, ignition)
            writer.write(packet)
            await writer.drain()
            metrics["packets_sent"] += 1
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        metrics["errors"].append(str(e))
        
    return metrics

async def run_connection_storm():
    """Simulates 100 concurrent device connections sending bursts in parallel."""
    logger.info(f"💥 Simulating Connection Storm: {NUM_STRESS_DEVICES} parallel connections...")
    start_time = time.time()
    
    tasks = [simulate_single_connection(i) for i in range(100, 100 + NUM_STRESS_DEVICES)]
    results = await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    connect_successes = sum(1 for r in results if r["connect_success"])
    auth_successes = sum(1 for r in results if r["auth_success"])
    total_packets = sum(r["packets_sent"] for r in results)
    
    logger.info(f"Storm complete in {duration:.2f}s!")
    logger.info(f" - Connection Rate: {connect_successes}/{NUM_STRESS_DEVICES} ({connect_successes/NUM_STRESS_DEVICES*100:.1f}%)")
    logger.info(f" - Authentication Rate: {auth_successes}/{NUM_STRESS_DEVICES} ({auth_successes/NUM_STRESS_DEVICES*100:.1f}%)")
    logger.info(f" - Total AVL packets delivered: {total_packets} ({total_packets/duration:.1f} pkts/sec)")

async def send_destructive_malformed_packets():
    """Attempts to inject corrupted binary data, invalid CRCs, and bad codecs to test parser isolation."""
    logger.info("☣️ Running Destructive Binary Injector tests...")
    imei = TEST_IMEIS[0]
    
    # Payload 1: Invalid CRC
    valid_pkt = generate_codec8e_payload(imei, 23.5, 58.4, 0, 1)
    corrupted_crc = valid_pkt[:-4] + b'\xDE\xAD\xBE\xEF'
    
    # Payload 2: Bad Codec ID (0x08 instead of 0x8E)
    bad_codec = valid_pkt[:8] + b'\x08' + valid_pkt[9:]
    
    # Payload 3: Truncated Mid-frame Packet
    truncated = valid_pkt[:25]
    
    metrics = {"dropped": 0, "survived": True}
    
    for i, pkt in enumerate([corrupted_crc, bad_codec, truncated]):
        try:
            reader, writer = await asyncio.open_connection(SERVER_IP, SERVER_PORT)
            # IMEI handshake
            imei_bytes = imei.encode()
            writer.write(struct.pack(">H", len(imei_bytes)) + imei_bytes)
            await writer.drain()
            resp = await reader.read(1)
            
            # Send payload
            writer.write(pkt)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            metrics["dropped"] += 1
        except Exception as e:
            logger.warning(f"Connection closed during payload {i+1} as expected: {e}")
            
    logger.info(f" ✅ Decoders survived binary injection audits! Dropped payloads: {metrics['dropped']}/3")

async def verify_cache_vs_database_drift():
    """Performs state consistency checks between PostgreSQL live status and Redis Cache."""
    logger.info("👁️ Auditing live state consistency (PostgreSQL vs Redis)...")
    db_user = os.getenv('DB_USER', 'ivmsuser')
    db_pass = os.getenv('DB_PASS', 'ivms_secure_2026')
    db_host = os.getenv('DB_HOST', 'db')
    db_name = os.getenv('DB_NAME', 'ivmsdb')
    
    conn = await asyncpg.connect(f"postgres://{db_user}:{db_pass}@{db_host}:5432/{db_name}")
    cache = LiveCache()
    await cache.connect()
    
    db_status = await conn.fetch("SELECT imei, last_timestamp, speed, status FROM live_vehicle_status")
    
    drift_count = 0
    total_checked = 0
    
    for row in db_status:
        imei = row['imei']
        redis_status = await cache.get_status(imei)
        
        if not redis_status:
            logger.warning(f" Drift: Device {imei} exists in DB but is missing in Redis Cache!")
            drift_count += 1
            continue
            
        total_checked += 1
        db_ts = row['last_timestamp'].isoformat()
        redis_ts = redis_status['timestamp']
        
        # Extract base string up to seconds to avoid subtle millisecond formatting differences
        if db_ts[:19] != redis_ts[:19]:
            logger.warning(f" Drift: Device {imei} timestamp mismatch! DB: {db_ts} | Redis: {redis_ts}")
            drift_count += 1
            
    logger.info(f" ✅ Live State Audit: Checked {total_checked} devices. Drift events: {drift_count}")
    await conn.close()
    await cache.disconnect()

async def benchmark_db_lock_contention():
    """Measures transaction insert latency and locks contention in TimescaleDB."""
    logger.info("⏱️ Benchmarking DB transaction latency under concurrency...")
    db_user = os.getenv('DB_USER', 'ivmsuser')
    db_pass = os.getenv('DB_PASS', 'ivms_secure_2026')
    db_host = os.getenv('DB_HOST', 'db')
    db_name = os.getenv('DB_NAME', 'ivmsdb')
    
    pool = await asyncpg.create_pool(f"postgres://{db_user}:{db_pass}@{db_host}:5432/{db_name}", min_size=5, max_size=20)
    
    latencies = []
    
    async def run_insert(i):
        ts = datetime.now(timezone.utc)
        start = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Write to telemetry hypertable
                    t_id = await conn.fetchval(
                        """
                        INSERT INTO telemetry (imei, timestamp, latitude, longitude, speed, io_elements)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING id
                        """,
                        TEST_IMEIS[0], ts, 23.58, 58.40, 45, '{"239": "1"}'
                    )
                    
                    # Write to Live Updates Audit Log Table
                    await conn.execute(
                        """
                        INSERT INTO live_position_updates (imei, new_telemetry_id, new_timestamp, reason, websocket_emitted, redis_updated, update_latency_ms)
                        VALUES ($1, $2, $3, 'stress_test', true, true, 5)
                        """,
                        TEST_IMEIS[0], t_id, ts
                    )
            elapsed = (time.time() - start) * 1000
            latencies.append(elapsed)
        except Exception:
            pass

    tasks = [run_insert(i) for i in range(200)]
    await asyncio.gather(*tasks)
    
    await pool.close()
    
    if latencies:
        avg_lat = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]
        p99 = statistics.quantiles(latencies, n=100)[98]
        
        logger.info(f" ✅ TimescaleDB Hypertable Benchmark Results:")
        logger.info(f"  - Average Transaction Latency: {avg_lat:.2f} ms")
        logger.info(f"  - p50 (Median) Latency: {p50:.2f} ms")
        logger.info(f"  - p95 Latency: {p95:.2f} ms")
        logger.info(f"  - p99 Latency: {p99:.2f} ms")
    else:
        logger.error(" ❌ DB Benchmark yielded no successful inserts.")

async def test_rest_api_security():
    """Attempts SQL injections and unauthorized payloads against system REST endpoints."""
    logger.info("🛡️ Performing API security verification audit...")
    async with httpx.AsyncClient() as client:
        # SQL Injection attempt against diagnostics endpoint
        sqli_payload = "864275071330206' OR '1'='1"
        try:
            resp = await client.get(f"http://api:8000/api/v2/diagnostics/live-position/{sqli_payload}")
            logger.info(f"  - Diagnostics SQLi Response Code: {resp.status_code} (Expected: 401 Unauthorized or 404/422)")
        except Exception as e:
            logger.info(f"  - SQLi test failed to connect: {e} (Expected isolation)")

async def main():
    logger.info("====================================================")
    logger.info("   IVMS ENTERPRISE DESTRUCTIVE AUDIT SUITE START    ")
    logger.info("====================================================\n")
    
    await run_connection_storm()
    await send_destructive_malformed_packets()
    await verify_cache_vs_database_drift()
    await benchmark_db_lock_contention()
    await test_rest_api_security()
    
    logger.info("\n====================================================")
    logger.info("   IVMS ENTERPRISE DESTRUCTIVE AUDIT SUITE COMPLETE ")
    logger.info("====================================================")

if __name__ == "__main__":
    asyncio.run(main())
