#!/usr/bin/env bash
# =============================================================================
# 海康威视密码重置工具 - 一键启动脚本
# Hikvision Password Reset Tool - One-click Start Script
#
# 用法 / Usage:
#   ./start.sh              # 同时启动后端和前端（开发模式）
#                           # Start both backend and frontend (dev mode)
#   ./start.sh --backend    # 仅启动后端 / Backend only
#   ./start.sh --frontend   # 仅启动前端 / Frontend only
#   ./start.sh --prod       # 生产模式（前端构建 + 后端生产启动）
#                           # Production mode (build frontend + start backend in prod)
# =============================================================================

set -euo pipefail

# 颜色输出 / Colored output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_section() { echo -e "\n${BLUE}======== $* ========${NC}"; }

# 脚本所在目录（即项目根目录）/ Script directory (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env 文件（如果存在）/ Load .env file if it exists
if [ -f ".env" ]; then
    log_info "Loading environment from .env"
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    log_warn ".env file not found. Using defaults. (Copy .env.example to .env to configure)"
fi

# 读取配置，提供默认值 / Read config with defaults
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# 解析参数 / Parse arguments
MODE="dev"
if [ "${1:-}" = "--prod" ]; then
    MODE="prod"
elif [ "${1:-}" = "--backend" ]; then
    MODE="backend"
elif [ "${1:-}" = "--frontend" ]; then
    MODE="frontend"
fi

# ---------------------------------------------------------------------------
# 依赖检查 / Dependency checks
# ---------------------------------------------------------------------------
check_deps() {
    log_section "Checking dependencies"

    # 检查 Poetry / Check Poetry
    if ! command -v poetry &>/dev/null; then
        log_error "Poetry is not installed. Install it with: pip install poetry"
        exit 1
    fi
    log_info "Poetry: $(poetry --version)"

    # 检查 Node.js（仅前端需要）/ Check Node.js (needed for frontend)
    if [ "$MODE" != "backend" ]; then
        if ! command -v node &>/dev/null; then
            log_error "Node.js is not installed. Download from: https://nodejs.org"
            exit 1
        fi
        log_info "Node.js: $(node --version)"
    fi

    # QR 码解码已迁移至纯 OpenCV（opencv-python-headless Python 包）
    # 无需系统级 libzbar 库 / No system-level libzbar required
    # (pyzbar dependency removed — pure OpenCV used for QR decoding)
}

# ---------------------------------------------------------------------------
# 安装依赖 / Install dependencies
# ---------------------------------------------------------------------------
install_deps() {
    log_section "Installing dependencies"

    if [ "$MODE" != "frontend" ]; then
        log_info "Installing Python dependencies..."
        poetry install --no-interaction
    fi

    if [ "$MODE" != "backend" ]; then
        log_info "Installing frontend dependencies..."
        (cd frontend && npm install --prefer-offline 2>&1 | tail -3)
    fi
}

# ---------------------------------------------------------------------------
# 启动后端 / Start backend
# ---------------------------------------------------------------------------
start_backend() {
    log_section "Starting Backend"
    log_info "Backend: http://${HOST}:${PORT}"
    log_info "API Docs: http://${HOST}:${PORT}/docs"

    if [ "$MODE" = "prod" ]; then
        # 生产模式：多 worker，不热重载 / Production: multiple workers, no reload
        WORKERS="${WORKERS:-4}"
        log_info "Production mode: ${WORKERS} workers"
        poetry run uvicorn hikresetpasswd.main:app \
            --host "$HOST" \
            --port "$PORT" \
            --workers "$WORKERS" \
            --log-level "$LOG_LEVEL"
    else
        # 开发模式：单 worker + 热重载 / Dev mode: single worker + hot reload
        log_info "Development mode: hot reload enabled"
        poetry run uvicorn hikresetpasswd.main:app \
            --host "$HOST" \
            --port "$PORT" \
            --reload \
            --log-level "$LOG_LEVEL"
    fi
}

# ---------------------------------------------------------------------------
# 启动前端 / Start frontend
# ---------------------------------------------------------------------------
start_frontend() {
    log_section "Starting Frontend"

    if [ "$MODE" = "prod" ]; then
        log_info "Building frontend for production..."
        (cd frontend && npm run build)
        log_info "Frontend built in frontend/dist/"
        log_info "Serve it with a web server (e.g. nginx) pointing to frontend/dist/"
    else
        log_info "Frontend dev server: http://localhost:${FRONTEND_PORT}"
        (cd frontend && npm run dev -- --host --port "$FRONTEND_PORT")
    fi
}

# ---------------------------------------------------------------------------
# 主逻辑 / Main logic
# ---------------------------------------------------------------------------
check_deps
install_deps

# 用于清理后台进程的 trap / Trap to clean up background processes
PIDS=()
cleanup() {
    log_info "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    exit 0
}
trap cleanup INT TERM

case "$MODE" in
    backend)
        start_backend
        ;;
    frontend)
        start_frontend
        ;;
    prod)
        # 生产模式：后台启动后端，前端构建 / Prod: backend in BG, build frontend
        start_backend &
        PIDS+=($!)
        start_frontend
        wait
        ;;
    dev|*)
        # 开发模式：后台启动后端，前台运行前端 / Dev: backend in BG, frontend in FG
        log_section "Starting in Development Mode"
        start_backend &
        PIDS+=($!)
        # 等待后端健康检查通过（最多 30 秒）
        # Wait for backend health check to pass (up to 30 seconds)
        log_info "Waiting for backend to become ready..."
        for i in $(seq 1 30); do
            if curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
                log_info "Backend is ready."
                break
            fi
            sleep 1
        done
        start_frontend
        wait
        ;;
esac
