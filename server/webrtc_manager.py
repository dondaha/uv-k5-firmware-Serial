import asyncio
import logging
import pyaudio
import numpy as np
import av
import fractions
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

logger = logging.getLogger(__name__)

class AudioCaptureTrack(MediaStreamTrack):
    """
    一个从麦克风（电台接收音频）捕获数据的 WebRTC 轨道
    """
    kind = "audio"

    def __init__(self, input_device_index=None, pyaudio_instance=None):
        super().__init__()
        # Use shared pyaudio instance instead of creating a new one
        self.p = pyaudio_instance if pyaudio_instance else pyaudio.PyAudio()
        self.rate = 48000
        # 20ms 一帧，WebRTC 常见的音频打包长度
        self.chunk = int(self.rate * 0.02) 
        self.stream = None
        self._input_device_index = input_device_index
        self._is_stopped = False
        
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.rate,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=self.chunk
            )
            logger.info(f"Audio input stream opened on device {input_device_index}")
        except Exception as e:
            logger.error(f"Failed to open audio input: {e}")
            self.stream = None
            
        self.pts = 0

    async def recv(self):
        if self._is_stopped:
            # 停止后抛出异常以结束任务
            # aiortc 需要 MediaStreamError 来正常停止轨道的拉取
            import aiortc.mediastreams
            raise aiortc.mediastreams.MediaStreamError("Track is stopped")
            
        if not self.stream:
            # 如果音频设备打开失败，发送空静音包，防止 WebRTC 卡死
            await asyncio.sleep(0.02)
            data = b'\x00' * (self.chunk * 2) # 16bit = 2 bytes
        else:
            try:
                # 在子线程中读取音频，防止阻塞 asyncio 的事件循环
                data = await asyncio.to_thread(self.stream.read, self.chunk, exception_on_overflow=False)
            except Exception as e:
                logger.error(f"Audio read error: {e}")
                data = b'\x00' * (self.chunk * 2)

        # 转换为 aiortc 所需的 av (FFmpeg) 帧
        ndarray = np.frombuffer(data, dtype=np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(ndarray, format='s16', layout='mono')
        frame.sample_rate = self.rate
        frame.time_base = fractions.Fraction(1, self.rate)
        frame.pts = self.pts
        self.pts += self.chunk
        
        return frame

    def stop(self):
        super().stop()
        self._is_stopped = True
        try:
            if self.stream:
                if not self.stream.is_stopped():
                    self.stream.stop_stream()
                self.stream.close()
                self.stream = None
                logger.info(f"Audio input stream closed")
        except Exception as e:
            logger.error(f"Error closing input stream: {e}")
        # Never terminate the shared PyAudio instance here

class WebRTCManager:
    """
    管理 WebRTC 连接与音频播放（写入声卡发给电台）
    """
    def __init__(self):
        self.pcs = set()
        self.p = pyaudio.PyAudio() # Singleton instance
        self.output_stream = None
        self.current_audio_track = None

    def get_audio_devices(self):
        """获取系统所有的声卡列表，供前端选择 USB 声卡"""
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

    async def handle_offer(self, sdp: str, offer_type: str, input_device_index: int = None, output_device_index: int = None) -> dict:
        offer = RTCSessionDescription(sdp=sdp, type=offer_type)
        pc = RTCPeerConnection()
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"WebRTC Connection state: {pc.connectionState}")
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                await pc.close()
                self.pcs.discard(pc)

        if self.current_audio_track:
            logger.info("Cleaning up previous audio recording track...")
            self.current_audio_track.stop()
            self.current_audio_track = None
            await asyncio.sleep(0.5)

        if self.output_stream:
            logger.info("Cleaning up previous audio output stream...")
            try:
                if not self.output_stream.is_stopped():
                    self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception as e:
                logger.warning(f"Error during output stream cleanup: {e}")
            self.output_stream = None
            await asyncio.sleep(0.5)

        # Do NOT terminate PyAudio instance. Reuse self.p!
        
        audio_track = AudioCaptureTrack(input_device_index=input_device_index, pyaudio_instance=self.p)
        self.current_audio_track = audio_track
        pc.addTrack(audio_track)

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                logger.info("Received an audio track from browser")

                if not self.output_stream:
                    try:
                        self.output_stream = self.p.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=48000,
                            output=True,
                            output_device_index=output_device_index,
                            start=False
                        )
                        self.output_stream.start_stream()
                    except Exception as e:
                        logger.error(f"Failed to open audio output: {e}")

                async def play_track():
                    # 我们需要将接收到的不同格式音频，统一重采样为我们声明的 48kHz 单声道
                    resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
                    while True:
                        try:
                            # 接收网页发来的音频帧
                            frame = await track.recv()
                            # 重采样并获取字节
                            frame.pts = None
                            for resampled_frame in resampler.resample(frame):
                                audio_bytes = resampled_frame.to_ndarray().tobytes()
                                if self.output_stream:
                                    # 将这段声音数据交给 PyAudio 去播放（实际上就进了 USB 声卡的麦克风发送给电台了）
                                    await asyncio.to_thread(self.output_stream.write, audio_bytes)
                        except Exception as e:
                            # 捕获所有由于断开连接引起的 track.recv() 异常 (包括 MediaStreamError)
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
