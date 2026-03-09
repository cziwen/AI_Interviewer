# AI Interviewer

AI 招聘面试系统基础框架。

## 项目结构

- `backend/`: FastAPI 后端
- `frontend/`: React 前端

## 快速启动

### 后端启动

1. 进入 backend 目录: `cd backend`
2. 安装依赖: `pip install -r requirements.txt`
3. 配置环境变量 (可选，默认使用 SQLite): 创建 `.env` 文件
4. 启动服务: `uvicorn app.main:app --reload`

### 前端启动

1. 进入 frontend 目录: `cd frontend`
2. 安装依赖: `npm install`
3. 启动开发服务器: `npm run dev`

## 核心流程

1. **创建面试**: 调用 `POST /api/interviews/create` 获取 `link_token`。
2. **候选人面试**: 访问 `http://localhost:5173/interview/{link_token}`。
3. **HR 后台**: 访问 `http://localhost:5173/admin/login` (默认账号: admin / admin123)。
