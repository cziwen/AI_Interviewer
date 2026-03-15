# 故障排查指南

## 📋 目录

- [HTTP 与安全上下文问题](#http-与安全上下文问题)
- [音频问题](#音频问题)
- [WebSocket 连接问题](#websocket-连接问题)
- [OpenAI API 问题](#openai-api-问题)
- [VAD 问题](#vad-问题)
- [数据库问题](#数据库问题)
- [性能问题](#性能问题)

---

## 🔒 HTTP 与安全上下文问题

### 问题：复制按钮无效（Cannot read properties of undefined (reading 'writeText')）

#### 症状
- 管理后台创建面试后点击「复制链接」无反应或报错
- 浏览器控制台：`Uncaught TypeError: Cannot read properties of undefined (reading 'writeText')`

#### 原因
`navigator.clipboard`（Clipboard API）仅在 **安全上下文**（HTTPS 或 localhost）下可用。页面通过 HTTP 访问时，`navigator.clipboard` 为 `undefined`，导致复制失败。

#### 解决方案
- **生产环境**：必须使用 HTTPS。按 [deploy.md](../deploy.md) 配置 `DOMAIN`、`ACME_EMAIL` 后执行 `./deploy.sh`，由 Caddy 自动申请 Let's Encrypt 证书，访问 `https://<DOMAIN>`。
- **本地开发**：使用 `http://localhost` 访问时，Clipboard API 可用；若用 IP 或非 localhost 的 HTTP，复制可能同样不可用，可改为用 HTTPS 或 localhost。

---

### 问题：无法拿到本机设备（Error enumerating devices: getUserMedia undefined）

#### 症状
- 面试页「选择麦克风/扬声器」下拉为空，或控制台报错
- 控制台：`Error enumerating devices: TypeError: Cannot read properties of undefined (reading 'getUserMedia')`

#### 原因
`navigator.mediaDevices`（含 `getUserMedia`、`enumerateDevices`）仅在 **安全上下文**（HTTPS 或 localhost）下可用。通过 HTTP（且非 localhost）访问时，`navigator.mediaDevices` 为 `undefined`，无法枚举或使用音视频设备。

#### 解决方案
- **生产环境**：必须使用 HTTPS，同上。启用 Caddy + Let's Encrypt 后，使用 `https://<DOMAIN>` 访问即可正常选择与测试设备。
- **本地开发**：使用 `http://localhost` 可正常使用设备；若用 IP 或其它 HTTP 地址，请改用 localhost 或 HTTPS。

---

## 🎙️ 音频问题

### 问题1：听不到 AI 声音

#### 症状
- 前端显示 AI 转写文本
- 音量条没有变化
- 扬声器无声音输出

#### 排查步骤

**1. 检查浏览器控制台**

```javascript
// 查找 AudioContext 相关错误
[TTS] AudioContext state = suspended
[TTS] Failed to start audio source: InvalidStateError
```

**2. 检查 AudioContext 状态**

```typescript
console.log('AudioContext state:', audioContext.state);
// 应该是 'running'，如果是 'suspended' 说明被浏览器阻止
```

**3. 检查后端日志**

```
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio.done
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio_transcript.done - {"transcript":"您好..."}
```

- ✅ 如果有这些日志：OpenAI 已生成音频，问题在前端
- ❌ 如果没有这些日志：OpenAI 未生成音频，检查 session 配置

#### 解决方案

**A. AudioContext suspended（最常见）**

```typescript
// 在用户点击"开始面试"按钮时主动恢复
if (audioContext.state === 'suspended') {
  await audioContext.resume();
}
```

**已实现位置**：[frontend/src/pages/Interview.tsx:132-136](../../frontend/src/pages/Interview.tsx#L132)

**B. 浏览器自动播放策略**

- Chrome/Edge：需要用户交互后才能播放音频
- Safari：更严格，可能需要用户手动点击

**解决方案**：
```typescript
// 在任意用户交互（如点击按钮）中调用
document.addEventListener('click', async () => {
  if (audioContext.state === 'suspended') {
    await audioContext.resume();
  }
}, { once: true });
```

**C. 音频数据格式错误**

```javascript
// 检查 console.log
[TTS] Decoded audio chunk: samples = 0  // ← 问题：samples 为 0
[TTS] Failed to decode base64 audio: InvalidCharacterError
```

**解决方案**：
- 检查后端 `response.audio.delta` 字段名修正逻辑
- 确认 Base64 解码无误

**D. 设备输出问题**

- 检查系统音量和静音状态
- 更换扬声器设备
- 使用耳机测试

---

### 问题2：麦克风无输入

#### 症状
- 音量条始终为 0
- 后端未收到 `speech_started` 事件
- VAD 不触发

#### 排查步骤

**1. 检查浏览器权限**

```javascript
// 控制台查看
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => console.log('Mic OK:', stream))
  .catch(err => console.error('Mic Error:', err));
```

常见错误：
- `NotAllowedError`：用户拒绝权限
- `NotFoundError`：未找到麦克风设备
- `NotReadableError`：设备被其他应用占用

**2. 检查设备选择**

```typescript
// 确认选择了正确的设备
console.log('Selected microphone:', selectedMicrophone);
```

**3. 检查音频流状态**

```typescript
// 检查 MediaStream 是否激活
console.log('Stream active:', stream.active);
console.log('Audio tracks:', stream.getAudioTracks());
```

#### 解决方案

**A. 重新授权麦克风**

Chrome：
1. 点击地址栏左侧的锁图标
2. 网站设置 → 麦克风 → 允许
3. 刷新页面

Safari：
1. Safari → 设置 → 网站 → 麦克风
2. 选择允许
3. 刷新页面

**B. 设备被占用**

```bash
# Mac：查看占用麦克风的进程
lsof | grep "CoreAudio"

# 关闭其他使用麦克风的应用（Zoom、Skype等）
```

**C. 系统麦克风设置**

Mac：
- 系统设置 → 隐私与安全性 → 麦克风
- 确保浏览器有权限

Windows：
- 设置 → 隐私 → 麦克风
- 确保浏览器有权限

---

### 问题3：声音断续或卡顿

#### 症状
- AI 声音播放不连贯
- 有明显停顿或跳帧

#### 排查步骤

**1. 检查网络延迟**

```bash
# 测试到 OpenAI 的延迟
ping api.openai.com
```

**2. 检查 CPU 使用率**

```bash
# Mac/Linux
top

# Windows
任务管理器 → 性能
```

**3. 检查音频 buffer 日志**

```javascript
[TTS] Scheduling playback at 2.5, currentTime = 2.6  // ← 问题：已经晚了
```

#### 解决方案

**A. 网络问题**

- 使用有线网络代替 WiFi
- 检查网络带宽（至少 1 Mbps 上传/下载）
- 使用 VPN/代理优化到 OpenAI 的路由

**B. 浏览器性能**

- 关闭其他标签页和扩展
- 使用 Chrome/Edge（性能优于 Firefox/Safari）
- 增加 `ScriptProcessorNode` buffer size（当前 2048，可增至 4096）

**C. 音频队列优化**

```typescript
// 检查播放队列是否堆积
if (nextStartTimeRef.current - audioContext.currentTime > 5) {
  console.warn('Audio queue too long, dropping old chunks');
  nextStartTimeRef.current = audioContext.currentTime;
}
```

---

### 问题4：回声或重复

#### 症状
- AI 听到自己的声音
- AI 重复刚说过的话
- 出现对话循环

#### 排查步骤

**1. 检查半双工门控**

```javascript
// 浏览器控制台
[MIC] isAgentSpeaking = false  // ← 应该在 AI 说话时为 true
```

**2. 检查音频设备**

- 是否使用了扬声器（容易被麦克风采集）
- 推荐使用耳机

**3. 检查 VAD 日志**

```
INFO - VAD: Speech started for question 0
INFO - VAD: Speech stopped for question 0
INFO - VAD: Speech started for question 0  // ← 问题：立即又触发
```

#### 解决方案

**A. 半双工策略失效**

检查代码：[frontend/src/pages/Interview.tsx:244-263](../../frontend/src/pages/Interview.tsx#L244)

```typescript
// 确认此逻辑正常工作
const isAgentSpeaking = now < (nextStartTimeRef.current + 0.2);
if (isAgentSpeaking) {
  return; // 阻止发送音频
}
```

**B. 使用耳机**

- 耳机可以物理隔离扬声器和麦克风
- 彻底消除回声问题

**C. 增加缓冲时间**

```typescript
// 从 0.2 秒增加到 0.5 秒
const isAgentSpeaking = now < (nextStartTimeRef.current + 0.5);
```

---

## 🌐 WebSocket 连接问题

### 问题5：WebSocket 连接失败

#### 症状
```
WebSocket connection failed: Error in connection establishment
```

#### 排查步骤

**1. 检查后端是否启动**

```bash
curl http://localhost:8000/docs
# 应该返回 FastAPI 文档页面
```

**2. 检查 WebSocket URL**

```typescript
// 前端
const wsUrl = `ws://localhost:8000/api/realtime/ws/${token}`;
console.log('Connecting to:', wsUrl);
```

**3. 检查 token 有效性**

```bash
# 测试 token
curl http://localhost:8000/api/interviews/your_token_here
```

#### 解决方案

**A. 后端未启动**

```bash
cd backend
uvicorn app.main:app --reload
```

**B. Token 无效**

- 重新创建面试获取新 token
- 检查数据库中的 `link_token` 字段

**C. CORS 问题**

检查 `backend/app/main.py` 的 CORS 配置：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

### 问题6：WebSocket 意外断开

#### 症状
```
[WS] closed, code = 1006, reason =
```

#### 排查步骤

**1. 检查后端日志**

```
ERROR - Realtime session error for token abc123: ...
```

**2. 检查网络稳定性**

```bash
# 持续 ping 测试
ping -c 100 api.openai.com
```

#### 解决方案

**A. OpenAI API 超时**

- 面试时间过长（>30 分钟）
- 解决方案：分段面试或优化面试时长

**B. 后端异常**

- 检查后端日志找到具体错误
- 修复代码后重启服务

**C. 网络不稳定**

- 使用有线网络
- 实现 WebSocket 重连机制（可选）

---

## 🔑 OpenAI API 问题

### 问题7：API 调用失败

#### 症状
```
OpenAI Realtime Error: {
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "Invalid API Key"
  }
}
```

#### 排查步骤

**1. 验证 API Key**

```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**2. 检查环境变量**

```bash
# 后端目录
cat .env | grep OPENAI_API_KEY
```

**3. 检查 API 额度**

访问：https://platform.openai.com/usage

#### 解决方案

**A. API Key 错误**

- 从 OpenAI 平台重新生成 API Key
- 更新 `.env` 文件并重启后端

**B. 余额不足**

- 充值 OpenAI 账户
- 临时降级到免费模型（如果可用）

**C. API 限流**

```
{
  "error": {
    "type": "rate_limit_error",
    "message": "Rate limit exceeded"
  }
}
```

- 减少并发面试数量
- 升级 OpenAI 账户等级

---

## 🎤 VAD 问题

### 问题8：VAD 不触发

#### 症状
- 候选人说话但没有 `speech_started` 事件
- 后端日志无 VAD 相关记录

#### 排查步骤

**1. 检查麦克风输入**

```javascript
// 浏览器控制台
[MIC] onaudioprocess rms = 0.001  // ← 问题：音量太小
```

**2. 检查 VAD 配置**

```python
# backend/app/api/realtime.py
"turn_detection": {
    "threshold": 0.5,  // ← 可能太高
    "silence_duration_ms": 600
}
```

**3. 检查音频发送**

```javascript
// 确认音频正在发送
ws.send(JSON.stringify({ type: 'audio', audio: base64Audio }));
```

#### 解决方案

**A. 降低 VAD 阈值**

```python
"threshold": 0.3,  # 从 0.5 降低到 0.3
```

**B. 检查麦克风音量**

- 系统设置中提高麦克风输入音量
- 更换麦克风设备
- 靠近麦克风说话

**C. 检查半双工门控**

确认候选人说话时 `isAgentSpeaking = false`

---

### 问题9：VAD 频繁误触发

#### 症状
- 背景噪音也触发 `speech_started`
- VAD 过于敏感

#### 解决方案

**A. 提高 VAD 阈值**

```python
"threshold": 0.7,  # 从 0.5 提高到 0.7
```

**B. 改善录音环境**

- 在安静的房间进行面试
- 使用降噪麦克风
- 关闭空调、风扇等噪音源

---

## 💾 数据库问题

### 问题10：数据库连接失败

#### 症状
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) unable to open database file
```

#### 解决方案

**A. SQLite 文件路径错误**

```python
# .env
DATABASE_URL=sqlite:///./interview.db  # 确保路径正确
```

**B. 权限问题**

```bash
# 检查文件权限
ls -l interview.db

# 修改权限
chmod 666 interview.db
```

**C. 切换到 PostgreSQL**

```bash
# 安装依赖
pip install psycopg2-binary

# 更新 .env
DATABASE_URL=postgresql://user:pass@localhost/ai_interview
```

---

## ⚡ 性能问题

### 问题11：后端响应慢

#### 症状
- API 响应时间 >3 秒
- WebSocket 延迟高

#### 排查步骤

**1. 检查数据库查询**

```python
# 添加查询时间日志
import time
start = time.time()
interview = db.query(Interview).filter(...).first()
logger.info(f"Query time: {time.time() - start}s")
```

**2. 检查 OpenAI API 延迟**

```python
start = time.time()
response = await openai_api_call()
logger.info(f"OpenAI API time: {time.time() - start}s")
```

#### 解决方案

**A. 添加数据库索引**

```python
# backend/app/models/interview.py
link_token = Column(String, unique=True, index=True)  # ← 添加 index=True
```

**B. 使用连接池**

```python
# backend/app/database.py
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10
)
```

**C. 使用 Gunicorn + Uvicorn Workers**

```bash
gunicorn app.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

---

## 🔍 诊断工具

### 浏览器控制台命令

```javascript
// 1. 检查 WebSocket 状态
console.log('WS state:', wsRef.current?.readyState);
// 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED

// 2. 检查 AudioContext
console.log('AC state:', audioContextRef.current?.state);
console.log('AC time:', audioContextRef.current?.currentTime);
console.log('Next start:', nextStartTimeRef.current);

// 3. 手动触发音频恢复
audioContextRef.current?.resume();

// 4. 查看音量历史
// 在开发者工具中实时监控 volume state
```

### 后端诊断命令

```bash
# 1. 查看实时日志
tail -f logs/server_*.log

# 2. 搜索错误
grep ERROR logs/server_*.log

# 3. 统计 VAD 事件
grep "VAD:" logs/server_*.log | wc -l

# 4. 查看 WebSocket 连接数
ps aux | grep uvicorn
```

---

## 📞 获取帮助

如果以上方法无法解决问题：

1. **查看完整日志**：
   - 前端：浏览器控制台
   - 后端：`logs/server_*.log`

2. **检查相关文档**：
   - [实时面试功能](03_features/03.2_realtime_interview.md)
   - [音频处理](04_technical_details/04.2_audio_processing.md)
   - [半双工策略](04_technical_details/04.4_half_duplex_strategy.md)
   - 复制/设备在 HTTP 下不可用 → [HTTP 与安全上下文问题](#http-与安全上下文问题)；生产上 HTTPS → [deploy.md](../deploy.md)

3. **提交 Issue**：
   - 提供错误日志
   - 描述复现步骤
   - 说明环境信息（浏览器、OS、网络）

祝你顺利解决问题！🎉
