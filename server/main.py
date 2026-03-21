from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from radio_manager import RadioManager
import asyncio
from pydantic import BaseModel
import os

app = FastAPI(title="UV-K5 Remote Radio Node")
radio = RadioManager()

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
    await radio.disconnect()
    return {"status": "disconnected"}

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

    except Exception as e:
        print(f"WebSocket error: {e}")

if __name__ == "__main__":
    import uvicorn
    # 为了保证能对外访问，绑定在 0.0.0.0，双系统下开发也可在 localhost 访问
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
