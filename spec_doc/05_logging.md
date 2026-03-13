# 日志系统

## 📝 概述

本系统使用 Python `logging` 模块进行统一日志管理，**明确拆分为两类日志通道**：

- **Server Log（服务器运行日志）**：关注整体服务运行状态与基础设施健康。
- **Interview Log（面试会话日志）**：聚焦单场面试的 WebSocket / OpenAI / turn / stage 等细粒度行为。

当前代码已经实现了统一的 `ai_interview` 日志器，并将所有事件写入 `backend/logs/server_*.log`。本规范在此基础上：

- 定义两类日志的职责边界与字段规范。
- 约定 Interview Log 的标准结构和事件分类，为后续代码落地做设计指引。

---

## 📚 日志分类与职责边界

### Server Log（服务器运行日志）

- **关注对象**：整个平台/服务的运行态，而不是某一场具体面试。
- **典型事件**：
  - 服务启动与关闭（FastAPI / Uvicorn 生命周期）
  - 依赖健康检查（数据库、OpenAI、存储等）
  - 全局异常与未捕获错误
  - 性能与资源告警（超时、请求量、队列堆积等）
  - 管理端 API 的访问情况（如 `/admin`、`/job_profiles`）
- **使用场景**：
  - 运维值班、SRE 监控。
  - 服务是否“整体正常”层面的排障。

### Interview Log（面试会话日志）

- **关注对象**：单场面试从“创建 → WebSocket 会话 → 结束 → 评估”的完整生命周期。
- **典型事件**：
  - WebSocket 连接/断开、重连、异常关闭。
  - OpenAI Realtime 关键事件（`session.*`、`response.*` 汇总态，而非所有 delta）。
  - VAD 语音起止、语音片段保存、提交 STT、STT 结果摘要。
  - Turn/Stage 状态变化（当前题目、追问次数、节奏控制、超时等）。
  - 面试完成、评分完成、异常终止等。
- **使用场景**：
  - 对单个候选人的面试过程进行追踪与复盘。
  - 定位“这场面试哪里出了问题”，包括 WebSocket、OpenAI、VAD、评估链路。

#### Interview Log 末尾的用量汇总（interview.usage_summary）

- **设计目的**：方便按「单场面试」统计 OpenAI 成本，而不在系统内直接算钱。
- **核心思路**：  
  - 由后端在每场面试结束时，**按模型 × 用量种类** 汇总用量；  
  - 写入一条 `event_name = "interview.usage_summary"` 的结构化日志；  
  - 你可以拿这一条里的数字 + 官方 `price per 1M tokens / per minute` 自行计算成本。

- **用量维度约定**（示例）：
  - Realtime 多模态模型（如 `gpt-realtime-mini`）：
    - `text_input_tokens`
    - `text_output_tokens`
    - `audio_input_seconds`（候选人语音总时长）
    - `audio_output_seconds`（AI 语音总时长，如有统计）
  - STT 模型（如 `whisper-1` 或其他 STT 模型）：
    - `audio_input_seconds`（所有转写音频总时长）
  - 评估 LLM（如 `gpt-4o`）：
    - `text_input_tokens`
    - `text_output_tokens`

- **日志结构示例**：

```json
{
  "timestamp": "2026-03-12T06:31:00.000Z",
  "level": "INFO",
  "event_name": "interview.usage_summary",
  "source": "usage_tracker",
  "interview_id": 42,
  "interview_token": "abc123",
  "details": {
    "models": {
      "gpt-realtime-mini": {
        "text_input_tokens": 1520,
        "text_output_tokens": 840,
        "audio_input_seconds": 120.5,
        "audio_output_seconds": 95.2
      },
      "whisper-1": {
        "audio_input_seconds": 120.5
      },
      "gpt-4o": {
        "text_input_tokens": 2100,
        "text_output_tokens": 560
      }
    }
  }
}
```

- **使用方式**：
  - 打开 `logs/interviews/interview_token_{token}_{date}.log`；
  - 滚动到最后一条 `interview.usage_summary`；
  - 按模型读取对应用量，结合 OpenAI 官方 `price per 1M tokens / per minute` 进行成本计算。

### 对比总结

