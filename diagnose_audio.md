# 音频播放问题诊断指南

## 问题现状
- ✅ 后端与 OpenAI Realtime API 通信正常，能收到 response.audio.done 事件
- ✅ 前端能收到并显示 AI 的文字转写（response.audio_transcript.delta）
- ❌ 前端无法播放 AI 的语音

## 诊断步骤

### 1. 在浏览器 Console 中检查音频数据接收

打开面试页面，开启浏览器开发者工具的 Console，观察以下日志：

```javascript
// 检查是否收到音频数据
// 应该看到类似这样的日志：
[TTS] response.audio.delta chunk # 1 base64 length = 2048
[TTS] response.audio.delta chunk # 2 base64 length = 2048
...

// 如果看不到这些日志，说明前端没有收到音频数据
```

### 2. 检查 AudioContext 状态

在 Console 中执行：

```javascript
// 检查 AudioContext 是否正常运行
document.querySelector('[data-testid="audio-context-state"]')?.textContent ||
console.log('请在面试开始后，打开 Console 执行以下命令检查 AudioContext 状态');

// 手动检查（面试进行中执行）
if (window.audioContextRef?.current) {
    console.log('AudioContext state:', window.audioContextRef.current.state);
    console.log('AudioContext currentTime:', window.audioContextRef.current.currentTime);
    console.log('AudioContext sampleRate:', window.audioContextRef.current.sampleRate);

    // 尝试手动恢复
    if (window.audioContextRef.current.state === 'suspended') {
        window.audioContextRef.current.resume().then(() => {
            console.log('AudioContext resumed successfully');
        });
    }
}
```

### 3. 检查音频解码和播放

查看 Console 中是否有以下日志：

```javascript
// 成功解码的日志
[TTS] Decoded audio chunk: samples = 512 firstSample = 0.00123

// 播放调度的日志
[TTS] Scheduling audio playback at 1.5 currentTime = 1.0 duration = 0.5

// 如果有错误
[TTS] Failed to decode base64 audio: ...
[TTS] Failed to start audio source: ...
```

### 4. 添加更多调试信息

在前端代码 Interview.tsx 的 enqueueAudio 函数中添加更多日志：

```typescript
// 在第 446 行后添加
source.connect(audioContextRef.current.destination);

// 添加调试代码
source.onended = () => {
  console.log('[TTS] Audio source ended at', audioContextRef.current.currentTime);
};

// 检查音频是否真的有声音
const maxSample = Math.max(...float32.map(Math.abs));
console.log('[TTS] Max sample value:', maxSample);
if (maxSample < 0.001) {
  console.warn('[TTS] Audio chunk appears to be silent!');
}
```

### 5. 测试音频播放功能

在 Console 中手动测试音频播放：

```javascript
// 创建测试音频
const testAudio = () => {
    const ctx = new AudioContext({ sampleRate: 16000 });
    const oscillator = ctx.createOscillator();
    oscillator.frequency.value = 440; // A4 音符
    oscillator.connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.5);
    console.log('Test audio played. Did you hear a beep?');
    console.log('AudioContext state:', ctx.state);
};
testAudio();
```

## 可能的解决方案

### 方案 1: 确保 AudioContext 在用户交互后创建和恢复

```typescript
// 在 startInterview 函数中，确保在用户点击后立即恢复
if (audioContext.state === 'suspended') {
    await audioContext.resume();
    // 添加重试逻辑
    let retries = 0;
    while (audioContext.state === 'suspended' && retries < 3) {
        await new Promise(resolve => setTimeout(resolve, 100));
        await audioContext.resume();
        retries++;
    }
    console.log('[TTS] AudioContext state after retries:', audioContext.state);
}
```

### 方案 2: 检查音频数据完整性

在前端 WebSocket 消息处理中添加验证：

```typescript
if (data.type === 'response.audio.delta') {
    if (!data.audio) {
        console.error('[TTS] Missing audio data in response.audio.delta');
        return;
    }

    // 验证 base64 格式
    try {
        const test = atob(data.audio);
        console.log('[TTS] Audio data validated, byte length:', test.length);
    } catch (e) {
        console.error('[TTS] Invalid base64 audio data:', e);
        return;
    }

    enqueueAudio(data.audio);
}
```

### 方案 3: 添加音频播放状态监控

```typescript
// 添加一个全局变量跟踪播放状态
let activeSourceCount = 0;

// 在 enqueueAudio 中
source.onended = () => {
    activeSourceCount--;
    console.log('[TTS] Source ended, active sources:', activeSourceCount);
};
activeSourceCount++;
console.log('[TTS] Source started, active sources:', activeSourceCount);
```

## 快速修复建议

1. **立即尝试**：在面试页面打开后，在 Console 中执行：
   ```javascript
   localStorage.setItem('debug', 'true');  // 启用详细日志
   ```

2. **检查浏览器设置**：
   - 确保网站有音频播放权限
   - 检查浏览器是否静音
   - 尝试使用 Chrome/Edge（对 Web Audio API 支持最好）

3. **验证音频流**：
   在后端 realtime.py 中添加日志验证音频数据存在：
   ```python
   if event_type == "response.audio.delta":
       audio_data = event.get("audio", "")
       logger.info(f"Forwarding audio delta, base64 length: {len(audio_data)}")
   ```

## 需要收集的信息

请提供以下信息以便进一步诊断：

1. 浏览器 Console 中的完整日志（特别是 [TTS] 开头的）
2. 浏览器版本和操作系统
3. 是否在其他浏览器中测试过
4. 系统音量是否正常，其他网站音频是否可以播放
5. 网络延迟情况（可能影响音频块的接收）