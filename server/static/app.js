const { createApp, ref, reactive, onMounted, computed } = Vue;

const app = createApp({
    setup() {
        const connected = ref(false);
        const ports = ref([]);
        const audioDevices = ref([]);
        
        const selectedPort = ref(null);
        // 如果没有选择声卡，默认 null 将交给系统去处理
        const audioInput = ref(null);
        const audioOutput = ref(null);

        // 电台状态
        const channels = reactive({ 0: null, 1: null });
        const activeChannel = ref(0);
        const squelch = ref(3);
        const monitorOn = ref(false);
        const isPtt = ref(false);
        const rssi = ref(-130);

        const rtcConnected = ref(false);
        let ws = null;
        let pc = null;
        let localStream = null;

        // 频道管理相关状态
        const showMemories = ref(false);
        const showEditor = ref(false);
        const memories = ref([]);
        
        // 亚音字典常量（对讲机标准顺序）
        const CTCSS_TONES = ["67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5", "91.5", "94.8", "97.4", "100.0", "103.5", "107.2", "110.9", "114.8", "118.8", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2", "151.4", "156.7", "159.8", "162.2", "165.5", "167.9", "171.3", "173.8", "177.3", "179.9", "183.5", "186.2", "189.9", "192.8", "196.6", "199.5", "203.5", "206.5", "210.7", "218.1", "225.7", "229.1", "233.6", "241.8", "250.3", "254.1"];
        const DCS_CODES = ["023", "025", "026", "031", "032", "036", "043", "047", "051", "053", "054", "065", "071", "072", "073", "074", "114", "115", "116", "122", "125", "131", "132", "134", "143", "145", "152", "155", "156", "162", "165", "172", "174", "205", "212", "223", "225", "226", "243", "244", "245", "246", "251", "252", "255", "261", "263", "265", "266", "271", "274", "306", "311", "315", "325", "331", "332", "343", "346", "351", "356", "364", "365", "371", "411", "412", "413", "423", "431", "432", "445", "446", "452", "454", "455", "462", "464", "465", "466", "503", "506", "516", "523", "526", "532", "546", "565", "606", "612", "624", "627", "631", "632", "654", "662", "664", "703", "712", "723", "731", "732", "734", "743", "754"];

        const memoryForm = reactive({
            id: null,
            name: '',
            freq_mhz: 430.0000,
            tx_off_dir: 0,
            tx_off_freq_mhz: 0.0000,
            bw: 0,
            power: 2,
            rx_tone_type: 0,
            rx_tone_code: 0,
            tx_tone_type: 0,
            tx_tone_code: 0
        });

        // 与当前网页域名保持一致
        const baseUrl = ""; 

        // 统一的 API 请求包装
        const api = async (endpoint, options = {}) => {
            const res = await fetch(`${baseUrl}/api${endpoint}`, {
                headers: { 'Content-Type': 'application/json' },
                ...options
            });
            if (!res.ok) throw new Error(await res.text());
            return res.json();
        };

        // 一进页面就拉取备选项
        const loadInitData = async () => {
            try {
                const resPorts = await api('/ports');
                ports.value = resPorts.ports;
                if (ports.value.length > 0 && !selectedPort.value) {
                    selectedPort.value = ports.value[0].device;
                }

                const resAudio = await api('/audio/devices');
                audioDevices.value = resAudio.devices;
            } catch (e) {
                console.error("加载设备数据失败", e);
            }
        };

        // 检查后端是否已经被别人连接了，如果已连接我们直接切入面板
        const checkStatus = async () => {
            try {
                const res = await api('/status');
                connected.value = res.connected;
                if (res.connected) {
                    await initRadioState();
                    initWebSocket();
                    initWebRTC();
                }
            } catch(e) {}
        };

        onMounted(() => {
            loadInitData();
            checkStatus();
        });

        // ======= 操作流程 =======

        const connectDevice = async () => {
            try {
                await api('/connect', {
                    method: 'POST',
                    body: JSON.stringify({ port: selectedPort.value })
                });
                connected.value = true;
                // 这三步是唤醒界面的核心
                await initRadioState(); 
                initWebSocket();
                initWebRTC();
            } catch(e) {
                alert("设备连接异常: " + (e.message || e));
            }
        };

        const initRadioState = async () => {
            try {
                channels[0] = await api('/channel/0');
                channels[1] = await api('/channel/1');
                // 主动拉取存储好的频道簿
                memories.value = await api('/memories');
                
                const actRes = await api('/active_channel');
                activeChannel.value = actRes.channel;

                const sqRes = await api('/squelch');
                squelch.value = sqRes.level;

                const monRes = await api('/monitor');
                monitorOn.value = monRes.on;
            } catch(e) {
                console.error("同步电台参数失败", e);
            }
        };

        // ======= WebSocket (超低延迟下发指令 + 信号上报) =======
        
        const initWebSocket = () => {
            const protocol = window.location.protocol === "https:" ? "wss" : "ws";
            const wsUrl = `${protocol}://${window.location.host}/ws/control`;
            ws = new WebSocket(wsUrl);
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.event === "rssi") {
                    rssi.value = data.value;
                } else if (data.event === "ptt_changed") {
                    // 后端确认完成 PTT 动作抛回的事件
                }
            };

            // 暂时关闭每 200ms 的 RSSI 轮询查询
            /*
            setInterval(() => {
                if (ws.readyState === WebSocket.OPEN && !isPtt.value) {
                    // 发射期不查，否则串口冲突
                    ws.send(JSON.stringify({ cmd: "get_rssi" }));
                }
            }, 200);
            */
        };

        // ======= WebRTC (获取网页麦克风 + 播放电台来的声音) =======
        
        const initWebRTC = async () => {
            pc = new RTCPeerConnection({
                // Google的免费打洞服务器，在内网穿透或者在公网访问时保证连接
                iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
            });

            pc.onconnectionstatechange = () => {
                rtcConnected.value = (pc.connectionState === 'connected');
            };

            // 获取你的笔记本或者手机上的麦克风对象（开启了回声消除）
            try {
                localStream = await navigator.mediaDevices.getUserMedia({ 
                    audio: { echoCancellation: true, noiseSuppression: true } 
                });
                localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
            } catch(e) {
                alert("对不起，无权访问您的麦克风。请在浏览器设置中授权本页面录音。\n或者确保您以 https 或 localhost/127.0.0.1 访问本页！");
                return;
            }

            // 监听：后端一旦发来了电台的声音，立刻绑定到那个隐藏的 <audio> 标签上播放
            const remoteStream = new MediaStream();
            const remoteAudio = document.getElementById('remoteAudio');
            remoteAudio.srcObject = remoteStream;

            pc.ontrack = (event) => {
                console.log("📡 接收到来自电台的音频轨道:", event.track.kind);
                remoteStream.addTrack(event.track);
                
                // 强制尝试播放，解决部分手机浏览器要求用户交互后才能发声的限制
                remoteAudio.play().catch(e => {
                    console.warn("⚠️ 自动播放可能被浏览器拦截:", e);
                });
            };

            // 标准的 WebRTC "Offer-Answer" 谈判流程
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);

            try {
                // 原来可能因为没选音频设备，传过去的是 null
                // FastAPI 验证发现类型对不上或者没默认值报错 422
                // 我们确保这里能正确传递即使是 null
                const reqBody = {
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type
                };
                if (audioInput.value !== null) reqBody.input_device_index = audioInput.value;
                if (audioOutput.value !== null) reqBody.output_device_index = audioOutput.value;

                const response = await api('/rtc/offer', {
                    method: 'POST',
                    body: JSON.stringify(reqBody)
                });
                await pc.setRemoteDescription(new RTCSessionDescription(response));
            } catch (e) {
                console.error("WebRTC信令握手失败", e);
            }
        };

        // ======= UI 点击事件回调 =======
        
        const startPtt = () => {
            if (!connected.value) return;
            isPtt.value = true;
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ cmd: "ptt", state: true }));
            }
        };

        // 松手时，发送关闭指令
        const stopPtt = () => {
            if (!connected.value || !isPtt.value) return;
            isPtt.value = false;
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ cmd: "ptt", state: false }));
            }
        };

        const toggleActiveChannel = async () => {
            const next = activeChannel.value === 0 ? 1 : 0;
            await api(`/active_channel/${next}`, { method: 'POST' });
            activeChannel.value = next;
            // 重新刷新下数据，保证数字更新
            channels[next] = await api(`/channel/${next}`);
        };

        const toggleMonitor = async () => {
            const next = !monitorOn.value;
            await api('/monitor', { method: 'POST', body: JSON.stringify({ on: next }) });
            monitorOn.value = next;
        };

        const setSquelch = async () => {
            // UI进度条滑动松开后触发
            await api('/squelch', { method: 'POST', body: JSON.stringify({ level: parseInt(squelch.value) }) });
        };


        // ======= 频道管理逻辑 =======
        
        const openMemories = () => {
            // 防止网页下面也能滚动
            showMemories.value = true;
        };

        const availableTones = (toneType) => {
            if (toneType === 1) return CTCSS_TONES;
            if (toneType === 2 || toneType === 3) return DCS_CODES;
            return [];
        };

        const createMemory = () => {
            Object.assign(memoryForm, {
                id: null, name: '新频道', freq_mhz: 430.0000,
                tx_off_dir: 0, tx_off_freq_mhz: 0, bw: 0, power: 2,
                rx_tone_type: 0, rx_tone_code: 0, tx_tone_type: 0, tx_tone_code: 0
            });
            showEditor.value = true;
        };

        const editMemory = (mem) => {
            Object.assign(memoryForm, {
                id: mem.id,
                name: mem.name,
                freq_mhz: mem.freq_hz / 1000000,
                tx_off_dir: mem.tx_off_dir,
                tx_off_freq_mhz: mem.tx_off_freq / 1000000,
                bw: mem.bw,
                power: mem.power,
                rx_tone_type: mem.rx_tone_type,
                rx_tone_code: mem.rx_tone_code,
                tx_tone_type: mem.tx_tone_type,
                tx_tone_code: mem.tx_tone_code
            });
            showEditor.value = true;
        };

        const saveMemory = async () => {
            const payload = {
                name: memoryForm.name,
                freq_hz: Math.round(memoryForm.freq_mhz * 1000000),
                tx_off_dir: memoryForm.tx_off_dir,
                tx_off_freq: Math.round(memoryForm.tx_off_freq_mhz * 1000000),
                bw: memoryForm.bw, power: memoryForm.power,
                rx_tone_type: memoryForm.rx_tone_type, rx_tone_code: memoryForm.rx_tone_code,
                tx_tone_type: memoryForm.tx_tone_type, tx_tone_code: memoryForm.tx_tone_code
            };

            if (memoryForm.id) {
                await api(`/memories/${memoryForm.id}`, { method: 'PUT', body: JSON.stringify(payload) });
            } else {
                await api('/memories', { method: 'POST', body: JSON.stringify(payload) });
            }
            memories.value = await api('/memories');
            showEditor.value = false;
        };

        const deleteMemory = async (id) => {
            if(!confirm("确定要删除这个频道吗？")) return;
            await api(`/memories/${id}`, { method: 'DELETE' });
            memories.value = await api('/memories');
            showEditor.value = false;
        };

        const applyMemory = async (mem) => {
            try {
                await api(`/memories/${mem.id}/apply`, { method: 'POST' });
                // 更新当前面板显示的频率
                channels[activeChannel.value] = await api(`/channel/${activeChannel.value}`);
                showMemories.value = false; // 退出抽屉
            } catch(e) {
                alert("上机失败：" + e.message);
            }
        };

        // ======= 计算与工具函数 =======

        // 把整数的 hz 转换成好看的形式 (例如 430125000 -> 430.1250 )
        const formatFreq = (hz) => {
            if (!hz) return "---.----";
            // 补齐 4 位小数
            return (hz / 1000000).toFixed(4); 
        };

        // 根据 -130 dBm (无信号) 到 -50 dBm (满格) 换算百分比
        const rssiPercent = computed(() => {
            let v = rssi.value;
            // UV-K5 大约这在个物理范围内
            if (v < -130) v = -130;  
            if (v > -40) v = -40;
            return ((v - (-130)) / 90) * 100;
        });

        return {
            connected, rtcConnected, ports, audioDevices,
            selectedPort, audioInput, audioOutput,
            channels, activeChannel, squelch, monitorOn, isPtt, rssi, rssiPercent,
            connectDevice, startPtt, stopPtt, toggleActiveChannel, toggleMonitor, setSquelch,
            formatFreq, showMemories, showEditor, memories, memoryForm,
            openMemories, createMemory, editMemory, saveMemory, deleteMemory, applyMemory, availableTones
        };
    }
});
app.mount('#app');