| 维度 | Server Log | Interview Log |
|------|-----------|---------------|
| **粒度** | 宏观，面向服务 | 细粒度，面向单场面试 |
| **主键** | 请求 ID / 进程信息 | `interview_id` / `token` / `runtime_session_id` |
| **主要读者** | 运维 / 平台工程 | 面试产品 / 算法 / 排障工程师 |
| **示例问题** | “昨晚 2 点服务有没有挂？” | “张三这场面试为何卡在第 2 题？” |

---

## 🔧 日志配置总览

### 全局 Logger 设置（当前实现）

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
        # 文件处理器（当前：Server Log）
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

- **当前行为**：所有通过 `from app.utils.logger import logger` 打印的内容，都会写入 `server_*.log`。
- **目标行为**：在保留现有 Server Log 的同时，为 Interview Log 增设独立的 handler（例如按 token / interview_id 拆分文件或输出到聚合系统）。

### 日志级别策略

| 级别 | 用途 | Server Log 示例 | Interview Log 示例 |
|-----|------|----------------|--------------------|
| **DEBUG** | 详细调试信息 | 请求参数细节、SQL 执行计划 | 单个 OpenAI event 全量 payload、音频帧级诊断 |
| **INFO** | 正常流转信息 | 服务启动、健康检查通过 | WebSocket 连接、VAD 事件、Turn 状态变化 |
| **WARNING** | 潜在问题 | API 调用接近限额 | 面试时长接近上限、VAD 长时间无语音 |
| **ERROR** | 明确错误 | DB 连接失败 | 单场面试的 STT 调用失败、OpenAI 错误 |
| **CRITICAL** | 严重错误 | 进程崩溃 | 面试核心流程无法继续的致命错误 |

**推荐默认级别**：

- 开发环境：`DEBUG`（便于调试）。
- 生产环境：Server Log 使用 `INFO`，Interview Log 建议支持按 session 动态切换到 `DEBUG`（问题现场时临时开启）。

---

## 📂 日志文件结构与命名

### 当前实现

```text
backend/
├── logs/
│   ├── server_20260311_142449.log
│   ├── server_20260311_153022.log
│   └── server_20260311_164501.log
└── ...
```

- 文件命名规则：

```text
server_{YYYYMMDD}_{HHMMSS}.log
```

- `YYYYMMDD`：启动日期（年月日）
- `HHMMSS`：启动时间（时分秒）

### 推荐的双通道结构（设计目标）

```text
backend/
├── logs/
│   ├── server_20260312_145308.log      # Server Log（现有）
│   └── interviews/                     # Interview Log 目录
│       ├── interview_token_abc123_20260312.log           # 控制/事件 Log
│       └── interview_token_abc123_20260312_dialogue.log  # 对话 Log（新增）
└── ...
```

- **Server Log**：按「服务启动」维度滚动，保留现有命名即可。
- **Interview Log**：按「面试标识 + 日期」维度命名，每个面试包含两个文件：
  - **控制/事件 Log**：`interview_token_{token}_{YYYYMMDD}.log`，记录所有后台控制事件。
  - **对话 Log**：`interview_token_{token}_{YYYYMMDD}_dialogue.log`，仅记录候选人与 AI 的文字对话。

---

## 🧩 Interview Log 标准字段（Schema）

### 1. 控制/事件 Log 字段
为方便后续接入日志聚合/查询系统，建议 **所有 Interview Log 事件都满足一套统一字段基线**。

