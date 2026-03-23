from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from radio_manager import RadioManager
import asyncio
from pydantic import BaseModel
import os
import json
import uuid
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from webrtc_manager import WebRTCManager

app = FastAPI(title="UV-K5 Remote Radio Node")
radio = RadioManager()
rtc_manager = WebRTCManager()

@app.on_event("startup")
async def startup_event():
    # 程序启动时立即连接固定串口
    from radio_manager import logger
    logger.info("Auto-connecting to Radio on /dev/ttyUSB0...")
    await radio.connect("/dev/ttyUSB0")
    logger.info("Starting Persistent Audio Streams...")
    await rtc_manager.start_audio_streams()

# 允许跨域请求（方便前后端分离调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectRequest(BaseModel):
    port: str = None  # 如果为 None，将使用 RadioManager 中的默认配置

class ChannelConfig(BaseModel):
    freq_hz: int
    tx_off_dir: int
    tx_off_freq: int
    bw: int
    rx_tone_type: int
    rx_tone_code: int
    tx_tone_type: int
    tx_tone_code: int
    power: int = 0

class SquelchConfig(BaseModel):
    level: int

class MonitorConfig(BaseModel):
    on: bool

class RTCRequest(BaseModel):
    sdp: str
    type: str
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None

class MemoryChannel(BaseModel):
    id: Optional[str] = None
    name: str
    freq_hz: int
    tx_off_dir: int
    tx_off_freq: int
    bw: int
    rx_tone_type: int
    rx_tone_code: int
    tx_tone_type: int
    tx_tone_code: int
    power: int

MEMORIES_FILE = os.path.join(os.path.dirname(__file__), "memories.json")

