import asyncio
import logging
import pyaudio
import numpy as np
import av
import fractions
import threading
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

logger = logging.getLogger(__name__)

class AudioCaptureTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.rate = 48000
        self.chunk = int(self.rate * 0.02)
        self.pts = 0
        self._is_stopped = False

    async def recv(self):
        if self._is_stopped:
            import aiortc.mediastreams
            raise aiortc.mediastreams.MediaStreamError("Track is stopped")

        data = await self.manager.read_input_safe(self.chunk)
        if not data:
            await asyncio.sleep(0.02)
            data = b'\x00' * (self.chunk * 2)

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


class WebRTCManager:
    def __init__(self):
        self.pcs = set()
        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.current_input_device_index = None
        self.current_output_device_index = None
        
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.current_audio_track = None

    def get_audio_devices(self):
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

    def _ensure_streams(self, in_idx, out_idx):
        with self._read_lock:
            if self.input_stream and self.current_input_device_index != in_idx:
                try:
                    self.input_stream.stop_stream()
                    self.input_stream.close()
                except:
                    pass
                self.input_stream = None

            if not self.input_stream:
                try:
                    self.input_stream = self.p.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=48000,
                        input=True,
                        input_device_index=in_idx,
                        frames_per_buffer=960
                    )
                    self.current_input_device_index = in_idx
                    logger.info(f"Opened persistent input stream on device {in_idx}")
                except Exception as e:
                    logger.error(f"Failed to open audio input: {e}")
            else:
                try:
                    frames = self.input_stream.get_read_available()
                    if frames > 0:
                        self.input_stream.read(frames, exception_on_overflow=False)
                except:
                    pass

        with self._write_lock:
            if self.output_stream and self.current_output_device_index != out_idx:
                try:
                    self.output_stream.stop_stream()
                    self.output_stream.close()
                except:
                    pass
                self.output_stream = None

            if not self.output_stream:
                try:
                    self.output_stream = self.p.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=48000,
                        output=True,
                        output_device_index=out_idx,
                        frames_per_buffer=960
                    )
                    self.current_output_device_index = out_idx
                    logger.info(f"Opened persistent output stream on device {out_idx}")
                except Exception as e:
                    logger.error(f"Failed to open audio output: {e}")

    async def read_input_safe(self, chunk):
        def _read():
            with self._read_lock:
                if self.input_stream and not self.input_stream.is_stopped():
                    try:
                        return self.input_stream.read(chunk, exception_on_overflow=False)
                    except Exception:
                        pass
            return None
        return await asyncio.to_thread(_read)

    async def write_output_safe(self, data):
        def _write():
            with self._write_lock:
                if self.output_stream and not self.output_stream.is_stopped():
                    try:
                        self.output_stream.write(data, exception_on_underflow=False)
                    except Exception:
                        pass
        await asyncio.to_thread(_write)

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
                    self.current_audio_track.stop()
                    self.current_audio_track = None

        if self.current_audio_track:
            self.current_audio_track.stop()
            self.current_audio_track = None

        # Always ensure streams are alive and flushed BEFORE returning control
        self._ensure_streams(input_device_index, output_device_index)

        audio_track = AudioCaptureTrack(manager=self)
        self.current_audio_track = audio_track
        pc.addTrack(audio_track)

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                logger.info("Received an audio track from browser")

                async def play_track():
                    resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
                    while True:
                        try:
                            frame = await track.recv()
                            frame.pts = None
                            for resampled_frame in resampler.resample(frame):
                                audio_bytes = resampled_frame.to_ndarray().tobytes()
                                await self.write_output_safe(audio_bytes)
                        except Exception as e:
                            logger.info(f"Track playback ended/error: {e}")
                            break

                asyncio.create_task(play_track())

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
