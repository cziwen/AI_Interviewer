# AI 面试系统技术文档

欢迎使用 AI 面试系统技术文档。
当前系统采用**三段式语音链路**：

- ASR：豆包语音 ASR（支持 `sauc_v3` / `openspeech_v2` / `gateway_json`）
- LLM：方舟文本模型（默认 `doubao-seed-2-0-mini-260215`）
- TTS：豆包语音合成（当前实现为 v1 HTTP，后端分片下发音频）

## 📚 文档导航

### 快速入门
- [01_quick_start.md](01_quick_start.md) - 快速开始与环境变量

### 系统架构
- [02_architecture.md](02_architecture.md) - 当前后端三段式架构

### 功能模块
- [03.1_interview_creation.md](03_features/03.1_interview_creation.md) - 面试创建流程
- [03.2_realtime_interview.md](03_features/03.2_realtime_interview.md) - 实时语音面试主链路
- [03.3_ai_evaluation.md](03_features/03.3_ai_evaluation.md) - AI 评估系统
- [03.4_admin_dashboard.md](03_features/03.4_admin_dashboard.md) - HR 管理后台
- [03.5_job_profile_config.md](03_features/03.5_job_profile_config.md) - 岗位配置管理

### 技术细节
- [04.1_realtime_api.md](04_technical_details/04.1_realtime_api.md) - Realtime 三段式实现细节
- [04.2_audio_processing.md](04_technical_details/04.2_audio_processing.md) - 音频处理
- [04.3_vad_mechanism.md](04_technical_details/04.3_vad_mechanism.md) - VAD 与分段策略
- [04.4_half_duplex_strategy.md](04_technical_details/04.4_half_duplex_strategy.md) - 半双工门控
- [04.5_realtime_turn_orchestrator.md](04_technical_details/04.5_realtime_turn_orchestrator.md) - 回合编排
- [04.6_realtime_anti_drift_mechanism.md](04_technical_details/04.6_realtime_anti_drift_mechanism.md) - 防跑题机制

### 运维与调试
- [05_logging.md](05_logging.md) - 日志事件与排查入口
- [06_troubleshooting.md](06_troubleshooting.md) - 常见故障排查

## 🎯 核心特性

1. 浏览器到后端保持轻量协议（`audio/end_turn/no_response_timeout`）
2. 后端状态机控制面试流程，不依赖端到端模型自由发挥
3. LLM 负责文本生成，TTS 负责语音输出，便于可控与审计
4. 音频统一为 PCM16 @ 24kHz，兼容前端播放链路

## 📝 备注

- 部署与 HTTPS 参考项目根目录 [deploy.md](../deploy.md)。