#### 核心字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `timestamp` | string | ISO8601 UTC 时间戳，例如 `2026-03-12T06:25:10.123Z` |
| `level` | string | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `event_name` | string | 规范化事件名，例如 `ws.connected`、`turn.completed` |
| `source` | string | 产生日志的模块，例如 `api.realtime`、`turn_orchestrator` |
| `interview_id` | int | 面试数据库主键 ID |
| `interview_token` | string | 用于候选人访问的链接 token（可按需脱敏） |
| `external_id` | string | 外部候选人 ID（如 ATS 系统 ID，可选） |
| `runtime_session_id` | string | 本次 WebSocket 会话的运行时 ID（服务生成） |
| `ws_connection_id` | string | WebSocket 连接 ID（可与网关/反向代理一致） |
| `stage` | string | 当前面试阶段，例如 `intro` / `qa` / `closing` |
| `turn_id` | string | Turn 唯一标识（与内部 orchestrator 对应） |
| `turn_kind` | string | `question` / `followup` / `closing` 等 |
| `turn_status` | string | `created` / `speaking` / `completed` / `cancelled` / `failed` |
| `question_order` | int | 当前主问题序号（从 0 或 1 开始，需在文档中统一） |
| `main_completed_count` | int | 已完成主问题数量 |
| `followups_used` | int | 对当前问题已使用的追问次数 |
| `overtime_mode` | bool | 是否已进入加时/收尾模式 |
| `openai_response_id` | string | OpenAI `response.id`（如适用） |
| `openai_conversation_id` | string | OpenAI `conversation.id`（如适用） |
| `duration_ms` | int | 本事件涉及的耗时（如一次 OpenAI 调用、一次 STT 调用） |
| `outcome` | string | 对本事件的归纳结果，如 `success` / `timeout` / `client_disconnected` |
| `error_code` | string | 业务或系统错误码（如 `OPENAI_TIMEOUT`、`STT_FAILED`，可选） |
| `error_message` | string | 错误信息（建议为简短摘要，避免长堆栈污染日志） |
| `details` | object | 事件特有的扩展字段（JSON 对象） |

---

### 2. 对话 Log 格式
对话 Log 旨在提供人类可读的面试复盘，格式应尽量简洁。

- **格式约定**：`{timestamp}  {role}  {text}`
- **示例**：
```text
2026-03-12T06:25:10.123Z  AI  你好，请先简单介绍一下自己。
2026-03-12T06:25:35.456Z  Candidate  我是张三，有三年后端经验...
```
- **角色说明**：
  - `AI`: AI 面试官的回复。
  - `Candidate`: 候选人的回答（经 STT 转写）。

---

## 📋 关键事件与路由策略

本节基于当前代码中的日志点（主要位于 [backend/app/api/realtime.py](../../backend/app/api/realtime.py)、[backend/app/services/realtime_turn_orchestrator.py](../../backend/app/services/realtime_turn_orchestrator.py) 等），明确哪些属于 Server Log，哪些应进入 Interview Log。

### 1. WebSocket 生命周期

**当前实现（示例）**：

```python
logger.info(f"WebSocket connected for token: {token}, Candidate: {interview.name}")
logger.info(f"Connecting to OpenAI Realtime for token: {token}")
logger.info(f"OpenAI Realtime connection established for token: {token}")

logger.info(f"Client disconnected: {token}")
logger.error(f"Realtime session error for token {token}: {e}")
```

- **规范建议**：
  - **Server Log**：记录 WebSocket 服务整体的监听端口、握手失败总数、异常峰值等聚合信息。
  - **Interview Log**：每一次成功/失败的连接、正常/异常断开、重连，均按上文的 Interview Log Schema 记录，便于按 `interview_id` 精确追踪。

### 2. OpenAI Realtime 事件

