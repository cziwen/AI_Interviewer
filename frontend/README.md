# Frontend - AI Interviewer

基于 React + Vite 的 AI 面试系统前端。

## 升级说明：实时语音面试 (Realtime Voice)

前端已从“录音-上传”模式升级为基于 **WebSocket** 的实时语音流交互模式。

### 关键技术实现
- **WebSocket 通信**：通过 `/api/realtime/ws/{token}` 与后端建立持久连接。
- **Web Audio API**：
  - 实时采集麦克风音频并转换为 PCM16 格式发送。
  - 接收后端下发的 base64 音频流并实时解码播放。
- **流式文本展示**：实时显示 AI 面试官的语音转写内容。

## 开发指南

### 运行
```bash
npm install
npm run dev
```

### 核心页面
- `src/pages/Interview.tsx`: 实时语音面试主页面。
- `src/pages/AdminInterviews.tsx`: HR 面试列表管理。

### 环境变量
默认连接后端地址：`http://localhost:8000/api`
WebSocket 地址：`ws://localhost:8000/api/realtime/ws`
