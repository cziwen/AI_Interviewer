# Frontend - AI 面试系统

基于 React 18 + TypeScript + Vite 的实时语音面试前端应用。

## 🎯 技术架构

### 核心技术栈
- **框架**：React 18 + TypeScript
- **构建工具**：Vite 4
- **路由**：React Router v6
- **音频处理**：Web Audio API
- **实时通信**：WebSocket

### 目录结构
```
frontend/
├── src/
│   ├── pages/
│   │   ├── Interview.tsx          # 候选人实时面试页
│   │   ├── InterviewDone.tsx      # 面试完成页
│   │   ├── AdminLogin.tsx         # HR 登录页
│   │   └── AdminInterviews.tsx    # HR 面试管理页
│   ├── api.ts                     # API 调用封装
│   ├── types.ts                   # TypeScript 类型定义
│   ├── App.tsx                    # 路由配置
│   └── main.tsx                   # 应用入口
├── package.json
└── vite.config.ts
```

## 🚀 快速开始

### 安装依赖
```bash
npm install
```

### 启动开发服务器
```bash
npm run dev
# 访问 http://localhost:5173
```

### 构建生产版本
```bash
npm run build
npm run preview  # 预览构建结果
```

## 🎙️ 核心功能实现

### 1. 实时语音面试 (`Interview.tsx`)

#### WebSocket 通信
```typescript
const ws = new WebSocket(`ws://localhost:8000/api/realtime/ws/${token}`);

// 发送音频流
ws.send(JSON.stringify({ type: 'audio', audio: base64Audio }));

// 接收 AI 响应
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'response.audio.delta') {
    enqueueAudio(data.audio); // 播放 AI 语音
  }
};
```

#### 音频采集与处理
- **采样率**：24kHz（匹配 OpenAI Realtime API）
- **格式**：PCM16（16-bit Linear PCM）
- **处理链路**：
  ```
  MediaStream → AudioContext → ScriptProcessorNode
    → Float32 → PCM16 → Base64 → WebSocket
  ```

#### 设备选择与测试
- **麦克风测试**：实时音量可视化（RMS 分析）
- **扬声器测试**：播放测试音（440Hz 正弦波）
- **设备枚举**：支持多设备选择

#### 半双工音频策略
```typescript
// 基于时间轴的智能门控
const isAgentSpeaking = audioContext.currentTime < nextStartTimeRef.current + 0.2;

if (isAgentSpeaking) {
  return; // 阻止发送音频到后端
}
```

### 2. HR 管理后台 (`AdminInterviews.tsx`)

- 面试列表展示（分页）
- 候选人信息查看
- 评分报告下载
- 面试状态管理

### 3. API 调用封装 (`api.ts`)

```typescript
// 创建面试
export const createInterview = (data: InterviewCreateRequest) =>
  fetch('/api/interviews/create', { method: 'POST', body: JSON.stringify(data) });

// 获取面试详情
export const getInterview = (token: string) =>
  fetch(`/api/interviews/${token}`).then(res => res.json());

// 完成面试
export const completeInterview = (token: string) =>
  fetch(`/api/interviews/${token}/complete`, { method: 'POST' });
```

## 🔧 关键技术点

### 1. 音频播放队列管理
```typescript
const enqueueAudio = (base64Audio: string) => {
  const audioBuffer = decodeBase64ToAudioBuffer(base64Audio);
  const source = audioContext.createBufferSource();
  source.buffer = audioBuffer;

  // 无缝衔接播放
  const startTime = Math.max(audioContext.currentTime, nextStartTimeRef.current);
  source.start(startTime);
  nextStartTimeRef.current = startTime + audioBuffer.duration;
};
```

### 2. 资源清理机制
```typescript
const cleanupInterview = () => {
  // 1. 关闭 WebSocket
  wsRef.current?.close();

  // 2. 停止音频轨道
  streamRef.current?.getTracks().forEach(t => t.stop());

  // 3. 断开音频节点
  processorRef.current?.disconnect();

  // 4. 关闭 AudioContext
  audioContextRef.current?.close();
};
```

### 3. 实时转写展示
```typescript
ws.onmessage = (event) => {
  if (data.type === 'response.audio_transcript.delta') {
    setTranscript(prev => prev + data.delta); // 逐字追加
  }
};
```

## 🎨 界面特性

- **设备测试界面**：面试前的设备选择和测试
- **音量可视化**：实时显示麦克风输入音量
- **AI 发言提示**：显示 AI 正在发言的状态
- **转写实时展示**：流式显示 AI 面试官的对话内容

## 🌐 环境配置

### 开发环境
```javascript
// vite.config.ts
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000'  // 代理后端 API
    }
  }
});
```

### 生产环境
需配置环境变量指向生产后端地址：
```bash
VITE_API_BASE_URL=https://your-backend.com
```

## 📱 浏览器兼容性

| 浏览器 | 版本要求 | 备注 |
|--------|---------|------|
| Chrome | 90+ | 推荐 |
| Edge | 90+ | 推荐 |
| Safari | 14+ | 需用户手动允许音频权限 |
| Firefox | 88+ | 部分设备选择功能受限 |

**关键 API 依赖**：
- Web Audio API
- MediaDevices API
- WebSocket API
- AudioContext with 24kHz sample rate support

## 🔍 调试指南

### 查看音频流日志
浏览器控制台输出关键日志：
```
[MIC] Stream acquired: xxx-xxx-xxx active: true
[TTS] response.audio.delta chunk #1, base64 length = 1024
[WS] Event: response.created
```

### 常见问题
1. **听不到 AI 声音**：检查 AudioContext 状态和浏览器自动播放策略
2. **麦克风无输入**：检查浏览器权限和设备选择
3. **回声问题**：确认半双工策略是否正常工作

详见：[../spec_doc/06_troubleshooting.md](../spec_doc/06_troubleshooting.md)

## 📚 相关文档

- [系统架构](../spec_doc/02_architecture.md)
- [实时面试功能](../spec_doc/03_features/03.2_realtime_interview.md)
- [音频处理技术](../spec_doc/04_technical_details/04.2_audio_processing.md)
- [半双工策略](../spec_doc/04_technical_details/04.4_half_duplex_strategy.md)
