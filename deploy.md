# Deploy (ECS)

## 一键部署（在 ECS 上）

```bash
git clone <your_repo_url>
cd AI_Interviewer
cp .env.example .env
# 编辑 .env，至少填 OPENAI_API_KEY / JWT_SECRET / ADMIN_PASSWORD / DOMAIN / ACME_EMAIL
./deploy.sh
```

说明：部署只读取**项目根目录** `.env`，不会读取 `backend/.env`。

部署完成后访问：

- Application: `https://<DOMAIN>`
- Backend API: `https://<DOMAIN>/api`
- API Docs: `https://<DOMAIN>/docs`

## 启用 HTTPS（Let's Encrypt，自动续期）

本项目使用 Caddy 作为反向代理，自动申请并续期 Let's Encrypt 证书。

前置条件：

- 域名 A 记录已指向 ECS 公网 IP（如 `smartinterview.cn` -> ECS IP）
- ECS 安全组放行 `80` 和 `443`

`.env` 中至少配置：

```env
DOMAIN=smartinterview.cn
ACME_EMAIL=admin@smartinterview.cn
```

部署：

```bash
./deploy.sh
```

说明：

- 首次启动时，Caddy 会自动向 Let's Encrypt 申请证书。
- 证书与 ACME 状态保存在 Docker 卷中，容器重启后仍可继续使用与续期。
- 自动续期由 Caddy 内置机制完成，无需额外 cron/systemd timer。

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

- ECS 安全组已放行：`80`、`443`（如启用 Postgres 再放行 `5432`）
- `.env` 已正确设置 `OPENAI_API_KEY`
- `.env` 已正确设置 `DOMAIN` 与 `ACME_EMAIL`
- 前后端均走同域（`/` + `/api`），后端 `8000` 不再对公网暴露
- 访问使用 `https://<DOMAIN>`，证书自动续期由 Caddy 管理
