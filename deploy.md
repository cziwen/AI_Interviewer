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

- Application: `http://<ECS_IP>`
- Backend API: `http://<ECS_IP>/api`
- API Docs: `http://<ECS_IP>/docs`

## 启用 PostgreSQL（可选）

```bash
./deploy.sh --with-postgres
```

- 脚本会在 `--with-postgres` 下自动检查 `.env`：
  - 若 `DATABASE_URL` 为空或仍是 sqlite，会自动改为 `postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@db:5432/<POSTGRES_DB>`。
  - 若你已手动设置 PostgreSQL 连接串，脚本会保留现有值。

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

- ECS 安全组已放行：`80`（上 HTTPS 时放行 `443`；如启用 Postgres 再放行 `5432`）
- `.env` 已正确设置 `OPENAI_API_KEY`
- 前后端均走同域（`/` + `/api`），后端 `8000` 不再对公网暴露
- 域名/HTTPS 暂未包含在该脚本内（后续可加证书）