**当前实现（节选，自 [backend/app/api/realtime.py](../../backend/app/api/realtime.py#L206)）**：

```python
# 记录所有非音频事件
if event_type in ["response.audio.delta", "response.audio_transcript.delta", "response.text.delta"]:
    pass  # 避免刷屏
else:
    logger.info(f"OpenAI Event: {event_type} - {json.dumps(event)}")
```

- **问题**：直接将原始 OpenAI 事件 JSON 打入 Server Log，体积较大、难以聚合分析。
- **规范建议**：
  - **Server Log**：仅记录 OpenAI 可用性相关的摘要信息（如“与 OpenAI 建立连接成功/失败”、“Reconnect 次数”等）。
  - **Interview Log**：将单场面试对应的 `session.*` / `response.*` 事件归纳为若干 **规范化事件**（例如 `openai.session.created`、`openai.response.done`），并填充 `openai_response_id` / `openai_conversation_id` 等字段，而不是原始 payload 全量输出。

### 3. VAD 语音与音频处理

**当前实现（示例）**：

```python
logger.info(f"VAD: Speech started for question {current_question_index}")
logger.info(f"VAD: Speech stopped for question {current_question_index}")
logger.info(f"VAD: Saved speech segment to {file_path}")
```

- **规范建议**：
  - **Interview Log**：记录为结构化事件，例如：
    - `vad.speech_started`
    - `vad.speech_stopped`
    - `vad.segment_saved`
  - 在 `details` 中带上 `question_order`、语音时长、保存路径（可只记录相对路径或 hash）。

### 4. 面试流程与业务状态

**当前实现（节选）**：

- 面试创建（[backend/app/api/interviews.py](../../backend/app/api/interviews.py)）：

```python
logger.info(f"Interview created: {db_interview.id}, token: {link_token}")
```

- 面试完成：

```python
logger.info(f"Interview completed: {interview.id}, status: {interview.status}")
```

- STT 转写（[backend/app/services/stt.py](../../backend/app/services/stt.py)）：

```python
logger.info(f"Transcribing audio: {audio_path}")
logger.info(f"Transcription result: {transcript[:100]}...")
```

- AI 评估（[backend/app/services/evaluator.py](../../backend/app/services/evaluator.py)）：

```python
logger.info(f"Evaluating interview {interview_id}")
logger.info(f"Evaluation completed, score: {evaluation['overall_score']}")
```

- **规范建议**：
  - **Server Log**：记录“某时间段共创建了多少场面试”、“评估模块是否正常工作”等聚合信息。
  - **Interview Log**：
    - `interview.created`：带上 `interview_id` / `token` / `position_key` 等。
    - `interview.completed`：带上最终 `status`、用时等。
    - `stt.requested` / `stt.completed`：带上音频片段标识和 STT 模型信息。
    - `evaluation.requested` / `evaluation.completed`：带上模型名和关键评分摘要。

### 5. 错误与警告

**当前实现（示例）**：

```python
logger.warning(f"WebSocket connection attempt with invalid token: {token}")
logger.error(f"OpenAI Realtime Error for token {token}: {json.dumps(event, indent=2)}")
logger.error(f"Database error during interview creation: {e}")
```

- **规范建议**：
  - **Server Log**：记录系统级错误（DB 连接失败、OpenAI 服务整体不可用等），方便快速判断是否为“全局性故障”。
  - **Interview Log**：记录“某场面试受影响”的错误（如某次 STT 失败、某次问答超时等），在 Schema 中使用 `outcome` / `error_code` / `error_message` 归一化表示。

---

## 🎛️ 采样与级别控制

为了避免 Interview Log 过于庞大，建议对高频事件（如 OpenAI delta、VAD 帧级数据）进行采样或下沉到 `DEBUG` 级别：

- **INFO 级别**（推荐默认）：
  - WebSocket 连接/断开。
  - Turn 创建/完成/失败。
  - STT / 评估的请求与完成（摘要）。
  - 重要的 OpenAI 事件（`response.created` / `response.done` 聚合视图）。
- **DEBUG 级别**（按 session 临时打开）：
  - 全量 OpenAI 事件 payload。
  - 更细粒度的 VAD 状态变化。
  - 中间态的 `INTERVIEW_STATE` dump。

> 建议在业务层封装一个小工具，允许通过环境变量或后端 API，为特定 `interview_id` / `token` 临时开启 Debug 级别的 Interview Log。

---

## 🔍 日志 analysis 示例（双通道视角）

### 示例 1：Server Log 视角（服务级）

```text
2026-03-12 14:24:40,000 - ai_interview - INFO - AI Interview API starting up...
2026-03-12 14:24:41,000 - ai_interview - INFO - Database connected: sqlite:///./interview.db
2026-03-12 14:24:42,000 - ai_interview - INFO - OpenAI Realtime health check passed
2026-03-12 14:30:00,000 - ai_interview - WARNING - Active interviews reached 50, approaching limit 60
```

从以上日志可以快速判断：**服务整体健康**，但在某时间点接近并发上限。

### 示例 2：Interview Log 视角（单场面试）

#### 控制 Log (JSON)
```text
{"timestamp":"2026-03-12T06:24:49.982Z","level":"INFO","event_name":"ws.connected","interview_id":42,"interview_token":"abc123","stage":"intro","outcome":"success"}
{"timestamp":"2026-03-12T06:24:50.100Z","level":"INFO","event_name":"openai.session.created","interview_id":42,"runtime_session_id":"sess_9f8c...","outcome":"success"}
{"timestamp":"2026-03-12T06:25:10.000Z","level":"INFO","event_name":"vad.speech_started","interview_id":42,"stage":"qa","question_order":0}
{"timestamp":"2026-03-12T06:25:13.000Z","level":"INFO","event_name":"vad.segment_saved","interview_id":42,"details":{"file_path":"uploads/abc123_0_a1b2.wav","duration_ms":3000}}
{"timestamp":"2026-03-12T06:30:35.000Z","level":"INFO","event_name":"evaluation.completed","interview_id":42,"details":{"overall_score":85}}
{"timestamp":"2026-03-12T06:30:40.000Z","level":"INFO","event_name":"ws.disconnected","interview_id":42,"outcome":"success"}
```

#### 对话 Log (Text)
```text
2026-03-12T06:24:55.123Z  AI  你好，我是今天的面试官。请先做一个简单的自我介绍。
2026-03-12T06:25:10.000Z  Candidate  你好，我叫张三，目前是一名后端开发工程师...
```

- 可以用 `interview_id=42` 或 `interview_token=abc123` 一键过滤出整场面试轨迹。
- 对单个事件进一步展开 `details` 字段，即可定位具体问题。

---

## 🔐 日志安全与隐私

### 敏感信息脱敏

对于 Interview Log，尤其要注意以下信息的处理：

- **API Key / 凭证**：绝不记录原文，只能记录前缀或 hash。
- **候选人姓名**：可以只保留姓氏+首字母，例如 `"张*"`。
- **消息正文 / 转写文本**：
  - 可在 `details.transcript_preview` 中仅保留前若干字符，用于快速识别语境。
  - 需要全文时，建议存入数据库表或对象存储，而不是日志文件。

```python
# ❌ 错误：记录完整 API Key
logger.info(f"Using API Key: {OPENAI_API_KEY}")

# ✅ 正确：脱敏处理
logger.info(f"Using API Key: {OPENAI_API_KEY[:8]}...")

# ✅ 正确：不记录密码
logger.info(f"User login: {username}")  # 不记录 password
```

### 日志访问控制与保留策略

- Interview Log 相比 Server Log，**隐私敏感度更高**，建议：
  - 日志文件权限：生产环境设置为 `600`（仅所有者可读写）。
  - 定期清理旧日志（如保留 30~90 天，视合规要求而定）。
  - 对接日志聚合系统时，限制只有授权角色可以查询具体面试详情。

```bash
# 设置日志文件权限
chmod 600 logs/*.log

# 定期清理（cron job）
find logs/ -name "*.log" -mtime +30 -delete
```

---

## 🔁 从单日志到双日志的迁移建议

本节描述从“当前所有日志都写入 `server_*.log`”演进到“Server Log + Interview Log 双通道”的建议步骤，仅影响后端实现，不改变对外 API。

1. **抽象统一的日志封装层**  
   - 在后端增加一个轻量级 `log_event()` 或 `interview_log()` 工具函数，内部负责：
     - 填充 Interview Log Schema 基础字段（`interview_id` / `token` / `stage` / `turn_id` 等）。
     - 根据事件类型决定写入 Server Log 还是 Interview Log。
2. **先划分事件归属，再改写调用点**  
   - 参考本文件“关键事件与路由策略”，对每一个现有 `logger.info(...)` / `logger.error(...)` 进行标注：
     - 纯基础设施相关 → 保留在 Server Log。
     - 含有 `token` / `interview_id` / turn 信息 → 迁移到 Interview Log。
3. **为 Interview Log 增加独立 handler**  
   - 在 `backend/app/utils/logger.py` 或新的模块中：
     - 创建专用的 `interview` logger 或在现有 `ai_interview` logger 上增加按面试维度切分的 handler。
     - 推荐使用结构化 JSON 格式。
4. **灰度上线与回滚预案**  
   - 初期可同时将 Interview Log 事件写入 Server Log + Interview Log，确保排障链路完整。
   - 待确认稳定后，再逐步降低 Server Log 中的面试细节，转而主要依赖 Interview Log。
5. **文档与运维约定同步**  
   - 将本规范同步至运维与数据团队，约定：
     - 如何按 `interview_id` / `token` 查询单场面试日志。
     - 如何联合 Server Log 与 Interview Log 排查跨面试的系统性问题。

---

## 📚 相关文档

- [系统架构](02_architecture.md)
- [故障排查](06_troubleshooting.md)
- [OpenAI Realtime API](04_technical_details/04.1_realtime_api.md)
