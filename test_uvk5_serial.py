import serial
import struct
import time
import sys

# Protocol Constants
TRANS_HEADER_ID = 0xCDAB  # AB CD
TRANS_FOOTER_ID = 0xBADC  # DC BA
OBFUSCATION_KEY = bytes([
    0x16, 0x6C, 0x14, 0xE6, 0x2E, 0x91, 0x0D, 0x40, 
    0x21, 0x35, 0xD5, 0x40, 0x13, 0x03, 0xE9, 0x80
])

def crc16_ccitt(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc

class UVK5Client:
    def __init__(self, port, baud=38400):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.is_encrypted = True
    
    def close(self):
        self.ser.close()

    def _apply_obfuscation(self, data):
        if not self.is_encrypted:
            return data
        
        out = bytearray(len(data))
        for i in range(len(data)):
            out[i] = data[i] ^ OBFUSCATION_KEY[i % 16]
        return bytes(out)

    def send_command(self, cmd_id, data_payload):
        # 1. Construct Inner Packet (Command Header + Data)
        inner_header = struct.pack('<HH', cmd_id, len(data_payload))
        inner_packet = inner_header + data_payload
        
        # 2. Calculate CRC over Inner Packet
        crc = crc16_ccitt(inner_packet)
        crc_bytes = struct.pack('<H', crc)
        
        # 3. Construct Body (Payload + CRC)
        body = inner_packet + crc_bytes
        
        # 4. Obfuscate Body
        obfuscated_body = self._apply_obfuscation(body)
        
        # 5. Construct Transport Frame
        # Transport Header: ID (DCAB), Size (Len of Inner Packet)
        # Note: Firmware determines Payload size from this. 
        # But Firmware expects "Inner Packet + CRC" (Size + 2 bytes) to be copied.
        # IF we send Len=InnerPacket, firmware copies InnerPacket+CRC.
        trans_header = struct.pack('<HH', TRANS_HEADER_ID, len(inner_packet))
        
        trans_footer = struct.pack('<H', TRANS_FOOTER_ID)
        
        frame = trans_header + obfuscated_body + trans_footer
        
        print(f"[TX] {frame.hex(' ')}")
        self.ser.write(frame)

    def read_response(self):
        # 1. Read Transport Header (4 bytes)
        header_data = self.ser.read(4)
        if len(header_data) < 4:
            print("[RX] Timeout reading header")
            return None
        
        magic, payload_len = struct.unpack('<HH', header_data)
        if magic != TRANS_HEADER_ID:
            print(f"[RX] Invalid Magic: {hex(magic)}")
            print(f"[RX Dump] {header_data.hex(' ')}")
            return None

        # 2. Read Payload (payload_len)
        # Firmware SendReply does NOT include CRC.
        body_len = payload_len
        encrypted_body = self.ser.read(body_len)
        if len(encrypted_body) < body_len:
            print("[RX] Incomplete Body")
            return None

        # 3. Read Footer (4 bytes: Padding + ID)
        footer_data = self.ser.read(4)
        if len(footer_data) < 4:
            print("[RX] Incomplete Footer")
            return None
            
        # 4. Decrypt Body
        decrypted_body = self._apply_obfuscation(encrypted_body)
        
        print(f"[RX] Header: {header_data.hex(' ')} | Body: {encrypted_body.hex(' ')} | Footer: {footer_data.hex(' ')}")
        
        # 5. Parse Inner Packet
        payload = decrypted_body
        if len(payload) < 4:
             return None
             
        # Reply Packet: Header(4) + Data
        # Header: ID(2) + Size(2)
        # But wait, SendReply sends: Header (4) + Payload. 
        # The "Payload" contains the struct data.
        # But the ID in Header IS the command ID.
        # Firmware SendReply:
        # Header.ID = 0xCDAB (Transport Header ID) ?? No.
        # Header.ID = 0xCDAB;
        # Header.Size = Size;
        # UART_Send(Header)
        
        # WAIT. SendReply sets Header.ID to 0xCDAB ??
        # app/uart.c:
        # Header.ID = 0xCDAB;
        # NO! 0xCDAB is the Transport Header ID.
        # So the Reply packet DOES NOT have an inner header?
        # It's just TransportHeader + Payload + Footer.
        
        # So where is the Command ID in the reply?
        # SendReply is called with pReply.
        # pReply is usually a struct starting with Header_t.
        # BUT SendReply sends Transport Header first.
        # Transport Header ID is ALWAYS 0xCDAB.
        
        # Does SendReply sends pReply content? Yes.
        # pReply usually contains a Header_t inside it (Inner Header).
        
        # Let's check a reply struct. e.g. REPLY_0514_t
        # typedef struct { Header_t Header; struct { ... } Data; } REPLY_0514_t;
        # Reply.Header.ID = 0x0515;
        # Reply.Header.Size = sizeof(Reply.Data);
        # SendReply(&Reply, sizeof(Reply));
        
        # SendReply takes (void* pReply, Size).
        # Sends TransportHeader(ID=CDAB, Size=Size).
        # Then Sends pReply (which contains InnerHeader(ID=0515, Size=DataSize) + Data).
        
        # So `decrypted_body` contains `InnerHeader` + `Data`.
        
        cmd_id, data_len = struct.unpack('<HH', payload[0:4])
        data = payload[4:]
        
        return cmd_id, data

    def handshake(self):
        print("Handshaking...")
        # 0x0514 Handshake
        # To strictly synchronize state with firmware (which switches to plaintext ONLY if it sees 0x0514 in current buffer),
        # we should send 0x0514 in Plaintext. 
        # Even if fw is currently encrypted, it checks ID before decrypting.
        
        # Determine previous state to handle re-handshakes if needed, but for fresh start assume we want plaintext sync.
        original_encryption = self.is_encrypted
        self.is_encrypted = False # Force plaintext for handshake request
        
        try:
            # Data: Timestamp (4 bytes)
            timestamp = struct.pack('<I', int(time.time()))
            self.send_command(0x0514, timestamp)
            
            # The response will be Plaintext if our request successfully switched the FW to plaintext.
            # However, if FW was somehow already encrypted and didn't switch (unlikely with 0514 check), we might fail.
            
            resp = self.read_response()
            if resp:
                cmd_id, data = resp
                if cmd_id == 0x0515:
                    version = data[0:16].decode('ascii', errors='ignore').strip('\x00')
                    print(f"Connected! Firmware Version: {version}")
                    # self.is_encrypted is already False. Keep it that way.
                    return True
        except Exception as e:
            print(f"Handshake error: {e}")
            self.is_encrypted = original_encryption # Restore if failed
            
        return False

    def set_channel(self, channel, freq_hz, tx_off_dir, tx_off_freq, bw, rx_tone_type, rx_tone_code, tx_tone_type, tx_tone_code, power=0):
        print(f"Setting Channel {channel} to {freq_hz/1000000} MHz, Power={power}...")
        # Struct: B I B I B B B B B B (16 bytes)
        payload = struct.pack('<BIBIBBBBBB', 
            channel, freq_hz, tx_off_dir, tx_off_freq, bw,
            rx_tone_type, rx_tone_code, tx_tone_type, tx_tone_code, power
        )
        self.send_command(0x0830, payload)
        # No specific response for set command? Protocol says no. 
        # But we can read back to verify.

    def get_channel(self, channel):
        print(f"Reading Channel {channel}...")
        payload = struct.pack('<B', channel)
        self.send_command(0x0831, payload)
        
        resp = self.read_response()
        if resp:
            cmd_id, data = resp
            if cmd_id == 0x0832:
                # Parse config
                ch, freq, off_dir, off_val, bw, rx_type, rx_code, tx_type, tx_code, power = struct.unpack('<BIBIBBBBBB', data)
                print(f"  > Channel: {ch}")
                print(f"  > Freq:    {freq/1000000:.4f} MHz")
                print(f"  > Offset:  {'+' if off_dir==1 else '-' if off_dir==2 else 'OFF'} {off_val/1000} kHz")
                print(f"  > BW:      {'Narrow' if bw else 'Wide'}")
                print(f"  > Power:   {'Low' if power==0 else 'Mid' if power==1 else 'High' if power==2 else str(power)}")
                print(f"  > RxTone:  Type={rx_type} Code={rx_code}")
                return freq
            else:
                print(f"Unexpected response ID: {hex(cmd_id)}")
        else:
            print("No response")
        return None

    def set_ptt(self, on):
        print(f"Setting PTT {'ON' if on else 'OFF'}...")
        payload = struct.pack('<B', 1 if on else 0)
        self.send_command(0x0840, payload)

    def set_active_channel(self, channel):
        print(f"Setting Active Channel to {channel}...")
        payload = struct.pack('<B', channel)
        self.send_command(0x0850, payload)

    def get_active_channel(self):
        print("Reading Active Channel...")
        self.send_command(0x0851, b'')
        
        resp = self.read_response()
        if resp:
            cmd_id, data = resp
            if cmd_id == 0x0852:
                ch = struct.unpack('<B', data)[0]
                print(f"  > Active Channel: {ch}")
                return ch
            else:
                print(f"Unexpected response ID: {hex(cmd_id)}")
        return None


# --- MAIN TEST ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_uvk5_serial.py <COM_PORT>")
        sys.exit(1)
        
    PORT = sys.argv[1]
    
    client = UVK5Client(PORT)
    
    try:
        # 1. Connect and Handshake
        if not client.handshake():
            print(f"{PORT} Handshake failed! Check connection.")
            sys.exit(1)
            
        time.sleep(1)
        
        # 2. Set Channel A (Index 0)
        # 438.500 MHz, +5MHz Offset, Wide, No Tone
        client.set_channel(
            channel=0,
            freq_hz=438500000,
            tx_off_dir=0, # -
            tx_off_freq=5000000, 
            bw=0, # Wide
            rx_tone_type=0, rx_tone_code=0,
            tx_tone_type=0, tx_tone_code=0,
            power=2 # High
        )
        time.sleep(0.5)
        
        # 3. Read back Channel A
        freq_a = client.get_channel(0)
        if freq_a == 438500000:
             print("[PASS] Channel A set correctly.")
        else:
             print(f"[FAIL] Channel A mismatch: {freq_a}")

        time.sleep(1)

        # 4. Set Channel B (Index 1)
        # 145.500 MHz, No Offset, Wide, No Tone
        client.set_channel(
            channel=1,
            freq_hz=145500000,
            tx_off_dir=0, 
            tx_off_freq=0, 
            bw=0, # Wide
            rx_tone_type=0, rx_tone_code=0,
            tx_tone_type=0, tx_tone_code=0,
            power=0 # Low
        )
        time.sleep(0.5)
        
        # 5. Read back Channel B
        freq_b = client.get_channel(1)
        
        time.sleep(1)
        
        # Ensure we are on Channel A before PTT test
        print("Switching to Channel A for PTT test...")
        client.set_active_channel(1)
        active_ch = client.get_active_channel()
        if active_ch != 1:
             print("[WARN] Failed to switch to Channel A?")

        time.sleep(1)
        
        # 6. Test PTT
        print("Testing PTT - WARNING: TRANSMITTING!")
        client.set_ptt(True)
        time.sleep(2) # Transmit for 2 seconds
        client.set_ptt(False)
        print("PTT OFF.")

    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()
