#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="AI_Interviewer"
REMOTE_TARGET=""
REMOTE_DIR="/opt/ai_interviewer"
WITH_POSTGRES=0

log() {
  echo "[deploy] $*"
}

die() {
  echo "[deploy][error] $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh
  ./deploy.sh --with-postgres
  ./deploy.sh --remote user@host [--remote-dir /opt/ai_interviewer] [--with-postgres]

Options:
  --remote <user@host>   Upload current project to remote ECS and run deploy there
  --remote-dir <path>    Remote project directory (default: /opt/ai_interviewer)
  --with-postgres        Start optional postgres service (compose profile: postgres)
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      [[ $# -ge 2 ]] || die "--remote requires user@host"
      REMOTE_TARGET="$2"
      shift 2
      ;;
    --remote-dir)
      [[ $# -ge 2 ]] || die "--remote-dir requires a path"
      REMOTE_DIR="$2"
      shift 2
      ;;
    --with-postgres)
      WITH_POSTGRES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

if [[ -n "$REMOTE_TARGET" ]]; then
  command -v rsync >/dev/null 2>&1 || die "rsync is required for --remote mode"
  command -v ssh >/dev/null 2>&1 || die "ssh is required for --remote mode"

  log "Syncing project to $REMOTE_TARGET:$REMOTE_DIR ..."
  ssh "$REMOTE_TARGET" "mkdir -p '$REMOTE_DIR'"
  rsync -az --delete \
    --exclude ".git" \
    --exclude "node_modules" \
    --exclude ".venv" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    ./ "$REMOTE_TARGET:$REMOTE_DIR/"

  log "Running remote deployment ..."
  REMOTE_CMD="cd '$REMOTE_DIR' && bash ./deploy.sh"
  if [[ "$WITH_POSTGRES" -eq 1 ]]; then
    REMOTE_CMD="$REMOTE_CMD --with-postgres"
  fi
  ssh "$REMOTE_TARGET" "$REMOTE_CMD"
  log "Remote deployment completed."
  exit 0
fi

if [[ ! -f "docker-compose.yml" || ! -d "backend" || ! -d "frontend" ]]; then
  die "Please run deploy.sh from the repository root."
fi

if [[ $EUID -eq 0 ]]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  die "sudo is required to install docker and manage docker service."
fi

install_docker_if_needed() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker is already installed."
    return
  fi

  local pkg_mgr
  if command -v dnf >/dev/null 2>&1; then
    pkg_mgr="dnf"
  elif command -v yum >/dev/null 2>&1; then
    pkg_mgr="yum"
  else
    die "Neither dnf nor yum found. Unsupported system."
  fi

  log "Installing docker with $pkg_mgr ..."
  $SUDO "$pkg_mgr" install -y docker
}

start_docker_service() {
  if $SUDO systemctl cat docker.service >/dev/null 2>&1; then
    log "Enabling and starting docker service ..."
    $SUDO systemctl enable --now docker
    return
  fi

  if $SUDO systemctl cat podman.socket >/dev/null 2>&1; then
    log "docker.service not found; enabling and starting podman.socket ..."
    $SUDO systemctl enable --now podman.socket
    return
  fi

  if $SUDO systemctl cat podman.service >/dev/null 2>&1; then
    log "docker.service not found; enabling and starting podman.service ..."
    $SUDO systemctl enable --now podman.service
    return
  fi

  die "Neither docker.service nor podman.socket/podman.service found. Please install Docker or Podman."
}

install_compose_if_needed() {
  if docker compose version >/dev/null 2>&1; then
    log "Docker Compose v2 is already available."
    return
  fi

  local pkg_mgr=""
  if command -v dnf >/dev/null 2>&1; then
    pkg_mgr="dnf"
  elif command -v yum >/dev/null 2>&1; then
    pkg_mgr="yum"
  fi

  if [[ -n "$pkg_mgr" ]]; then
    log "Trying to install docker-compose-plugin with $pkg_mgr ..."
    if $SUDO "$pkg_mgr" install -y docker-compose-plugin >/dev/null 2>&1; then
      if docker compose version >/dev/null 2>&1; then
        log "Docker Compose plugin installed."
        return
      fi
    fi
  fi

  log "Installing docker compose plugin in ~/.docker/cli-plugins ..."
  mkdir -p "${HOME}/.docker/cli-plugins"

  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    *) die "Unsupported architecture: $arch" ;;
  esac

  local url="https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${arch}"
  curl -fsSL "$url" -o "${HOME}/.docker/cli-plugins/docker-compose"
  chmod +x "${HOME}/.docker/cli-plugins/docker-compose"

  if ! docker compose version >/dev/null 2>&1; then
    die "Docker Compose installation failed."
  fi
}

ensure_env_file() {
  if [[ -f ".env" ]]; then
    log ".env already exists."
    return
  fi

  [[ -f ".env.example" ]] || die ".env.example not found."
  cp .env.example .env
  log "Created .env from .env.example"

  read -r -p "Enter OPENAI_API_KEY (leave empty to edit manually later): " input_key || true
  if [[ -n "${input_key:-}" ]]; then
    sed -i.bak "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${input_key}|" .env && rm -f .env.bak
    log "OPENAI_API_KEY has been written to .env"
  else
    log "Please edit .env and set OPENAI_API_KEY before production use."
  fi
}

get_env_value() {
  local key="$1"
  awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, "", $0); print $0; exit}' .env
}

