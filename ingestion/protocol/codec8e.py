import struct
from datetime import datetime, timezone

class Codec8EParser:
    """
    Parser for Teltonika Codec 8 Extended (8E) protocol.
    Used by FMC130 and other modern Teltonika devices.
    """
    
    @staticmethod
    def parse_imei(data):
        if len(data) < 2:
            return None
        imei_len = struct.unpack('>H', data[:2])[0]
        if len(data) < 2 + imei_len:
            return None
        return data[2:2+imei_len].decode('ascii')

    @staticmethod
    def crc16(data):
        crc = 0x0000
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    @staticmethod
    def decode_avl(data):
        """
        Decodes a full AVL data packet with CRC validation.
        Returns a list of records.
        """
        if len(data) < 15:
            return None
            
        offset = 0
        # Preamble (4 bytes zeros)
        if data[offset:offset+4] != b'\x00\x00\x00\x00':
            return None
        offset += 4
        
        # Data Length (4 bytes)
        data_field_len = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4
        
        # CRC Validation
        # The CRC is calculated over the data field (Codec ID to Number of Data 2)
        # Length of data field is data_field_len
        # CRC is the last 4 bytes of the packet
        if len(data) < 8 + data_field_len + 4:
            return None
            
        data_field = data[8:8+data_field_len]
        received_crc = struct.unpack('>I', data[8+data_field_len:8+data_field_len+4])[0]
        
        calculated_crc = Codec8EParser.crc16(data_field)
        if calculated_crc != (received_crc & 0xFFFF):
            # CRC Mismatch (Phase 7 requirement)
            # Log as hex for diagnostics
            return None
            
        # Codec ID (1 byte)
        codec_id = data[offset]
        offset += 1
        
        if codec_id != 0x8E:
            return None
            
        # Number of Data 1 (1 byte)
        num_records = data[offset]
        offset += 1
        
        records = []
        try:
            for i in range(num_records):
                record, bytes_read = Codec8EParser._parse_single_record(data[offset:])
                if record:
                    if Codec8EParser._is_valid_gps(record):
                        records.append(record)
                    offset += bytes_read
                else:
                    # Partial record or parsing error
                    break
        except Exception:
            # Fatal parse error in the middle of a packet
            return None
                
        # Number of Data 2 (1 byte)
        # num_records_2 = data[offset]
        
        return records

    @staticmethod
    def _is_valid_gps(record):
        """Basic GPS sanity check."""
        lon = record.get('longitude', 0)
        lat = record.get('latitude', 0)
        # Avoid 0,0 and out of range coordinates
        if lon == 0 and lat == 0:
            return False
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            return False
        return True

    @staticmethod
    def _parse_single_record(data):
        offset = 0
        try:
            # Timestamp (8 bytes, ms since epoch)
            ts_ms = struct.unpack('>Q', data[offset:offset+8])[0]
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            offset += 8
            
            # Priority (1 byte)
            priority = data[offset]
            offset += 1
            
            # GPS Element
            # Longitude (4 bytes)
            lon = struct.unpack('>i', data[offset:offset+4])[0] / 10000000.0
            offset += 4
            # Latitude (4 bytes)
            lat = struct.unpack('>i', data[offset:offset+4])[0] / 10000000.0
            offset += 4
            # Altitude (2 bytes)
            alt = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            # Angle (2 bytes)
            angle = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            # Satellites (1 byte)
            sats = data[offset]
            offset += 1
            # Speed (2 bytes)
            speed = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            
            # IO Element (Extended)
            event_id = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            total_io = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            
            io_dict = {}
            
            # 1-byte elements
            cnt1 = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            for _ in range(cnt1):
                id_ = struct.unpack('>H', data[offset:offset+2])[0]
                val = data[offset+2]
                io_dict[id_] = val
                offset += 3
                
            # 2-byte elements
            cnt2 = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            for _ in range(cnt2):
                id_ = struct.unpack('>H', data[offset:offset+2])[0]
                val = struct.unpack('>H', data[offset+2:offset+4])[0]
                io_dict[id_] = val
                offset += 4
                
            # 4-byte elements
            cnt4 = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            for _ in range(cnt4):
                id_ = struct.unpack('>H', data[offset:offset+2])[0]
                val = struct.unpack('>I', data[offset+2:offset+6])[0]
                io_dict[id_] = val
                offset += 6
                
            # 8-byte elements
            cnt8 = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            for _ in range(cnt8):
                id_ = struct.unpack('>H', data[offset:offset+2])[0]
                val = struct.unpack('>Q', data[offset+2:offset+10])[0]
                io_dict[id_] = val
                offset += 10
                
            # Variable length elements
            cnt_var = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            for _ in range(cnt_var):
                id_ = struct.unpack('>H', data[offset:offset+2])[0]
                v_len = struct.unpack('>H', data[offset+2:offset+4])[0]
                val = data[offset+4:offset+4+v_len].hex()
                io_dict[id_] = val
                offset += 4 + v_len

            record = {
                'timestamp': ts,
                'priority': priority,
                'longitude': lon,
                'latitude': lat,
                'altitude': alt,
                'angle': angle,
                'satellites': sats,
                'speed': speed,
                'event_id': event_id,
                'io_elements': io_dict
            }
            return record, offset
        except Exception:
            return None, offset
