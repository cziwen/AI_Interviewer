# 快速启动指南

## 🎯 5 分钟快速体验

本指南帮助你快速启动 AI 面试系统并进行第一次面试。

### 前置要求

- **Python 3.9+**
- **Node.js 16+**
- **OpenAI API Key**（支持 Realtime API）

## 🚀 安装与启动

### 步骤 1：克隆项目

```bash
git clone <repository-url>
cd AI_Interviewer
```

### 步骤 2：后端启动

```bash
cd backend

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置本地环境变量（推荐）
cp ../.env.local.example .env
# 至少填写 OPENAI_API_KEY

# 启动服务
uvicorn app.main:app --reload
```

**验证**：访问 http://localhost:8000/docs 查看 API 文档

### 步骤 3：前端启动

```bash
# 新终端窗口
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

**验证**：访问 http://localhost:5173

### 步骤 4：创建第一个面试

#### 方式 1：使用管理后台（推荐）

1. 访问 http://localhost:5173/admin/login
2. 登录（默认账号：admin / admin123）
3. 点击"创建面试"
4. 填写候选人信息：
   - 姓名：张三
   - 岗位：后端工程师
   - 简历摘要：5年 Python 开发经验
5. 点击"创建"并复制面试链接

#### 方式 2：使用 API

```bash
curl -X POST http://localhost:8000/api/interviews/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "张三",
    "position": "后端工程师",
    "external_id": "candidate_001",
    "resume_brief": "5年 Python 开发经验"
  }'

# 返回：{ "link_token": "abc123...", ... }
```

### 步骤 5：开始面试

1. 访问面试链接：`http://localhost:5173/interview/{token}`
2. 允许浏览器麦克风权限
3. 选择麦克风和扬声器设备
4. 点击"测试设备"确认音频正常
5. 点击"确认设备并开始面试"
6. 与 AI 面试官进行实时对话
7. 完成后点击"结束面试并生成评分"

### 步骤 6：查看结果

1. 返回管理后台：http://localhost:5173/admin/login
2. 在面试列表中找到刚才的面试
3. 查看详细评分报告

## 🎯 岗位配置（可选）

如需使用自定义题库和 JD 配置：

### 准备配置文件

**questions.csv**（题库）：
```csv
question,reference
请介绍一下 Python 的 GIL,全局解释器锁的概念和影响
如何设计一个高并发系统？,考察负载均衡、缓存、数据库优化
```

**jd.json**（岗位描述）：
```json
{
  "responsibilities": "负责后端服务开发和优化",
  "requirements": "精通 Python，熟悉 Django/FastAPI",
  "main_question_count": 3,
  "followup_limit_per_question": 1,
  "expected_duration_minutes": 10
}
```

### 上传岗位配置

```bash
curl -X POST http://localhost:8000/api/job-profiles/upload \
  -F "position_key=backend_engineer" \
  -F "position_name=后端工程师" \
  -F "csv_file=@questions.csv" \
  -F "jd_file=@jd.json"
```

### 使用岗位配置创建面试

```bash
curl -X POST http://localhost:8000/api/interviews/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "张三",
    "position_key": "backend_engineer",
    "external_id": "candidate_001",
    "resume_brief": "5年 Python 开发经验"
  }'
```

详见：[岗位配置管理](03_features/03.5_job_profile_config.md)

## ⚙️ 环境变量说明

### 文件约定（推荐）

- 本地后端开发：`backend/.env`（由 `../.env.local.example` 复制）
- Docker 部署：项目根目录 `.env`（由 `.env.example` 复制）

### 必需配置

| 变量 | 说明 | 示例 |
|-----|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | `sk-proj-...` |

### 可选配置（有默认值）

| 变量 | 说明 | 默认值 |
|-----|------|--------|
| `DATABASE_URL` | 数据库连接 | `sqlite:///./ai_interview.db` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin123` |
| `JWT_SECRET` | JWT 签名密钥 | `local-dev-secret-change-in-production` |
| `UPLOAD_DIR` | 音频文件存储目录 | `./app/static/uploads` |

## ⚠️ 常见问题

### 1. 端口被占用

**症状**：`Address already in use`

**解决**：
```bash
# Linux/Mac 查找占用进程
lsof -i :8000

