# Deploy (ECS)

## 一键部署（在 ECS 上）

```bash
git clone <your_repo_url>
cd AI_Interviewer
cp .env.example .env
# 编辑 .env，至少填 OPENAI_API_KEY / JWT_SECRET / ADMIN_PASSWORD
./deploy.sh
```

部署完成后访问：

- Frontend: `http://<ECS_IP>`
- Backend API: `http://<ECS_IP>:8000`
- API Docs: `http://<ECS_IP>:8000/docs`

## 启用 PostgreSQL（可选）

```bash
./deploy.sh --with-postgres
```

并在 `.env` 中把 `DATABASE_URL` 改成 PostgreSQL 连接串。

## 本机推送并远程部署（可选）

```bash
./deploy.sh --remote <user@ecs_ip> --remote-dir /opt/ai_interviewer
```

带 PostgreSQL：

```bash
./deploy.sh --remote <user@ecs_ip> --with-postgres
```

## 常用运维命令

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose restart backend frontend
docker compose down
```

## 最小检查清单

- ECS 安全组已放行：`80`、`8000`（如启用 Postgres 再放行 `5432`）
- `.env` 已正确设置 `OPENAI_API_KEY`
- 域名/HTTPS 暂未包含在该脚本内（后续可加 Nginx + 证书）
