# AI Interviewer

AI 招聘面试系统基础框架。

## 项目结构

- `backend/`: FastAPI 后端
- `frontend/`: React 前端

## 核心升级：OpenAI Realtime 实时语音面试

系统已升级为基于 **OpenAI Realtime API** 的实时语音对话模式。

### 升级特性
- **实时对话**：AI 面试官实时发问、追问，候选人语音流式回答，低延迟交互。
- **动态题库**：支持从 `backend/app/static/question_bank.csv` 按岗位匹配题目。
- **智能评估**：面试结束后自动进行全场 STT 转写与 LLM 综合评分。

## 快速启动

### 后端启动

1. 进入 backend 目录: `cd backend`
2. 安装依赖: `pip install -r requirements.txt`
3. 配置环境变量: 创建 `.env` 文件并填入 `OPENAI_API_KEY`
4. 启动服务: `uvicorn app.main:app --reload`

### 前端启动

1. 进入 frontend 目录: `cd frontend`
2. 安装依赖: `npm install`
3. 启动开发服务器: `npm run dev`

## 核心流程

1. **创建面试**: 调用 `POST /api/interviews/create` (可指定 `position`)。
2. **候选人面试**: 访问 `http://localhost:5173/interview/{link_token}`，点击“开始面试”进入实时通话。
3. **完成与评分**: 面试结束后点击“结束面试”，后端将自动生成 STT 转写与评分。
4. **HR 后台**: 访问 `http://localhost:5173/admin/login` 查看结果。
