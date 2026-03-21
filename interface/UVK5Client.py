import serial
import struct
import time

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
    def __init__(self, port, baud=38400, debug=False):
        """
        Initialize the UVK5Client.

        Args:
            port (str): Serial port name (e.g., 'COM10', '/dev/ttyUSB0').
            baud (int, optional): Baud rate. Defaults to 38400.
            debug (bool, optional): Enable debug logging. Defaults to False.
        """
        self.port = port
        self.baud = baud
        self.is_encrypted = True
        self.debug = debug
        self.ser = None
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1, write_timeout=1)
        except Exception as e:
            print(f"Failed to open port {self.port}: {e}")
            print("Trying to reconnect... Please unplug and replug the USB cable if needed.")
            self.reconnect()

    def reconnect(self):
        """Automatically reconnect if the connection drops."""
        print(f"Connection lost. Reconnecting to {self.port}...")
        while True:
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1, write_timeout=1)
                print(f"Reconnected to {self.port} successfully.")
                break
            except Exception:
                print(f"Failed to reconnect to {self.port}. Retrying in 1 second...")
                time.sleep(1)

    def close(self):
        """Close the serial connection."""
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
        
        if self.debug:
            print(f"[TX] {frame.hex(' ')}")
            
        while True:
            try:
                self.ser.write(frame)
                break
            except Exception as e:
                print(f"Write error: {e}")
                self.reconnect()

    def read_response(self):
        """
        Read and decrypt a response from the device.

        Returns:
            tuple: (cmd_id, data_bytes) or None if timeout/error.
        """
        # 1. Read Transport Header (4 bytes)
        try:
            header_data = self.ser.read(4)
        except Exception as e:
            print(f"Read error: {e}")
            self.reconnect()
            return None
            
        if len(header_data) < 4:
            print("[RX] Timeout reading header")
            return None
        
        magic, payload_len = struct.unpack('<HH', header_data)
        if magic != TRANS_HEADER_ID:
            if self.debug:
                print(f"[RX] Invalid Magic: {hex(magic)}")
                print(f"[RX Dump] {header_data.hex(' ')}")
            return None

        # 2. Read Payload (payload_len)
        # Firmware SendReply does NOT include CRC.
        body_len = payload_len
        try:
            encrypted_body = self.ser.read(body_len)
        except Exception as e:
            print(f"Read payload error: {e}")
            self.reconnect()
            return None
            
        if len(encrypted_body) < body_len:
            if self.debug:
                print("[RX] Incomplete Body")
            return None

        # 3. Read Footer (4 bytes: Padding + ID)
        try:
            footer_data = self.ser.read(4)
        except Exception as e:
            print(f"Read footer error: {e}")
            self.reconnect()
            return None
            
        if len(footer_data) < 4:
            if self.debug:
                print("[RX] Incomplete Footer")
            return None
            
        # 4. Decrypt Body
        decrypted_body = self._apply_obfuscation(encrypted_body)
        
        if self.debug:
            print(f"[RX] Header: {header_data.hex(' ')} | Body: {encrypted_body.hex(' ')} | Footer: {footer_data.hex(' ')}")
        
        # 5. Parse Inner Packet
        payload = decrypted_body
        if len(payload) < 4:
             return None
        
        cmd_id, data_len = struct.unpack('<HH', payload[0:4])
        data = payload[4:]
        
        return cmd_id, data

    def connect(self):
        """
        Establish connection and perform protocol handshake.

        Returns:
            bool: True if connection successful, False otherwise.
        """
        print("Connecting and Handshaking...")
        # 0x0514 Handshake
        original_encryption = self.is_encrypted
        self.is_encrypted = False # Force plaintext for handshake request
        
        try:
            timestamp = struct.pack('<I', int(time.time()))
            self.send_command(0x0514, timestamp)
            
            resp = self.read_response()
            if resp:
                cmd_id, data = resp
                if cmd_id == 0x0515:
                    version = data[0:16].decode('ascii', errors='ignore').strip('\x00')
                    print(f"Connected! Firmware Version: {version}")
                    return True
        except Exception as e:
            print(f"Handshake error: {e}")
            self.is_encrypted = original_encryption
            
        return False

    def set_channel(self, channel, freq_hz, tx_off_dir, tx_off_freq, bw, rx_tone_type, rx_tone_code, tx_tone_type, tx_tone_code, power=0):
        """
        Configure parameters for a specific channel.

        Args:
            channel (int): Channel index (0 for VFO A, 1 for VFO B).
            freq_hz (int): Receive frequency in Hz.
            tx_off_dir (int): Transmit offset direction (0=None, 1=Add, 2=Sub).
            tx_off_freq (int): Transmit offset frequency in Hz.
            bw (int): Bandwidth (0=Wide, 1=Narrow).
            rx_tone_type (int): RX Tone Type (0=Off, 1=CTCSS, 2=DCS, 3=RevDCS).
            rx_tone_code (int): RX Tone Code Index.
            tx_tone_type (int): TX Tone Type (0=Off, 1=CTCSS, 2=DCS, 3=RevDCS).
            tx_tone_code (int): TX Tone Code Index.
            power (int, optional): Transmit power (0=Low, 1=Mid, 2=High). Defaults to 0.
        """
        print(f"Setting Channel {channel} to {freq_hz/1000000} MHz, Power={power}...")
        # Struct: B I B I B B B B B B (16 bytes)
        payload = struct.pack('<BIBIBBBBBB', 
            channel, freq_hz, tx_off_dir, tx_off_freq, bw,
            rx_tone_type, rx_tone_code, tx_tone_type, tx_tone_code, power
        )
        self.send_command(0x0830, payload)

    def get_channel(self, channel):
        """
        Retrieve configuration for a specific channel.

        Args:
            channel (int): Channel index (0 for VFO A, 1 for VFO B).

        Returns:
            dict: Dictionary containing channel configuration (frequency, offset, tones, power, etc.) or None if failed.
        """
        print(f"Reading Channel {channel}...")
        payload = struct.pack('<B', channel)
        self.send_command(0x0831, payload)
        
        resp = self.read_response()
        if resp:
            cmd_id, data = resp
            if cmd_id == 0x0832:
                ch, freq, off_dir, off_val, bw, rx_type, rx_code, tx_type, tx_code, power = struct.unpack('<BIBIBBBBBB', data)
                return {
                    "channel": ch,
                    "frequency": freq,
                    "offset_dir": off_dir,
                    "offset_val": off_val,
                    "bandwidth": bw,
                    "rx_tone_type": rx_type,
                    "rx_tone_code": rx_code,
                    "tx_tone_type": tx_type,
                    "tx_tone_code": tx_code,
                    "power": power
                }
        return None

    def set_ptt(self, on):
        """
        Control the PTT (Push-To-Talk) state.

        Args:
            on (bool): True to start transmitting, False to stop.
        """
        print(f"Setting PTT {'ON' if on else 'OFF'}...")
        payload = struct.pack('<B', 1 if on else 0)
        self.send_command(0x0840, payload)

    def set_active_channel(self, channel):
        """
        Set the currently active channel (VFO).

        Args:
            channel (int): Channel index (0 for VFO A, 1 for VFO B).
        """
        print(f"Setting Active Channel to {channel}...")
        payload = struct.pack('<B', channel)
        self.send_command(0x0850, payload)

    def get_active_channel(self):
        """
        Get the currently active channel (VFO).

        Returns:
            int: Active channel index (0 or 1) or None if failed.
        """
        print("Reading Active Channel...")
        self.send_command(0x0851, b'')
        
        resp = self.read_response()
        if resp:
            cmd_id, data = resp
            if cmd_id == 0x0852:
                ch = struct.unpack('<B', data)[0]
                return ch
        return None

    def set_squelch(self, level):
        """
        Set the global Squelch level.

        Args:
            level (int): Squelch level (0-9).
        """
        if level < 0 or level > 9:
            print("Squelch level must be between 0 and 9.")
            return

        print(f"Setting Squelch level to {level}...")
        payload = struct.pack('<B', level)
        self.send_command(0x0860, payload)

    def get_squelch(self):
        """
        Get the global Squelch level.

        Returns:
            int: Squelch level (0-9) or None if failed.
        """
        print("Reading Squelch level...")
        self.send_command(0x0861, b'')
        
        resp = self.read_response()
        if resp:
            cmd_id, data = resp
            if cmd_id == 0x0862:
                level = struct.unpack('<B', data)[0]
                return level
        return None
