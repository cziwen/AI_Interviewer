# 日志系统

## 概述

当前日志体系分为两类：

- **Server Log**
  - 关注服务整体运行状态
  - 例如服务启动、全局错误、健康检查
- **Interview Log**
  - 关注单场 realtime 面试的完整过程
  - 例如 WebSocket 生命周期、VAD 事件、pipeline 阶段、决策层、turn 生命周期

本次 realtime 重构后，Interview Log 的主线也同步变为单一链路：

`candidate_audio -> transcription -> decision -> ai_response`

因此日志设计也围绕这条链路组织。

## 日志通道职责

### Server Log

适合记录：

- 服务启动与关闭
- 全局异常
- 数据库或外部依赖整体不可用
- 负载、连接数、资源告警

对于单场面试，Server Log 应尽量只保留摘要，例如：

- `Interview started`
- `Interview ended`

### Interview Log

适合记录：

- `ws.*`
- `openai.*`
- `vad.*`
- `pipeline.*`
- `decision_layer.*`
- `turn.*`
- `evaluation.*`

Interview Log 的目标是：只看一份 token 对应的日志文件，就能还原整场面试如何推进、在哪一步出错。

## 当前日志文件

### Server Log

```text
backend/logs/server_{YYYYMMDD}_{HHMMSS}.log
```

### Interview Log

```text
backend/logs/interviews/interview_token_{token}_{YYYYMMDD}.log
backend/logs/interviews/interview_token_{token}_{YYYYMMDD}_dialogue.log
```

其中：

- `*.log`：控制与结构化事件日志
- `*_dialogue.log`：候选人与 AI 的可读对话文本

## Interview Log 标准字段

建议所有控制事件至少包含以下字段：

| 字段 | 说明 |
|---|---|
| `timestamp` | ISO8601 UTC 时间 |
| `level` | `INFO` / `WARNING` / `ERROR` 等 |
| `event_name` | 规范化事件名 |
| `source` | 产生日志的模块 |
| `interview_id` | 面试主键 |
| `interview_token` | 候选人 token |
| `stage` | 当前业务阶段 |
| `turn_id` | 当前 turn 标识 |
| `question_order` | 当前主问题序号 |
| `main_completed_count` | 已完成主问题数 |
| `followups_used` | 当前题已用追问数 |
| `expected_reply` | 当前期望候选人回复类型 |
| `overtime_mode` | 是否已进入超时模式 |
| `duration_ms` | 本事件耗时 |
| `outcome` | `success` / `failed` / `timeout` 等 |
| `error_code` | 错误码 |
| `error_message` | 错误摘要 |
| `details` | 事件特有扩展字段 |

## 新版 realtime 观测主线

### 1. VAD 事件

- `vad.speech_started`
- `vad.speech_stopped`
- `vad.segment_saved`

这些事件只描述：

- 候选人开始/结束说话
- 音频 segment 是否已保存

它们**不等于**业务状态已经推进。

### 2. Pipeline 事件

这是本次重构新增的核心观测链路。

- `pipeline.segment_started`
  - 开始处理一个候选人 segment
- `pipeline.committed`
  - 当前音频已提交到 OpenAI input buffer
- `pipeline.transcribed`
  - 已拿到该 `item_id` 对应 transcript
- `pipeline.transcription_timeout`
  - 等待 transcript 超时
- `pipeline.responding`
  - 已创建 turn 并发送 `response.create`
- `pipeline.completed`
  - 收到 `response.done(completed)` 并完成状态推进
- `pipeline.skip_duplicate_finalize`
  - 因 `decision_pending = true` 跳过重复 finalize

这组事件回答的是：

- 当前 segment 到哪一步了
- 是否发生了未转写先决策
- 是否发生了重复推进

### 3. 决策层事件

- `decision_layer.requested`
- `decision_layer.succeeded`
- `decision_layer.fallback`
- `decision_layer.mapped_to_plan`
- `decision_layer.finish_blocked`

这组事件回答的是：

- 决策层是否稳定
- 决策层是否超时
- 决策输出和 `TurnPlan` 是否一致
- 是否出现提前结束被服务端硬拦截

### 4. Turn 生命周期事件

