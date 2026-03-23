import asyncio
import logging
import pyaudio
import numpy as np
import av
import fractions
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from config import load_config

logger = logging.getLogger(__name__)

class PersistentAudioCaptureTrack(MediaStreamTrack):
    """
    一个从全局缓冲队列中读取音频数据的 WebRTC 轨道
    """
    kind = "audio"

    def __init__(self, track_queue):
        super().__init__()
        self.track_queue = track_queue

    async def recv(self):
        # 阻塞等待属于自己的音频数据（队列为空时挂起，避免消费过快或死循环消耗CPU）
        frame = await self.track_queue.get()
        return frame


class WebRTCManager:
    """
    管理 WebRTC 连接与音频播放，全局单例保持设备永久开启
    """
    def __init__(self):
        self.pcs = set()
        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        
        # 发送给电台硬件的混音/播放队列
        self.tx_queue = asyncio.Queue(maxsize=100)
        # 每个客户端维护一个独立拉取队列，防多端消费冲突
        self.client_rx_queues = []
        
        self.rate = 48000
        self.chunk = int(self.rate * 0.02)
        self.running = False

    def get_audio_devices(self):
        """获取系统所有的声卡列表，供前台参考（现在后端已经接管控制不怎么用到了）"""
        devices = []
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            devices.append({
                "index": i,
                "name": info.get("name"),
                "max_input_channels": info.get("maxInputChannels"),
                "max_output_channels": info.get("maxOutputChannels")
            })
        return devices

    def get_device_index_by_name(self, target_name: str) -> int:
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            name = info.get("name", "")
            if target_name in name:
                return i
        return None

    async def start_audio_streams(self):
        """启动全局单例音频流（程序启动时执行一次，不再关闭）"""
        if self.running:
            return
            
        conf = load_config()
        target_audio_name = conf.get("audio_device", "AB13X USB Audio")
        forced_index = self.get_device_index_by_name(target_audio_name)
        
        if forced_index is not None:
            logger.info(f"Target Audio Device '{target_audio_name}' found at index {forced_index}. Forcing binding.")
        else:
            logger.error(f"Target Audio Device '{target_audio_name}' NOT found. Exiting program to prevent unexpected behavior.")
            import sys
            sys.exit(1)

        # 启动输入流（麦克风->网页拾音）
        try:
            self.input_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.rate,
                input=True,
                input_device_index=forced_index,
                frames_per_buffer=self.chunk
            )
            logger.info("Persistent Audio INPUT stream opened successfully.")
        except Exception as e:
            logger.error(f"Failed to open persistent audio input: {e}")
            import sys
            sys.exit(1)

        # 启动输出流（网页播音->扬声器）
        try:
            self.output_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.rate,
                output=True,
                output_device_index=forced_index,
                frames_per_buffer=self.chunk
            )
            logger.info("Persistent Audio OUTPUT stream opened successfully.")
        except Exception as e:
            logger.error(f"Failed to open persistent audio output: {e}")
            import sys
            sys.exit(1)

        self.running = True
        
        # 挂起背景守护长期任务，死循环读写
        asyncio.create_task(self._mic_read_loop())
        asyncio.create_task(self._spk_write_loop())

    async def _mic_read_loop(self):
        """持续从硬件麦克风读取数据并分发给所有活跃网页的队列"""
        pts = 0
        while self.running:
            if not self.input_stream:
                await asyncio.sleep(0.02)
                continue
            
            try:
                # IO 读取防止阻塞使用 to_thread
                data = await asyncio.to_thread(self.input_stream.read, self.chunk, exception_on_overflow=False)
                
                ndarray = np.frombuffer(data, dtype=np.int16).reshape(1, -1)
                frame = av.AudioFrame.from_ndarray(ndarray, format='s16', layout='mono')
                frame.sample_rate = self.rate
                frame.time_base = fractions.Fraction(1, self.rate)
                frame.pts = pts
                pts += self.chunk

                # 广播分发给所有当前连接网页的独立队列
                dead_queues = []
                for q in self.client_rx_queues:
                    try:
                        if q.full():
                            q.get_nowait()  # 若网页处理太慢，丢弃旧的一帧抗积压
                        q.put_nowait(frame)
                    except Exception:
                        dead_queues.append(q)
                
                # 清理坏队列
                for dq in dead_queues:
                    if dq in self.client_rx_queues:
                        self.client_rx_queues.remove(dq)
                        
            except Exception as e:
                logger.error(f"Mic read loop error: {e}")
                await asyncio.sleep(0.02)

    async def _spk_write_loop(self):
        """持续从接收队列读取发声数据并写入声卡；没人发声时发静音防断连"""
        silence = b'\x00' * (self.chunk * 2)
        while self.running:
            if not self.output_stream:
                await asyncio.sleep(0.02)
                continue

            try:
                try:
                    # 尝试从队列拿网页交来的发声数据，最长等 0.02s
                    audio_bytes = await asyncio.wait_for(self.tx_queue.get(), timeout=0.02)
                except asyncio.TimeoutError:
                    # 如果这 0.02s 没人说话，填入静音维持心跳流
                    audio_bytes = silence

                await asyncio.to_thread(self.output_stream.write, audio_bytes)
            except Exception as e:
                logger.error(f"Spk write loop error: {e}")
                await asyncio.sleep(0.02)

    async def handle_offer(self, sdp: str, offer_type: str, input_device_index: int = None, output_device_index: int = None) -> dict:
        """极简的 SDP 与 Track 分发（不再触碰底层声卡硬件，全走队列）"""
        offer = RTCSessionDescription(sdp=sdp, type=offer_type)
        pc = RTCPeerConnection()
        self.pcs.add(pc)

        # ====== 收听电台通道 (给网页发声音) ======
        client_q = asyncio.Queue(maxsize=15)
        self.client_rx_queues.append(client_q)
        audio_track = PersistentAudioCaptureTrack(track_queue=client_q)
        pc.addTrack(audio_track)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"WebRTC Connection state: {pc.connectionState}")
            if pc.connectionState in ["failed", "closed", "disconnected"]:
                if client_q in self.client_rx_queues:
                    self.client_rx_queues.remove(client_q)
                await pc.close()
                self.pcs.discard(pc)

        # ====== 输出到电台通道 (处理网页发来的麦克风) ======
        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                logger.info("Received an audio track from browser")
                
                async def play_track():
                    resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
                    while True:
                        try:
                            # 挂起等待接收网页发来的声音数据并放进 tx_queue 给守护进程播放
                            frame = await track.recv()
                            frame.pts = None
                            for resampled_frame in resampler.resample(frame):
                                audio_bytes = resampled_frame.to_ndarray().tobytes()
                                # 推送到共享 Tx 队列
                                if self.tx_queue.full():
                                    self.tx_queue.get_nowait()
                                self.tx_queue.put_nowait(audio_bytes)
                        except MediaStreamError:
                            logger.info("Track WebRTC channel closed properly (Client Refreshed/Disconnected).")
                            break
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.info(f"Track playback ended/error: {e}")
                            break

                asyncio.create_task(play_track())

        # 完成 SDP 握手
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
