# AI 面试系统技术文档

欢迎使用 AI 面试系统技术文档。本系统基于 OpenAI Realtime API，提供实时语音面试体验。

## 📚 文档导航

### 快速入门
- [01_quick_start.md](01_quick_start.md) - 快速开始指南

### 系统架构
- [02_architecture.md](02_architecture.md) - 整体架构设计

### 功能模块
- [03.1_interview_creation.md](03_features/03.1_interview_creation.md) - 面试创建流程
- [03.2_realtime_interview.md](03_features/03.2_realtime_interview.md) - 实时语音面试
- [03.3_ai_evaluation.md](03_features/03.3_ai_evaluation.md) - AI 评估系统
- [03.4_admin_dashboard.md](03_features/03.4_admin_dashboard.md) - HR 管理后台
- [03.5_job_profile_config.md](03_features/03.5_job_profile_config.md) - 岗位配置管理

### 技术细节
- [04.1_realtime_api.md](04_technical_details/04.1_realtime_api.md) - OpenAI Realtime API 集成
- [04.2_audio_processing.md](04_technical_details/04.2_audio_processing.md) - 音频处理技术
- [04.3_vad_mechanism.md](04_technical_details/04.3_vad_mechanism.md) - VAD 语音检测机制
- [04.4_half_duplex_strategy.md](04_technical_details/04.4_half_duplex_strategy.md) - 半双工音频策略

### 运维与调试
- [05_logging.md](05_logging.md) - 日志系统
- [06_troubleshooting.md](06_troubleshooting.md) - 故障排查指南

## 🔍 快速查找

**我想了解...**
- 如何快速部署？→ [快速开始](01_quick_start.md)
- 系统如何工作？→ [系统架构](02_architecture.md)
- 如何创建面试？→ [面试创建](03_features/03.1_interview_creation.md)
- 实时面试如何实现？→ [实时语音面试](03_features/03.2_realtime_interview.md)
- 如何配置岗位题库？→ [岗位配置](03_features/03.5_job_profile_config.md)
- 音频为什么听不到？→ [故障排查](06_troubleshooting.md)
- 为什么有回声？→ [半双工策略](04_technical_details/04.4_half_duplex_strategy.md)

## 🎯 核心特性

1. **实时语音交互**：基于 OpenAI Realtime API 的低延迟语音对话
2. **智能面试流程**：自动化提问、追问、节奏控制
3. **岗位题库管理**：支持 CSV 题库导入和 JSON JD 配置
4. **多维度评估**：面试结束后自动生成结构化评分报告
5. **设备适配**：支持麦克风和扬声器选择及实时测试

## 🛠️ 技术栈

- **前端**：React + TypeScript + Web Audio API
- **后端**：FastAPI + SQLAlchemy + WebSocket
- **AI 服务**：OpenAI Realtime API (gpt-realtime-mini)
- **数据库**：PostgreSQL / SQLite
- **音频格式**：PCM16 @ 24kHz

## 📝 版本信息

- 当前版本：2.0 (Realtime 升级版)
- 最后更新：2026-03-11