upsert_env_value() {
  local key="$1"
  local value="$2"
  if awk -F= -v k="$key" '$1 == k {found=1} END {exit !found}' .env; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    printf "\n%s=%s\n" "$key" "$value" >> .env
  fi
}

ensure_postgres_database_url() {
  if [[ "$WITH_POSTGRES" -ne 1 ]]; then
    return
  fi

  local pg_db pg_user pg_password current_db_url target_db_url
  pg_db="$(get_env_value "POSTGRES_DB")"
  pg_user="$(get_env_value "POSTGRES_USER")"
  pg_password="$(get_env_value "POSTGRES_PASSWORD")"
  current_db_url="$(get_env_value "DATABASE_URL")"

  pg_db="${pg_db:-ai_interview}"
  pg_user="${pg_user:-ai_interview}"
  pg_password="${pg_password:-change_me}"
  target_db_url="postgresql://${pg_user}:${pg_password}@db:5432/${pg_db}"

  if [[ -z "$current_db_url" || "$current_db_url" == sqlite://* ]]; then
    upsert_env_value "DATABASE_URL" "$target_db_url"
    log "DATABASE_URL auto-updated for PostgreSQL profile."
    return
  fi

  if [[ "$current_db_url" == postgresql://* || "$current_db_url" == postgres://* ]]; then
    log "Using existing PostgreSQL DATABASE_URL from .env"
    return
  fi

  log "Warning: DATABASE_URL is non-sqlite and non-postgresql. Keeping current value."
}

docker_compose_up() {
  local compose_cmd=(docker compose --env-file .env up -d --build)
  if [[ "$WITH_POSTGRES" -eq 1 ]]; then
    compose_cmd=(docker compose --profile postgres --env-file .env up -d --build)
  fi

  if docker info >/dev/null 2>&1; then
    "${compose_cmd[@]}"
  else
    $SUDO "${compose_cmd[@]}"
  fi
}

validate_https_env() {
  local domain acme_email
  domain="$(get_env_value "DOMAIN")"
  acme_email="$(get_env_value "ACME_EMAIL")"

  if [[ -z "$domain" || "$domain" == "your.domain.com" ]]; then
    die "DOMAIN is not configured in .env. Set it to your real domain before deployment."
  fi

  if [[ -z "$acme_email" || "$acme_email" == "your-email@example.com" ]]; then
    die "ACME_EMAIL is not configured in .env. Set a real email for Let's Encrypt notifications."
  fi
}

main() {
  log "Starting ${PROJECT_NAME} deployment ..."
  install_docker_if_needed
  start_docker_service
  install_compose_if_needed
  ensure_env_file
  ensure_postgres_database_url
  validate_https_env

  log "Building and starting containers ..."
  docker_compose_up

  log "Deployment completed."
  log "Application: https://$(get_env_value "DOMAIN")"
  log "API: https://$(get_env_value "DOMAIN")/api"
  log "API Docs: https://$(get_env_value "DOMAIN")/docs"
  log "TLS certificates are managed by Caddy and renew automatically."
}

main "$@"
