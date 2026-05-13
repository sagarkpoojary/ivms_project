import asyncio
import logging
import struct
import time
import json
from datetime import datetime
from ingestion.protocol.codec8e import Codec8EParser
from core.cache import LiveCache
from ingestion import metrics

logger = logging.getLogger(__name__)

class DeviceSession:
    """
    Handles the lifecycle and protocol state for a single Teltonika device connection.
    """
    def __init__(self, reader, writer, db_queue, registry):
        self.reader = reader
        self.writer = writer
        self.db_queue = db_queue
        self.registry = registry
        self.addr = writer.get_extra_info('peername')
        self.imei = None
        self.connected_at = time.time()
        self.last_activity = time.time()
        self.packet_count = 0
        self.buffer = bytearray()
        self.command_task = None
        self.cache = LiveCache()
        self._superseded = False
        
    async def run(self):
        try:
            # 1. IMEI Handshake
            if not await self._authenticate():
                return

            # 2. Start Command Listener Task
            self.command_task = asyncio.create_task(self._listen_for_commands())

            # 3. Continuous Data Ingestion
            while True:
                # Read header/preamble or generic data
                data = await asyncio.wait_for(self.reader.read(4096), timeout=300)
                if not data:
                    break
                
                self.buffer.extend(data)
                self.last_activity = time.time()
                
                # Process buffer (may contain multiple packets or partial packets)
                await self._process_buffer()

        except asyncio.TimeoutError:
            logger.warning(f"Session timeout for {self.imei or self.addr}")
        except Exception as e:
            logger.error(f"Error in session {self.imei or self.addr}: {e}", exc_info=True)
        finally:
            await self.close()

    async def _authenticate(self):
        """Validates IMEI and sends handshake ACK."""
        try:
            data = await asyncio.wait_for(self.reader.read(1024), timeout=30)
            if not data: return False
            
            imei = Codec8EParser.parse_imei(data)
            if not imei or len(imei) < 15:
                logger.warning(f"Failed authentication from {self.addr}: Invalid IMEI")
                self.writer.write(b'\x00')
                await self.writer.drain()
                return False
            
            self.imei = imei
            self.registry.register(self)
            
            # Send Success ACK
            self.writer.write(b'\x01')
            await self.writer.drain()
            logger.info(f"Device authenticated: {self.imei} [{self.addr}]")
            return True
        except Exception as e:
            logger.error(f"Authentication error from {self.addr}: {e}")
            return False

    async def _process_buffer(self):
        """Frames packets and dispatches to parser."""
        while len(self.buffer) >= 8:
            # Check for Preamble (4 bytes zeros)
            if self.buffer[:4] != b'\x00\x00\x00\x00':
                # Malformed data or out of sync, search for next preamble
                idx = self.buffer.find(b'\x00\x00\x00\x00')
                if idx == -1:
                    # No preamble found, clear buffer if it grows too large
                    if len(self.buffer) > 8192: self.buffer.clear()
                    break
                else:
                    self.buffer = self.buffer[idx:]
                    continue

            # We found a preamble. Read data field length (next 4 bytes)
            data_len = struct.unpack('>I', self.buffer[4:8])[0]
            
            # Full packet length = 4(preamble) + 4(len) + data_len + 4(CRC)
            full_packet_len = 8 + data_len + 4
            
            if len(self.buffer) < full_packet_len:
                # Partial packet, wait for more data
                break
            
            # We have a full packet
            packet = bytes(self.buffer[:full_packet_len])
            self.buffer = self.buffer[full_packet_len:]
            
            await self._handle_packet(packet)

    async def _handle_packet(self, packet):
        """Decodes AVL packet, ACKs, and queues for DB."""
        self.packet_count += 1
        metrics.PACKETS_RECEIVED.inc()
        
        records = Codec8EParser.decode_avl(packet)
        
        if records:
            # ACK with record count (4 bytes)
            num_records = len(records)
            metrics.RECORDS_RECEIVED.inc(num_records)
            self.writer.write(num_records.to_bytes(4, byteorder='big'))
            await self.writer.drain()
            
            # Push to DB Queue (Phase 1 requirement)
            await self.db_queue.put({
                'imei': self.imei,
                'records': records,
                'raw': packet.hex(),
                'received_at': time.time()
            })
            logger.debug(f"Queued {num_records} records from {self.imei}")
        else:
            metrics.MALFORMED_PACKETS.inc()
            logger.warning(f"Failed to decode packet from {self.imei}")

    async def _listen_for_commands(self):
        """Subscribes to Redis for commands specific to this IMEI."""
        await self.cache.connect()
        pubsub = self.cache.client.pubsub()
        await pubsub.subscribe(f"device_commands:{self.imei}")
        
        logger.info(f"Command listener started for {self.imei}")
        
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    cmd_data = json.loads(message['data'].decode('utf-8'))
                    logger.info(f"Sending command {cmd_data['type']} to {self.imei}")
                    
                    # Teltonika GPRS command format (Codec 12 is common, but let's assume raw string for now)
                    # Implementation of Codec 12 would go here.
                    # For demonstration, we send a simple reboot string if requested
                    command_str = cmd_data['payload'] or cmd_data['type']
                    self.writer.write(command_str.encode())
                    await self.writer.drain()
                
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Command listener error for {self.imei}: {e}")
                await asyncio.sleep(5)

    async def supersede(self):
        """Forces the session to close because a newer one started."""
        self._superseded = True
        await self.close()

    async def close(self):
        if self.command_task:
            self.command_task.cancel()
        self.registry.unregister(self)
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except: pass
        logger.info(f"Session closed for {self.imei or self.addr}")
