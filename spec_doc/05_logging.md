# 日志系统

## 📝 概述

本系统使用 Python `logging` 模块进行统一日志管理，记录所有关键事件、错误和调试信息。日志同时输出到文件和控制台，便于开发调试和生产环境排查问题。

## 🔧 日志配置

### Logger 设置

**代码位置**：[backend/app/utils/logger.py](../../backend/app/utils/logger.py)

```python
import logging
from datetime import datetime
from pathlib import Path

def setup_logger():
    """
    配置全局日志模块，每次启动生成独立的日志文件。
    """
    # 1. 确保日志目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 2. 生成带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"server_{timestamp}.log"

    # 3. 配置 logging
    logger = logging.getLogger("ai_interview")
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if not logger.handlers:
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger

# 创建全局 logger 实例
logger = setup_logger()
```

### 日志级别

| 级别 | 用途 | 示例 |
|-----|------|------|
| **DEBUG** | 详细调试信息 | 每个音频帧的详细数据 |
| **INFO** | 一般信息事件 | WebSocket 连接、VAD 事件 |
| **WARNING** | 警告信息 | API 调用接近限额 |
| **ERROR** | 错误信息 | 数据库连接失败 |
| **CRITICAL** | 严重错误 | 系统崩溃 |

**当前设置**：默认 `INFO` 级别

### 日志格式

**文件日志格式**：
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

**示例**：
```
2026-03-11 14:24:49,982 - ai_interview - INFO - WebSocket connected for token: abc123
```

**控制台日志格式**：
```
%(asctime)s - %(levelname)s - %(message)s
```

**示例**：
```
2026-03-11 14:24:49,982 - INFO - WebSocket connected for token: abc123
```

## 📂 日志文件管理

### 文件存储

```
backend/
├── logs/
│   ├── server_20260311_142449.log
│   ├── server_20260311_153022.log
│   └── server_20260311_164501.log
└── ...
```

### 文件命名规则

```
server_{YYYYMMDD}_{HHMMSS}.log
```

- `YYYYMMDD`：启动日期（年月日）
- `HHMMSS`：启动时间（时分秒）

### 日志轮转（可选）

对于长期运行的生产环境，建议配置日志轮转：

```python
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,           # 保留 5 个备份
    encoding="utf-8"
)
```

## 📋 关键日志事件

### 1. WebSocket 生命周期

#### 连接建立

```python
logger.info(f"WebSocket connected for token: {token}, Candidate: {interview.name}")
logger.info(f"Connecting to OpenAI Realtime for token: {token}")
logger.info(f"OpenAI Realtime connection established for token: {token}")
```

**示例日志**：
```
2026-03-11 14:24:49 - INFO - WebSocket connected for token: abc123, Candidate: 张三
2026-03-11 14:24:49 - INFO - Connecting to OpenAI Realtime for token: abc123
2026-03-11 14:24:50 - INFO - OpenAI Realtime connection established for token: abc123
```

#### 连接断开

```python
logger.info(f"Client disconnected: {token}")
logger.error(f"Realtime session error for token {token}: {e}")
```

### 2. OpenAI Realtime 事件

#### 会话事件

