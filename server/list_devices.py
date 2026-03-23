# -*- coding: utf-8 -*-
import sys

try:
    import serial.tools.list_ports
except ImportError:
    print("pyserial is not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    import pyaudio
except ImportError:
    print("pyaudio is not installed. Run: pip install pyaudio")
    sys.exit(1)

def main():
    print("=================== 串口设备列表 (Serial Ports) ===================")
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("未找到任何串口设备 (No serial ports found).")
    for p in ports:
        print("设备路径 (Device): " + p.device)
        print("  描述 (Description): " + p.description)
        print("  硬件ID (HWID): " + p.hwid + "\n")

    print("=================== 音频设备列表 (Audio Devices) ===================")
    try:
        p = pyaudio.PyAudio()
        count = p.get_device_count()
        if count == 0:
            print("未找到任何音频设备 (No audio devices found).")
        for i in range(count):
            info = p.get_device_info_by_index(i)
            print("名称 (Name): '" + str(info.get('name')) + "'")
            print("  索引 (Index): " + str(i))
            print("  输入通道 (Max Input Channels): " + str(info.get('maxInputChannels')))
            print("  输出通道 (Max Output Channels): " + str(info.get('maxOutputChannels')))
            print("  默认采样率 (Default Sample Rate): " + str(info.get('defaultSampleRate')) + "\n")
        p.terminate()
    except Exception as e:
        print("访问音频设备时出错 (Error accessing audio devices): " + str(e))

    print("====================================================================")
    print("1. 请从中挑选出你要连接的电台控制串口路径（例如 /dev/ttyUSB0），将其填入 config.json 的 serial_port 中。")
    print("2. 请从中挑选出你要连接的 USB 声卡的部分或完整名称（例如 AB13X USB Audio），将其填入 config.json 的 audio_device 中。")

if __name__ == "__main__":
    main()
