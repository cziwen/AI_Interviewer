# AI 面试系统

基于火山方舟 Realtime API 的智能语音面试系统，提供实时对话、智能追问、多维度评估等企业级招聘解决方案。

## ✨ 核心特性

- 🎙️ **实时语音交互**：基于火山方舟 Realtime API，低延迟（<2s）的自然对话体验
- 🤖 **智能面试流程**：自动化提问、追问、节奏控制，模拟真人面试官
- 📊 **岗位题库管理**：支持 CSV 题库导入和 JSON JD 配置，灵活匹配不同岗位
- 📈 **多维度评估**：面试结束后自动生成结构化评分报告
- 🎧 **设备适配优化**：麦克风/扬声器选择及实时音量测试
- 🔇 **半双工策略**：智能音频门控，消除回声和自我反馈

## 🏗️ 项目结构

```
AI_Interviewer/
├── backend/           # FastAPI 后端服务
│   ├── app/
│   │   ├── api/       # API 路由（interviews, realtime, job_profiles, admin）
│   │   ├── models/    # 数据库模型（Interview, Answer, JobProfile）
│   │   ├── services/  # 业务逻辑（STT, 评估, 题目生成）
│   │   └── utils/     # 工具类（日志等）
│   └── requirements.txt
├── frontend/          # React + TypeScript 前端
│   ├── src/
│   │   ├── pages/     # 页面组件（Interview, Admin, Done）
│   │   └── api.ts     # API 调用封装
│   └── package.json
└── spec_doc/          # 📚 完整技术文档
```

## 🚀 快速启动

### 1. 环境准备

**前置要求**：
- Node.js 16+
- Python 3.9+
- 火山方舟 API Key（支持 Realtime API）

**克隆项目**：
```bash
git clone <repository-url>
cd AI_Interviewer
```

### 2. 后端启动

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 配置本地环境变量（建议使用本地模板）
cp ../.env.local.example .env
# 然后编辑 .env，至少填 ARK_API_KEY
# (可选) 如需改库路径，修改 DATABASE_URL=sqlite:///./ai_interview.db

