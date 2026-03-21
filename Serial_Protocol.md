# 串口控制协议文档 (Serial Protocol Documentation)

## 1. 连接参数 (Connection Settings)
*   **波特率 (Baud Rate)**: 38400 bps
*   **数据位 (Data Bits)**: 8
*   **停止位 (Stop Bits)**: 1
*   **校验位 (Parity)**: None
*   **流控 (Flow Control)**: None

## 2. 数据包协议 (Packet Structure)

通信采用“请求-响应”模式。
数据包格式为 Little Endian (低位在前)。

### 2.1 帧格式 (Frame Format)

| 偏移 (Offset) | 长度 (Bytes) | 字段 (Field) | 说明 (Description) |
| :--- | :--- | :--- | :--- |
| 0 | 2 | **Header ID** | 指令 ID (Little Endian). 例: `0x0830` -> `30 08` |
| 2 | 2 | **Size** | Header(4) + Data 的总长度. (Little Endian) |
| 4 | N | **Data** | 指令载荷 (Payload) |
| 4+N | 2 | **CRC** | CRC-16 校验和 (覆盖偏移 0 到 3+N) |

### 2.2 加密与混淆 (Encryption / Obfuscation)
默认情况下，UV-K5 的串口通信是“加密”的。这实际上是一个简单的 XOR 混淆。
在计算 CRC 之前，发送方和接收方都需要将数据包内容（**除最后2字节CRC外的所有字节**）与以下 16 字节密钥进行 XOR 运算：

**XOR Key**:
```
0x16, 0x6C, 0x14, 0xE6, 0x2E, 0x91, 0x0D, 0x40, 
0x21, 0x35, 0xD5, 0x40, 0x13, 0x03, 0xE9, 0x80
```
(密钥循环使用，即 `Payload[i] ^ Key[i % 16]`)

**推荐做法**:
每次连接建立后，首先发送 **握手指令 (ID: 0x0514)**。
*   该指令发送时仍需加密。
*   设备收到该指令后，会回复版本信息，并将后续通信切换为**明文模式**（不再 XOR）。
*   这样后续发送控制指令时就不需要进行 XOR 运算了。

---

## 3. 指令详解 (Commands)

### 3.1 握手 (Handshake) / 获取版本
*   **ID**: `0x0514`
*   **总长度 (Size)**: 8 (Header 4 + Data 4)
*   **Data**:
    *   `Timestamp` (4 bytes): 时间戳，可填 `00 00 00 00`。
*   **作用**: 解除加密模式，获取固件版本。

### 3.2 设置信道参数 (Set Channel Config)
*   **ID**: `0x0830`
*   **总长度 (Size)**: 19 (Header 4 + Data 15)
*   **Data 结构** (Packed struct, 15 bytes):

| 偏移 (Data内) | 字节数 | 类型 | 字段名 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| 0 | 1 | uint8 | **Channel** | `0` = 信道 A (上排)<br>`1` = 信道 B (下排) |
| 1 | 4 | uint32 | **Frequency** | 接收频率 (Hz)。<br>例: 438.500MHz = `438500000` |
| 5 | 1 | uint8 | **TxOffsetDir** | 发射差频方向:<br>`0` = 关闭 (OFF)<br>`1` = 正差频 (+)<br>`2` = 负差频 (-) |
| 6 | 4 | uint32 | **TxOffsetFreq**| 差频频率 (Hz) |
| 10 | 1 | uint8 | **Bandwidth** | 带宽:<br>`0` = 25kHz (Wide)<br>`1` = 12.5kHz (Narrow) |
| 11 | 1 | uint8 | **RxToneType** | 接收亚音类型:<br>`0` = NONE<br>`1` = CTCSS<br>`2` = DCS_N<br>`3` = DCS_I |
| 12 | 1 | uint8 | **RxToneCode** | 接收亚音值 (原始值或索引) |
| 13 | 1 | uint8 | **TxToneType** | 发射亚音类型 (同上) |
| 14 | 1 | uint8 | **TxToneCode** | 发射亚音值 (同上) |

*注意：此指令直接修改内存中的 VFO 设置，立即生效，但在重启后会恢复原状。*

### 3.3 读取信道参数 (Get Channel Config)
*   **ID**: `0x0831`
*   **总长度 (Size)**: 5 (Header 4 + Data 1)
*   **Data**:
    *   `Channel` (1 byte): `0` 或 `1`。

**回复 (Reply)**:
*   **ID**: `0x0832` (在 Payload 中体现)
*   **Data**: 同 `0x0830` 的结构，返回当前信道的实际参数。

### 3.4 PTT 控制 (PTT Control)
*   **ID**: `0x0840`
*   **总长度 (Size)**: 5 (Header 4 + Data 1)
*   **Data**:
    *   `PttState` (1 byte):
        *   `1`: 按下 PTT (开始发射)
        *   `0`: 松开 PTT (停止发射/回到接收)

---

## 4. 通信示例 (Example)

假设已完成握手（或者手动计算了 XOR）：

**目标**: 将信道 A 设置为 438.500 MHz, 无亚音, 无差频。
*   ID: `30 08`
*   Size: `13 00` (19 bytes)
*   Channel: `00`
*   Freq: 438500000 = `0x1A232CA0` -> Little Endian `A0 2C 23 1A`
*   其他全为 0。

**构建 Payload**:
`30 08 13 00 00 A0 2C 23 1A 00 00 00 00 00 00 00 00 00 00`

**计算 CRC**:
对上述 19 个字节计算 CRC-16 (XMODEM 或类似的算法，需参考固件源码 `driver/crc.c`)。
假设 CRC 为 `AB CD`。

**最终发送**:
`30 08 13 00 00 A0 2C 23 1A 00 00 00 00 00 00 00 00 00 00 cd ab`

(如果有加密，需对最后两个字节之前的 19 字节进行 XOR)。