# Windows 查找占用进程
netstat -ano | findstr :8000

# 更换端口启动
uvicorn app.main:app --reload --port 8001
```

### 2. 麦克风权限被拒绝

**症状**：浏览器无法访问麦克风

**解决**：
1. 检查浏览器设置：设置 → 隐私和安全 → 网站设置 → 麦克风
2. 确保使用 `localhost` 或 `https://`
3. 刷新页面重新授权

### 3. 听不到 AI 声音

**症状**：能看到转写文本，但听不到声音

**解决**：
1. 检查浏览器控制台是否有 AudioContext 错误
2. 点击页面任意位置激活 AudioContext（浏览器自动播放策略）
3. 检查系统音量和扬声器设置
4. 查看详细排查：[故障排查指南](06_troubleshooting.md#听不到-ai-声音)

### 4. OpenAI API 调用失败

**症状**：AI 无响应或返回错误

**解决**：
```bash
# 验证 API Key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# 检查余额
# 访问 https://platform.openai.com/usage

# 使用代理（国内网络环境）
export HTTPS_PROXY=http://127.0.0.1:7890
```

### 5. 数据库连接错误

**症状**：`Could not connect to database`

**解决**：
```bash
# SQLite（默认）无需额外配置
# 如使用 PostgreSQL，确保数据库已创建
createdb ai_interview

# 更新 .env
DATABASE_URL=postgresql://user:pass@localhost/ai_interview
```

## 🔧 开发模式说明

### 当前模式：OpenAI Realtime API

**特点**：
- ✅ 全自动语音对话（Server VAD）
- ✅ 实时转写显示
- ✅ 开箱即用，无需本地模型
- ⚠️ 产生 OpenAI API 费用（STT + TTS + LLM）

**成本估算**：
- 10 分钟面试约消耗 $0.5-1.0
- 详见 [OpenAI Pricing](https://openai.com/api/pricing/)

### 未来规划：本地 STT/TTS 模式

后续版本将支持本地模型以降低成本：
- RealtimeSTT（Whisper）
- RealtimeTTS（Kokoro）
- 预计成本降低 70%+

当前代码中的 `backend/app/realtime/` 模块为实验性本地语音组件，默认未启用。

## 📚 下一步

- 📖 [系统架构](02_architecture.md) - 了解整体设计
- 🎙️ [实时面试功能](03_features/03.2_realtime_interview.md) - 深入技术实现
- 📊 [AI 评估系统](03_features/03.3_ai_evaluation.md) - 评分机制
- 🔍 [故障排查](06_troubleshooting.md) - 问题诊断

## 💡 生产环境部署

生产环境**必须使用 HTTPS**，否则浏览器会限制以下能力：
- **复制链接**：`navigator.clipboard` 仅在安全上下文中可用
- **麦克风/扬声器选择**：`navigator.mediaDevices` 仅在安全上下文中可用

**推荐方式**：使用项目自带一键部署（Caddy + Let's Encrypt 自动续期），详见根目录 [deploy.md](../deploy.md)。在 ECS 上配置 `DOMAIN`、`ACME_EMAIL` 后执行 `./deploy.sh` 即可获得 HTTPS。

### 使用 Gunicorn + Uvicorn Workers（仅后端）

```bash
pip install gunicorn

gunicorn app.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### 使用 Nginx 反向代理（需自行配置 TLS）

若不用项目内的 Caddy 方案，可自建 Nginx，并**务必配置 HTTPS**（如 Let's Encrypt + certbot）：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    # ssl_certificate /path/to/fullchain.pem;
    # ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://localhost:5173;
    }

    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 切换到 PostgreSQL

```bash
# 安装 psycopg2
pip install psycopg2-binary

# 更新 .env
DATABASE_URL=postgresql://user:pass@localhost/ai_interview

# 重启服务
uvicorn app.main:app --reload
```

## 🛟 获取帮助

- **文档问题**：查看 [spec_doc/](README.md) 目录
- **技术问题**：查看 [故障排查](06_troubleshooting.md)
- **Bug 报告**：提交 GitHub Issue

祝你使用愉快！🎉
