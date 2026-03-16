# 日志系统

## 日志位置

- 服务日志：`backend/logs/server_*.log`
- 面试事件日志：`backend/logs/interviews/interview_token_<token>_<date>.log`
- 对话日志：`backend/logs/interviews/interview_token_<token>_<date>_dialogue.log`

## 关键事件（当前实现）

### 连接与链路
- `asr.connecting`
- `asr.connected`
- `relay.client_to_asr.error`
- `relay.asr_to_client.error`
- `ws.error`

### Pipeline
- `pipeline.segment_started`
- `pipeline.committed`
- `pipeline.transcribed`
- `decision_layer.requested`
- `decision_layer.succeeded`
- `decision_layer.fallback`
- `pipeline.responding`
- `pipeline.completed`

### 回合
- `turn.created`
- `turn.completed`
- `turn.cancelled`
- `turn.failed`
- `turn.transition_applied`

### 语音
- `asr.speech_started`
- `asr.speech_stopped`
- `vad.segment_saved`

## 排查建议

1. 先看是否有 `asr.connected`
2. 再看是否出现 `pipeline.transcribed`
3. 再看是否有 `decision_layer.succeeded/fallback`
4. 最后看是否出现 `response.created` 与 `response.done`（前端日志或 ws 下行）