# 启动服务（默认 http://localhost:8000）
uvicorn app.main:app --reload
```

### 3. 生产环境部署 (推荐 20+ 并发)

对于生产环境或高并发场景（如 20 人同时面试），建议使用 `gunicorn` 配合 `uvicorn` worker。

**启动命令示例 (2vCPU 推荐)**：
```bash
gunicorn -k uvicorn.workers.UvicornWorker -w 2 --threads 4 --worker-connections 1000 app.main:app --bind 0.0.0.0:8000
```

**关键配置说明**：
- `-w 2`: 启动 2 个 worker 进程（建议设为 CPU 核心数）。
- `--threads 4`: 每个 worker 的线程数，用于处理 `asyncio.to_thread` 抛出的阻塞 IO（如音频落盘）。
- `--worker-connections 1000`: 每个 worker 支持的最大并发连接数。

**Nginx 反向代理配置 (WebSocket 支持)**：
如果前置 Nginx，请确保包含以下配置以支持 WebSocket 长连接：
```nginx
location /api/realtime/ws/ {
    proxy_pass http://backend_upstream;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "Upgrade";
    proxy_set_header Host $host;
    
    # 延长超时时间，防止面试中途断连
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

### 4. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器（默认 http://localhost:5173）
npm run dev
```

### 5. 访问系统

- **候选人面试页**：`http://localhost:5173/interview/{token}` （由 HR 创建后分享）
- **HR 管理后台**：`http://localhost:5173/admin/login`
- **API 文档**：`http://localhost:8000/docs`

### 6. 生产环境部署（Docker + HTTPS）

生产环境推荐使用项目自带的一键部署脚本，通过 **Caddy** 反向代理自动申请并续期 **Let's Encrypt** 证书，提供 HTTPS：

- **复制链接、麦克风/扬声器选择** 等能力依赖浏览器安全上下文（HTTPS），生产必须使用 HTTPS。
- 在 ECS 上配置好 `DOMAIN`、`ACME_EMAIL` 后执行 `./deploy.sh` 即可。

详见：[deploy.md](deploy.md)（一键部署、启用 HTTPS、PostgreSQL 可选等）。

### 环境变量文件约定

- **部署（Docker/Caddy）**：使用根目录 `.env`（从 `.env.example` 复制）
- **本地后端开发**：使用 `backend/.env`（从 `.env.local.example` 复制）
- 后端会优先读取根目录 `.env`，再读取 `backend/.env` 作为本地覆盖，减少本地/部署切换成本

## 📖 使用流程

### HR 创建面试

```bash
curl -X POST http://localhost:8000/api/interviews/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "张三",
    "position": "后端工程师",
    "position_key": "backend_engineer",
    "external_id": "candidate_001",
    "resume_brief": "5年 Python 开发经验"
  }'

# 返回：{ "link_token": "abc123...", ... }
```

### 候选人参加面试

1. 访问面试链接：`http://localhost:5173/interview/abc123...`
2. 选择麦克风和扬声器，点击"测试设备"
3. 点击"确认设备并开始面试"
4. 与 AI 面试官进行实时语音对话
5. 完成后点击"结束面试并生成评分"

### HR 查看结果

1. 登录管理后台：`http://localhost:5173/admin/login`
2. 查看面试列表和详细评分报告

## 🎯 岗位配置管理

系统支持通过 **JobProfile** 配置不同岗位的题库和 JD：

```bash
# 上传岗位配置（CSV 题库 + JSON JD）
curl -X POST http://localhost:8000/api/job-profiles/upload \
  -F "position_key=backend_engineer" \
  -F "position_name=后端工程师" \
  -F "csv_file=@questions.csv" \
  -F "jd_file=@jd.json"
```

**CSV 格式示例**（`questions.csv`）：
```csv
question,reference
请介绍一下 Python 的 GIL,全局解释器锁的概念和影响
如何设计一个高并发系统？,考察负载均衡、缓存、数据库优化
```

**JD 格式示例**（`jd.json`）：
```json
{
  "responsibilities": "负责后端服务开发和优化",
  "requirements": "精通 Python，熟悉 Django/FastAPI",
  "main_question_count": 3,
  "followup_limit_per_question": 1,
  "expected_duration_minutes": 10
}
```

详见：[spec_doc/03_features/03.5_job_profile_config.md](spec_doc/03_features/03.5_job_profile_config.md)

## 📚 完整文档

- **部署**：[deploy.md](deploy.md) — ECS 一键部署、HTTPS（Let's Encrypt 自动续期）、PostgreSQL 可选  
- **技术文档**：[spec_doc/README.md](spec_doc/README.md)：
  - [快速开始指南](spec_doc/01_quick_start.md)
  - [系统架构设计](spec_doc/02_architecture.md)
  - [功能模块详解](spec_doc/03_features/)
  - [技术实现细节](spec_doc/04_technical_details/)
  - [故障排查指南](spec_doc/06_troubleshooting.md)

## 🛠️ 技术栈

| 类别 | 技术 |
|-----|------|
| **前端** | React 18, TypeScript, Web Audio API |
| **后端** | FastAPI, SQLAlchemy, WebSocket |
| **AI 服务** | 火山方舟 Realtime API |
| **音频处理** | PCM16 @ 24kHz, Server VAD, ScriptProcessorNode |
| **数据库** | PostgreSQL / SQLite |

## 🔧 核心技术亮点

1. **火山方舟 Realtime API 集成**：全流程 WebSocket 通信，支持音频流式传输
2. **Server VAD 机制**：利用方舟服务端语音检测，精确定位说话起止
3. **半双工音频策略**：基于时间轴的智能门控，防止 AI 声音被麦克风采集
4. **动态节奏控制**：根据预设时长自动调整提问节奏，支持超时自然收尾
5. **设备适配优化**：支持音频设备选择和实时音量可视化

## 📝 版本历史

- **v2.0** (2026-03) - Realtime API 升级版，实时语音交互
- **v1.0** (2025-12) - 基础版本，录音上传模式

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