- `turn.created`
- `turn.completed`
- `turn.cancelled`
- `turn.failed`
- `turn.transition_applied`

这组事件回答的是：

- AI 这一轮是否真正开始
- 是否完整完成
- 是否被取消或失败
- 哪个 `TurnPlan` 最终落成了业务状态

## 为什么要区分 `vad.*`、`pipeline.*`、`turn.*`

这三层日志解决的是不同问题：

- `vad.*`
  - 候选人是否真的说话了
  - 音频边界是否形成
- `pipeline.*`
  - 候选人音频是否按线性链条被处理完
  - 是否已等到转写再决策
- `turn.*`
  - AI 这一轮回复是否真正完成
  - 是否允许推进业务状态

如果只看 `vad.speech_stopped`，无法判断：

- 转写是否到达
- 决策是否完成
- AI 是否已经说完

因此排障时推荐顺序是：

1. 先看 `pipeline.*`
2. 再看 `decision_layer.*`
3. 最后看 `turn.*`

## 对话日志

`*_dialogue.log` 的格式为：

```text
{timestamp}  {role}  {text}
```

例如：

```text
2026-03-12T06:24:55.123Z  AI  你好，请先简单介绍一下自己。
2026-03-12T06:25:10.000Z  Candidate  我做过一个多 Agent 项目...
```

### 写入时机

- Candidate 行
  - 来自 `conversation.item.input_audio_transcription.completed`
- AI 行
  - 来自 `response.done(completed)` 后聚合完成的 transcript

因此控制日志和对话日志的时序应一起看：

- 控制日志告诉你链路在哪一步
- 对话日志告诉你具体说了什么

## Interview Log 示例

```text
{"timestamp":"2026-03-12T06:25:10.000Z","level":"INFO","event_name":"vad.speech_started","interview_id":42,"stage":"qa","question_order":1}
{"timestamp":"2026-03-12T06:25:13.000Z","level":"INFO","event_name":"pipeline.segment_started","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"trigger":"vad_speech_stopped","item_id":"item_1"},"question_order":1}
{"timestamp":"2026-03-12T06:25:13.030Z","level":"INFO","event_name":"pipeline.committed","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"item_id":"item_1"},"question_order":1}
{"timestamp":"2026-03-12T06:25:13.300Z","level":"INFO","event_name":"pipeline.transcribed","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"item_id":"item_1","waited_ms":270,"chars":128},"question_order":1}
{"timestamp":"2026-03-12T06:25:13.520Z","level":"INFO","event_name":"decision_layer.succeeded","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"action":"followup","latency_ms":518},"duration_ms":518,"question_order":1}
{"timestamp":"2026-03-12T06:25:13.560Z","level":"INFO","event_name":"pipeline.responding","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"turn_id":7,"turn_kind":"followup_prompt"},"question_order":1}
{"timestamp":"2026-03-12T06:25:16.000Z","level":"INFO","event_name":"turn.completed","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","turn_id":"7","outcome":"success"}
{"timestamp":"2026-03-12T06:25:16.020Z","level":"INFO","event_name":"pipeline.completed","interview_id":42,"interview_token":"abc123","source":"turn_orchestrator","details":{"stage":"qa"},"question_order":1}
```

## 日志级别建议

### `INFO`

默认建议记录：

- `ws.*`
- `vad.*`
- `pipeline.*`
- `decision_layer.*`
- `turn.*`
- `evaluation.*`

### `DEBUG`

仅在问题排查时打开：

- 原始 OpenAI payload
- 更细粒度的中间状态
- 过于频繁的 delta 级日志

## 安全与隐私

日志中应避免直接记录：

- API Key
- 完整凭证
- 不必要的候选人敏感个人信息

推荐：

- 在结构化事件中只保留必要标识
- 文本内容优先写到 `*_dialogue.log`
- 对需要长期保留的全文转写，优先依赖数据库而不是日志文件

## 相关文档

- [实时语音面试功能](03_features/03.2_realtime_interview.md)
- [OpenAI Realtime API 集成](04_technical_details/04.1_realtime_api.md)
- [Realtime Turn 编排器技术文档](04_technical_details/04.5_realtime_turn_orchestrator.md)
