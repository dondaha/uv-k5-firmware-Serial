import sys
import time
from interface.UVK5Client import UVK5Client

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_uvk5_serial.py <COM_PORT>")
        sys.exit(1)
        
    PORT = sys.argv[1]
    
    client = UVK5Client(PORT)
    
    try:
        if not client.connect():
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
        ch_info = client.get_channel(0)
        if ch_info and ch_info['frequency'] == 438500000:
             print("[PASS] Channel A set correctly.")
        else:
             print(f"[FAIL] Channel A mismatch: {ch_info}")

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
        client.get_channel(1)
        
        time.sleep(1)
        
        # Ensure we are on Channel A before PTT test
        print("Switching to Channel B for PTT test...")
        client.set_active_channel(1)
        active_ch = client.get_active_channel()
        if active_ch != 1:
             print("[WARN] Failed to switch to Channel B?")

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