def load_memories():
    if not os.path.exists(MEMORIES_FILE):
        return []
    try:
        with open(MEMORIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_memories(data):
    with open(MEMORIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get("/api/audio/devices")
async def get_audio_devices():
    """获取所有可用的声卡设备列表"""
    devices = rtc_manager.get_audio_devices()
    return {"devices": devices}

@app.post("/api/rtc/offer")
async def rtc_offer(req: RTCRequest):
    """WebRTC 专属握手通道 (SDP 打洞)"""
    answer = await rtc_manager.handle_offer(
        req.sdp, 
        req.type, 
        input_device_index=req.input_device_index,
        output_device_index=req.output_device_index
    )
    return answer

@app.get("/api/ports")
async def get_ports():
    return {"ports": RadioManager.list_ports()}

@app.get("/api/status")
async def get_status():
    return {
        "connected": radio.connected,
        "port": radio.port,
        "os": os.name
    }

@app.post("/api/connect")
async def connect_radio(req: ConnectRequest):
    success = await radio.connect(req.port)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to connect to the radio")
    return {"status": "success", "port": radio.port}

@app.post("/api/disconnect")
async def disconnect_radio():
    # await radio.disconnect()
    return {"status": "Action restricted: Device is set to always connected."}

@app.get("/api/channel/{channel_id}")
async def get_channel(channel_id: int):
    # channel_id 0 为 VFO A, 1 为 VFO B
    data = await radio.get_channel(channel_id)
    if data is None:
        raise HTTPException(status_code=400, detail="Failed to get channel or radio disconnected")
    return data

@app.post("/api/channel/{channel_id}")
async def set_channel(channel_id: int, config: ChannelConfig):
    success = await radio.set_channel(
        channel_id,
        config.freq_hz, config.tx_off_dir, config.tx_off_freq,
        config.bw, config.rx_tone_type, config.rx_tone_code,
        config.tx_tone_type, config.tx_tone_code, config.power
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set channel")
    return {"status": "success"}

@app.get("/api/active_channel")
async def get_active_channel():
    channel = await radio.get_active_channel()
    if channel is None:
        raise HTTPException(status_code=400, detail="Failed to get active channel")
    return {"channel": channel}

@app.post("/api/active_channel/{channel_id}")
async def set_active_channel(channel_id: int):
    success = await radio.set_active_channel(channel_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set active channel")
    return {"status": "success"}

@app.get("/api/squelch")
async def get_squelch():
    level = await radio.get_squelch()
    if level is None:
        raise HTTPException(status_code=400, detail="Failed to get squelch")
    return {"level": level}

@app.post("/api/squelch")
async def set_squelch(config: SquelchConfig):
    success = await radio.set_squelch(config.level)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set squelch")
    return {"status": "success"}

@app.get("/api/monitor")
async def get_monitor():
    on = await radio.get_monitor()
    if on is None:
        raise HTTPException(status_code=400, detail="Failed to get monitor")
    return {"on": on}

@app.post("/api/monitor")
async def set_monitor(config: MonitorConfig):
    success = await radio.set_monitor(config.on)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set monitor")
    return {"status": "success"}

@app.get("/api/memories")
async def get_memories():
    return load_memories()

@app.post("/api/memories")
async def add_memory(mem: MemoryChannel):
    mem.id = str(uuid.uuid4())
    data = load_memories()
    data.append(mem.model_dump())
    save_memories(data)
    return mem.model_dump()

@app.put("/api/memories/{mem_id}")
async def update_memory(mem_id: str, mem: MemoryChannel):
    data = load_memories()
    for idx, item in enumerate(data):
        if item.get('id') == mem_id:
            mem.id = mem_id
            data[idx] = mem.model_dump()
            save_memories(data)
            return data[idx]
    raise HTTPException(status_code=404, detail="Memory not found")

@app.delete("/api/memories/{mem_id}")
async def delete_memory(mem_id: str):
    data = load_memories()
    filtered = [item for item in data if item.get('id') != mem_id]
    if len(filtered) == len(data):
        raise HTTPException(status_code=404, detail="Memory not found")
    save_memories(filtered)
    return {"status": "success"}

@app.post("/api/memories/{mem_id}/apply")
async def apply_memory(mem_id: str):
    data = load_memories()
    memory = next((item for item in data if item.get('id') == mem_id), None)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    active_ch = await radio.get_active_channel()
    if active_ch is None:
        raise HTTPException(status_code=400, detail="Radio disconnected")
    
    success = await radio.set_channel(
        active_ch,
        memory['freq_hz'], memory['tx_off_dir'], memory['tx_off_freq'],
        memory['bw'], memory['rx_tone_type'], memory['rx_tone_code'],
        memory['tx_tone_type'], memory['tx_tone_code'], memory['power']
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to apply memory to radio")
    return {"status": "success"}

@app.websocket("/ws/control")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket client connected")
    try:
        while True:
            # 接收前端发送的控制指令 JSON (例如: {"cmd": "ptt", "state": true})
            data = await websocket.receive_json()
            cmd = data.get("cmd")
            
            if cmd == "ptt":
                state = data.get("state", False)
                success = await radio.set_ptt(state)
                await websocket.send_json({"event": "ptt_changed", "state": state, "success": success})
            elif cmd == "get_rssi":
                rssi = await radio.get_rssi()
                await websocket.send_json({"event": "rssi", "value": rssi})
            else:
                await websocket.send_json({"error": "Unknown command"})
                
    except WebSocketDisconnect:
        print("WebSocket client disconnected")
        # 安全脱离：如果网页强行关闭了，但是对讲机还在发射，我们赶快拉黑 PTT 防止烧管
        await radio.set_ptt(False)

    except Exception as e:
        print(f"WebSocket error: {e}")
        await radio.set_ptt(False)

# ======= 挂载前端静态文件 =======
# 确保在API定义之后挂载，否则路由可能会被覆盖拦截
if os.path.exists(os.path.join(os.path.dirname(__file__), "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

@app.get("/")
async def serve_frontend():
    """访问根目录时直接返回前端 Vue 页面"""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

if __name__ == "__main__":
    import uvicorn
    cert_file = os.path.join(os.path.dirname(__file__), "cert.pem")
    key_file = os.path.join(os.path.dirname(__file__), "key.pem")
    
    # 自动探测是否有 HTTPS 证书，如果有则挂载 SSL 运行
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("🚀 检测到 SSL 证书，将以 HTTPS 模式启动！解决手机麦克风无法访问的问题。")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, 
                    ssl_keyfile=key_file, ssl_certfile=cert_file)
    else:
        print("⚠️ 未检测到 SSL 证书，以普通 HTTP 模式启动（适合本机 localhost 测试）。")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