**代码位置**：[backend/app/api/realtime.py:206-210](../../backend/app/api/realtime.py#L206)

```python
# 记录所有非音频事件
if event_type in ["response.audio.delta", "response.audio_transcript.delta", "response.text.delta"]:
    pass  # 避免刷屏
else:
    logger.info(f"OpenAI Event: {event_type} - {json.dumps(event)}")
```

**示例日志**：
```
2026-03-11 14:24:50 - INFO - OpenAI Event: session.created - {"type":"session.created",...}
2026-03-11 14:24:50 - INFO - OpenAI Event: session.updated - {"type":"session.updated",...}
2026-03-11 14:24:50 - INFO - OpenAI Event: response.created - {"type":"response.created",...}
```

#### VAD 事件

```python
logger.info(f"VAD: Speech started for question {current_question_index}")
logger.info(f"VAD: Speech stopped for question {current_question_index}")
logger.info(f"VAD: Saved speech segment to {file_path}")
```

**示例日志**：
```
2026-03-11 14:25:10 - INFO - VAD: Speech started for question 0
2026-03-11 14:25:13 - INFO - VAD: Speech stopped for question 0
2026-03-11 14:25:13 - INFO - VAD: Saved speech segment for question 0 to uploads/abc123_0_a1b2.wav
```

### 3. 面试流程事件

#### 面试创建

```python
# backend/app/api/interviews.py
logger.info(f"Interview created: {db_interview.id}, token: {link_token}")
```

#### 面试完成

```python
logger.info(f"Interview completed: {interview.id}, status: {interview.status}")
```

#### STT 转写

```python
# backend/app/services/stt.py
logger.info(f"Transcribing audio: {audio_path}")
logger.info(f"Transcription result: {transcript[:100]}...")
```

#### AI 评估

```python
# backend/app/services/evaluator.py
logger.info(f"Evaluating interview {interview_id}")
logger.info(f"Evaluation completed, score: {evaluation['overall_score']}")
```

### 4. 错误和警告

#### Token 验证失败

```python
logger.warning(f"WebSocket connection attempt with invalid token: {token}")
```

#### OpenAI API 错误

```python
logger.error(f"OpenAI Realtime Error for token {token}: {json.dumps(event, indent=2)}")
```

#### 数据库错误

```python
logger.error(f"Database error during interview creation: {e}")
```

## 🔍 日志分析示例

### 完整面试流程日志

```
# 1. 建立连接
2026-03-11 14:24:49 - INFO - WebSocket connected for token: abc123, Candidate: 张三
2026-03-11 14:24:49 - INFO - Connecting to OpenAI Realtime for token: abc123
2026-03-11 14:24:50 - INFO - OpenAI Realtime connection established for token: abc123

# 2. 会话初始化
2026-03-11 14:24:50 - INFO - OpenAI Event: session.created - {...}
2026-03-11 14:24:50 - INFO - OpenAI Event: session.updated - {...}

# 3. AI 开始第一个问题
2026-03-11 14:24:50 - INFO - OpenAI Event: response.created - {...}
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio.done - {...}
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio_transcript.done - {"transcript":"您好，欢迎..."}
2026-03-11 14:24:51 - INFO - OpenAI: Response done. Transcript: 您好，欢迎参加今天的面试！

# 4. 候选人回答
2026-03-11 14:25:10 - INFO - VAD: Speech started for question 0
2026-03-11 14:25:13 - INFO - VAD: Speech stopped for question 0
2026-03-11 14:25:13 - INFO - VAD: Saved speech segment to uploads/abc123_0_a1b2.wav

# 5. 节奏控制
2026-03-11 14:26:15 - INFO - Pacing: 节奏落后：请减少或停止追问，尽快进入下一个主问题。

# 6. 面试结束
2026-03-11 14:30:00 - INFO - Interview reached time budget (600.0s). Entering overtime mode.
2026-03-11 14:30:20 - INFO - Client disconnected: abc123

# 7. STT 和评估
2026-03-11 14:30:25 - INFO - Transcribing audio: uploads/abc123_0_a1b2.wav
2026-03-11 14:30:27 - INFO - Transcription result: 大家好，我叫张三...
2026-03-11 14:30:30 - INFO - Evaluating interview
2026-03-11 14:30:35 - INFO - Evaluation completed, score: 85
```

### 问题排查示例

#### 场景 1：听不到 AI 声音

**日志分析**：

```
2026-03-11 14:24:50 - INFO - OpenAI Event: response.created
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio.done
2026-03-11 14:24:51 - INFO - OpenAI Event: response.audio_transcript.done - {"transcript":"您好..."}
```

**结论**：
- ✅ OpenAI 已生成音频（`response.audio.done`）
- ✅ 转写文本正常（`response.audio_transcript.done`）
- 🔍 问题可能在前端播放环节（检查 AudioContext 状态）

#### 场景 2：VAD 不触发

**日志分析**：

```
2026-03-11 14:25:00 - INFO - OpenAI Event: response.done
# ... 30 秒后仍无 speech_started ...
```

**结论**：
- 🔍 VAD threshold 太高或麦克风无输入
- 检查浏览器控制台的麦克风权限
- 降低 VAD threshold 到 0.3-0.4

## 🎛️ 自定义日志

### 添加自定义日志

```python
from app.utils.logger import logger

# INFO 级别
logger.info(f"Custom event: {data}")

# WARNING 级别
logger.warning(f"Potential issue: {details}")

# ERROR 级别
logger.error(f"Error occurred: {error_message}")

# DEBUG 级别（需要调整 logger.setLevel(logging.DEBUG)）
logger.debug(f"Debug info: {debug_data}")
```

### 结构化日志（推荐）

```python
import json

# 记录结构化数据
logger.info(f"Event data: {json.dumps({
    'event_type': 'interview_created',
    'interview_id': interview.id,
    'candidate': interview.name,
    'position': interview.position,
    'timestamp': datetime.utcnow().isoformat()
})}")
```

**好处**：
- 易于解析和分析
- 支持日志聚合工具（ELK、Splunk）

## 📊 日志监控（生产环境）

### 推荐工具

1. **ELK Stack**（Elasticsearch + Logstash + Kibana）
   - 强大的日志聚合和可视化
   - 支持全文搜索

2. **Prometheus + Grafana**
   - 实时监控和告警
   - 需要配合 Python metrics 库

3. **Sentry**
   - 错误追踪和告警
   - 提供上下文和堆栈跟踪

### 集成 Sentry（可选）

```python
# backend/app/main.py
import sentry_sdk

sentry_sdk.init(
    dsn="your-sentry-dsn",
    traces_sample_rate=1.0
)

# 自动捕获异常
```

## 🔐 日志安全

### 敏感信息脱敏

```python
# ❌ 错误：记录完整 API Key
logger.info(f"Using API Key: {OPENAI_API_KEY}")

# ✅ 正确：脱敏处理
logger.info(f"Using API Key: {OPENAI_API_KEY[:8]}...")

# ✅ 正确：不记录密码
logger.info(f"User login: {username}")  # 不记录 password
```

### 日志访问控制

**生产环境建议**：
- 日志文件权限设置为 `600`（仅所有者可读写）
- 定期清理旧日志
- 使用日志轮转避免磁盘占满

```bash
# 设置日志文件权限
chmod 600 logs/*.log

# 定期清理（cron job）
find logs/ -name "*.log" -mtime +30 -delete
```

## 📚 相关文档

- [系统架构](02_architecture.md)
- [故障排查](06_troubleshooting.md)
- [OpenAI Realtime API](04_technical_details/04.1_realtime_api.md)
