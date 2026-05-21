import socket
import time
import random
import struct
import binascii
import threading
import datetime

# Enterprise IVMS Stress Test Suite
# Goal: Validate 10k events/min and burst handling.

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5027
NUM_DEVICES = 100
MESSAGES_PER_DEVICE = 100
DELAY_BETWEEN_MESSAGES = 0.5 # seconds

def generate_teltonika_avl_packet(imei):
    """
    Generates a valid-looking Teltonika Codec 8 packet.
    """
    # 1. Preamble (4 bytes zeros)
    preamble = b'\x00\x00\x00\x00'
    
    # 2. Data Length (4 bytes) - placeholder
    # 3. Codec ID (1 byte)
    codec = b'\x08'
    # 4. Number of Data 1 (1 byte)
    count = b'\x01'
    
    # 5. AVL Data (Timestamp, Priority, GPS, IO)
    # Timestamp (8 bytes)
    now = int(datetime.datetime.now().timestamp() * 1000)
    ts = struct.pack(">Q", now)
    # Priority (1 byte)
    priority = b'\x01'
    # GPS Data (15 bytes)
    lng = struct.pack(">i", int(58.3 * 10000000))
    lat = struct.pack(">i", int(23.6 * 10000000))
    alt = struct.pack(">H", 100)
    angle = struct.pack(">H", 90)
    sats = b'\x0c'
    speed = struct.pack(">H", random.randint(0, 100))
    gps = lng + lat + alt + angle + sats + speed
    
    # IO Data (simplified)
    # 1 byte event ID, 1 byte total IO, ...
    io = b'\x00\x00\x00\x00\x00\x00' # No IO elements
    
    data = codec + count + ts + priority + gps + io + count
    data_len = struct.pack(">I", len(data))
    
    # 6. CRC-16 (4 bytes)
    crc = b'\x00\x00\x00\x00' # Placeholder
    
    return preamble + data_len + data + crc

def simulate_device(device_id):
    imei = f"358245000000{device_id:03d}"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((SERVER_IP, SERVER_PORT))
            
            # Send IMEI
            imei_bytes = imei.encode()
            s.send(struct.pack(">H", len(imei_bytes)) + imei_bytes)
            
            resp = s.recv(1)
            if resp != b'\x01':
                return
            
            for _ in range(MESSAGES_PER_DEVICE):
                packet = generate_teltonika_avl_packet(imei)
                s.send(packet)
                # Ingestion server doesn't respond to Codec 8 data packets usually (or responds with record count)
                # s.recv(4) 
                time.sleep(DELAY_BETWEEN_MESSAGES)
                
    except Exception as e:
        pass

if __name__ == "__main__":
    print(f"Starting Stress Test: {NUM_DEVICES} devices, {MESSAGES_PER_DEVICE} msgs each...")
    start_time = time.time()
    
    threads = []
    for i in range(NUM_DEVICES):
        t = threading.Thread(target=simulate_device, args=(i,))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
        
    duration = time.time() - start_time
    total_msgs = NUM_DEVICES * MESSAGES_PER_DEVICE
    print(f"\nTest Complete!")
    print(f"Total Messages: {total_msgs}")
    print(f"Duration: {duration:.2f}s")
    print(f"Throughput: {total_msgs/duration:.2f} msgs/sec ({60 * total_msgs/duration:.2f} msgs/min)")
