#!/usr/bin/env bash
# =============================================================================
# 海康威视密码重置工具 - Nuitka 编译脚本
# Hikvision Password Reset Tool - Nuitka Compilation Script
#
# 将 Python 后端编译为独立可执行文件（无需 Python 运行时）。
# Compiles the Python backend into a standalone executable (no Python runtime needed).
#
# 依赖 / Requirements:
#   - Python 3.12 + Poetry（用于安装项目依赖）
#   - Nuitka（编译器，本脚本会自动安装）
#   - C 编译器：gcc/clang（Linux/macOS）或 MSVC（Windows）
#   - 系统库：libGL（OpenCV headless 可能需要）
#
# 用法 / Usage:
#   ./build_nuitka.sh              # 编译后端 / Compile backend
#   ./build_nuitka.sh --onefile    # 单文件模式（较慢，但分发方便）
#                                   # Single-file mode (slower, easier to distribute)
#
# 输出 / Output:
#   dist/hikresetpasswd            # 可执行文件（Linux/macOS）
#   dist/hikresetpasswd.exe        # 可执行文件（Windows）
#   dist/hikresetpasswd.dist/      # standalone 模式下的依赖目录
# =============================================================================

set -euo pipefail

# 颜色输出 / Colored output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_section() { echo -e "\n${BLUE}======== $* ========${NC}"; }

# 脚本目录 / Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 输出目录 / Output directory
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

# 解析参数 / Parse arguments
ONEFILE=false
if [ "${1:-}" = "--onefile" ]; then
    ONEFILE=true
fi

# ---------------------------------------------------------------------------
# 检查依赖 / Check dependencies
# ---------------------------------------------------------------------------
log_section "Checking dependencies"

if ! command -v poetry &>/dev/null; then
    log_error "Poetry is not installed. Install it with: pip install poetry"
    exit 1
fi

# 安装 Python 项目依赖（仅生产依赖）/ Install Python project deps (production only)
log_info "Installing project dependencies..."
poetry install --only main --no-interaction

# 安装 Nuitka（如未安装）/ Install Nuitka if not present
PYTHON="$(poetry run python -c 'import sys; print(sys.executable)')"
log_info "Using Python: $PYTHON"

if ! poetry run python -c "import nuitka" &>/dev/null 2>&1; then
    log_info "Installing Nuitka..."
    poetry run pip install nuitka --quiet
fi
NUITKA_VERSION="$(poetry run python -m nuitka --version 2>&1 | head -1)"
log_info "Nuitka: $NUITKA_VERSION"

# ---------------------------------------------------------------------------
# 构建选项 / Build options
# ---------------------------------------------------------------------------
log_section "Building with Nuitka"

# 基础选项 / Base options
NUITKA_OPTS=(
    # 源文件 / Source file
    "--module-name=hikresetpasswd"

    # 输出目录 / Output directory
    "--output-dir=${DIST_DIR}"
    "--output-filename=hikresetpasswd"

    # 包含整个 hikresetpasswd 包及其所有子模块
    # Include the entire hikresetpasswd package and all submodules
    "--include-package=hikresetpasswd"

    # 包含关键依赖 / Include critical dependencies
    "--include-package=fastapi"
    "--include-package=uvicorn"
    "--include-package=starlette"
    "--include-package=pydantic"
    "--include-package=pydantic_core"
    "--include-package=anyio"
    "--include-package=httpx"
    "--include-package=PIL"
    "--include-package=cv2"
    "--include-package=dotenv"
    "--include-package=multipart"

    # 包含 pydantic 所需的数据文件
    # Include pydantic data files
    "--include-package-data=pydantic"

    # 独立模式（包含所有依赖，可在无 Python 环境的机器上运行）
    # Standalone mode (include all deps, runnable without Python)
    "--standalone"

    # 跟随包内导入 / Follow imports within packages
    "--follow-imports"

    # 禁用控制台窗口（可选，服务器程序通常保留控制台）
    # Disable console window (optional, server programs usually keep console)
    # "--windows-console-mode=disable"

    # 编译时优化 / Compile-time optimization
    "--python-flag=no_asserts"

    # 进度显示 / Show progress
    "--show-progress"
    "--show-scons"
)

# 单文件模式 / Single-file mode
if [ "$ONEFILE" = true ]; then
    log_info "Building in single-file (onefile) mode..."
    NUITKA_OPTS+=("--onefile")
else
    log_info "Building in standalone mode (distributable directory)..."
fi

# 入口点：__main__.py / Entry point: __main__.py
ENTRY_POINT="src/hikresetpasswd/__main__.py"

log_info "Entry point: $ENTRY_POINT"
log_info "Output directory: $DIST_DIR"

# 执行编译 / Run compilation
poetry run python -m nuitka "${NUITKA_OPTS[@]}" "$ENTRY_POINT"

# ---------------------------------------------------------------------------
# 编译后处理 / Post-build
# ---------------------------------------------------------------------------
log_section "Build Complete"

if [ "$ONEFILE" = true ]; then
    BINARY="$DIST_DIR/hikresetpasswd"
    if [ -f "${BINARY}.exe" ]; then
        BINARY="${BINARY}.exe"
    fi
    log_info "Standalone binary: $BINARY"
    log_info ""
    log_info "Run with:"
    log_info "  $BINARY"
    log_info ""
    log_info "Or with custom settings:"
    log_info "  HOST=0.0.0.0 PORT=8000 $BINARY"
else
    BINARY_DIR="$DIST_DIR/__main__.dist"
    log_info "Distributable directory: $BINARY_DIR"
    log_info ""
    log_info "To distribute: copy the entire $BINARY_DIR directory"
    log_info ""
    log_info "Run with:"
    log_info "  $BINARY_DIR/hikresetpasswd"
    log_info ""
    log_info "Or rename the directory and binary as needed."
fi

log_info ""
log_info "QR decoding uses pure OpenCV — no system-level libzbar required."
