import os
import sys
import asyncio
import logging
import serial.tools.list_ports # 追加引入

# 将父级目录加入 path，以便导入 interface/UVK5Client.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'interface')))
from UVK5Client import UVK5Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RadioManager:
    def __init__(self):
        self.client = None
        # 根据系统设定默认端口，Windows 通常为 COMx，Linux 通常为 /dev/ttyUSB0
        self.port = "COM11" if os.name == 'nt' else "/dev/ttyUSB0"
        self.connected = False
        self.lock = asyncio.Lock() # 用于保护串口并发调用

    async def connect(self, port: str = None) -> bool:
        if port:
            self.port = port
        logger.info(f"Connecting to radio on {self.port}...")
        
        try:
            # 串口操作和网络 IO 可能会阻塞 event loop，这里为了简单先直接调用
            # 或者使用 asyncio.to_thread 防止阻塞
            def _connect():
                client = UVK5Client(self.port, baud=38400, debug=False)
                connected = client.connect()
                return client, connected

            self.client, self.connected = await asyncio.to_thread(_connect)
            return self.connected
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        if self.client and self.connected:
            self.client.close()
            self.connected = False
            self.client = None
            logger.info("Radio disconnected.")

    async def set_ptt(self, state: bool) -> bool:
        if not self.connected or not self.client:
            return False
        
        # 使用锁确保串口写操作不冲突冲突
        async with self.lock:
            try:
                await asyncio.to_thread(self.client.set_ptt, state)
                return True
            except Exception as e:
                logger.error(f"PTT Error: {e}")
                return False

    async def get_rssi(self):
        if not self.connected or not self.client:
            return None
        
        async with self.lock:
            try:
                rssi = await asyncio.to_thread(self.client.get_rssi)
                return rssi
            except Exception as e:
                logger.error(f"RSSI Error: {e}")
                return None

    @staticmethod
    def list_ports():
        ports = serial.tools.list_ports.comports()
        return [{"device": p.device, "description": p.description} for p in ports]

    async def get_channel(self, channel: int):
        if not self.connected or not self.client:
            return None
        async with self.lock:
            try:
                return await asyncio.to_thread(self.client.get_channel, channel)
            except Exception as e:
                logger.error(f"Get channel error: {e}")
                return None

    async def set_channel(self, channel: int, freq_hz: int, tx_off_dir: int, tx_off_freq: int, 
                          bw: int, rx_tone_type: int, rx_tone_code: int, tx_tone_type: int, 
                          tx_tone_code: int, power: int = 0):
        if not self.connected or not self.client:
            return False
        async with self.lock:
            try:
                await asyncio.to_thread(
                    self.client.set_channel, channel, freq_hz, tx_off_dir, tx_off_freq, 
                    bw, rx_tone_type, rx_tone_code, tx_tone_type, tx_tone_code, power
                )
                return True
            except Exception as e:
                logger.error(f"Set channel error: {e}")
                return False

    async def get_active_channel(self):
        if not self.connected or not self.client:
            return None
        async with self.lock:
            try:
                return await asyncio.to_thread(self.client.get_active_channel)
            except Exception as e:
                logger.error(f"Get active channel error: {e}")
                return None

    async def set_active_channel(self, channel: int):
        if not self.connected or not self.client:
            return False
        async with self.lock:
            try:
                await asyncio.to_thread(self.client.set_active_channel, channel)
                return True
            except Exception as e:
                logger.error(f"Set active channel error: {e}")
                return False

    async def get_squelch(self):
        if not self.connected or not self.client:
            return None
        async with self.lock:
            try:
                return await asyncio.to_thread(self.client.get_squelch)
            except Exception as e:
                logger.error(f"Get squelch error: {e}")
                return None

    async def set_squelch(self, level: int):
        if not self.connected or not self.client:
            return False
        async with self.lock:
            try:
                await asyncio.to_thread(self.client.set_squelch, level)
                return True
            except Exception as e:
                logger.error(f"Set squelch error: {e}")
                return False

    async def get_monitor(self):
        if not self.connected or not self.client:
            return None
        async with self.lock:
            try:
                return await asyncio.to_thread(self.client.get_monitor)
            except Exception as e:
                logger.error(f"Get monitor error: {e}")
                return None

    async def set_monitor(self, on: bool):
        if not self.connected or not self.client:
            return False
        async with self.lock:
            try:
                await asyncio.to_thread(self.client.set_monitor, on)
                return True
            except Exception as e:
                logger.error(f"Set monitor error: {e}")
                return False
