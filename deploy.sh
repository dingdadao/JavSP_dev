#!/usr/bin/env bash
# ============================================================
# JavSP Web 一键部署脚本 - 兼容 macOS / Linux
# 用法:
#   chmod +x deploy.sh && ./deploy.sh [start|stop|restart|status|logs|rebuild]
# ============================================================

set -euo pipefail

# ---------- 颜色 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---------- 路径 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/javsp/webapp/frontend"
DIST_DIR="$FRONTEND_DIR/dist"
PID_FILE="$SCRIPT_DIR/.javsp_web.pid"
LOG_FILE="$SCRIPT_DIR/javsp_web.log"
DB_FILE="$SCRIPT_DIR/javsp_web.db"

HOST="${JAVSP_HOST:-0.0.0.0}"
PORT="${JAVSP_PORT:-5001}"

# Poetry 安装后可能不在默认 PATH 中，提前探测
POETRY_BIN=""
for p in "$HOME/.local/bin/poetry" "$HOME/.poetry/bin/poetry" "/usr/local/bin/poetry"; do
    if [[ -x "$p" ]]; then
        POETRY_BIN="$(dirname "$p")"
        export PATH="$POETRY_BIN:$PATH"
        break
    fi
done

# ---------- 工具函数 ----------
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

detect_os() {
    case "$(uname -s)" in
        Darwin*) echo "macos" ;;
        Linux*)  echo "linux" ;;
        *)       echo "unknown" ;;
    esac
}

OS=$(detect_os)

# ---------- 环境检查与自动安装 ----------

ensure_basics() {
    # 检查最基本的工具：curl, git, sudo
    local missing=()
    if ! command -v curl &>/dev/null; then missing+=(curl); fi
    if ! command -v git &>/dev/null; then missing+=(git); fi
    if [[ ${#missing[@]} -gt 0 ]]; then
        warn "缺少基础工具: ${missing[*]}，尝试安装..."
        if [[ "$OS" == "linux" ]]; then
            if command -v apt-get &>/dev/null; then
                sudo apt-get update && sudo apt-get install -y "${missing[@]}"
            elif command -v yum &>/dev/null; then
                sudo yum install -y "${missing[@]}"
            elif command -v dnf &>/dev/null; then
                sudo dnf install -y "${missing[@]}"
            fi
        elif [[ "$OS" == "macos" ]]; then
            # macOS 通常自带 curl/git，如果缺少走 xcode-select
            xcode-select --install 2>/dev/null || true
        fi
    fi
    for cmd in curl git; do
        if ! command -v "$cmd" &>/dev/null; then
            error "缺少必要工具 '$cmd'，请手动安装后重试"
            exit 1
        fi
    done
    info "基础工具 (curl, git) ✓"
}

ensure_python() {
    if command -v python3 &>/dev/null; then
        info "Python $(python3 --version 2>&1 | awk '{print $2}') ✓"
        return 0
    fi
    warn "未找到 python3，尝试自动安装..."
    if [[ "$OS" == "macos" ]]; then
        if command -v brew &>/dev/null; then
            brew install python@3.10
        else
            error "请先安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            exit 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
        elif command -v yum &>/dev/null; then
            sudo yum install -y python3 python3-pip
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3 python3-pip
        else
            error "无法自动安装 Python，请手动安装 Python >= 3.10"
            exit 1
        fi
    fi
    if ! command -v python3 &>/dev/null; then
        error "Python 安装失败"
        exit 1
    fi
    info "Python $(python3 --version 2>&1 | awk '{print $2}') ✓"
}

ensure_poetry() {
    # 每次都尝试刷新 PATH（处理刚安装的情况）
    for p in "$HOME/.local/bin" "$HOME/.poetry/bin"; do
        if [[ -d "$p" ]]; then
            export PATH="$p:$PATH"
        fi
    done

    if command -v poetry &>/dev/null; then
        info "Poetry $(poetry --version 2>&1 | awk '{print $3}') ✓"
        return 0
    fi
    warn "未找到 Poetry，正在安装..."
    curl -sSL https://install.python-poetry.org | python3 -
    # 刷新 PATH
    for p in "$HOME/.local/bin" "$HOME/.poetry/bin"; do
        if [[ -d "$p" ]]; then
            export PATH="$p:$PATH"
        fi
    done
    if ! command -v poetry &>/dev/null; then
        error "Poetry 安装失败，请手动安装: https://python-poetry.org/docs/#installation"
        exit 1
    fi
    info "Poetry $(poetry --version 2>&1 | awk '{print $3}') ✓"
}

ensure_node() {
    if command -v node &>/dev/null; then
        local node_ver
        node_ver=$(node -v | sed 's/v//' | cut -d. -f1)
        if [[ "$node_ver" -ge 18 ]]; then
            info "Node.js $(node -v) ✓"
            return 0
        else
            warn "Node.js 版本过低 ($(node -v))，需要 >= 18，尝试升级..."
        fi
    else
        warn "未找到 Node.js，尝试自动安装..."
    fi

    if [[ "$OS" == "macos" ]]; then
        if command -v brew &>/dev/null; then
            brew install node
        else
            error "请先安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            exit 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            # 使用 NodeSource 安装最新 LTS
            curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
            sudo apt-get install -y nodejs
        elif command -v yum &>/dev/null; then
            curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
            sudo yum install -y nodejs
        elif command -v dnf &>/dev/null; then
            curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
            sudo dnf install -y nodejs
        else
            error "无法自动安装 Node.js，请手动安装 >= 18"
            exit 1
        fi
    fi

    if ! command -v node &>/dev/null; then
        error "Node.js 安装失败"
        exit 1
    fi
    info "Node.js $(node -v) ✓"
}

ensure_python_deps() {
    cd "$SCRIPT_DIR"
    # 检查虚拟环境是否存在且包含关键包
    local need_install=false
    if ! poetry run python -c "import flask" &>/dev/null; then
        need_install=true
    fi
    if ! poetry run python -c "import flask_socketio" &>/dev/null; then
        need_install=true
    fi
    if ! poetry run python -c "import watchdog" &>/dev/null; then
        need_install=true
    fi

    if [[ "$need_install" == "true" ]]; then
        info "安装 Python 依赖..."
        poetry install --no-interaction 2>&1 | tail -5
    fi
    info "Python 依赖就绪 ✓"
}

ensure_node_deps() {
    cd "$FRONTEND_DIR"
    if [[ ! -d "node_modules" ]] || [[ ! -f "node_modules/.package-lock.json" ]]; then
        info "安装前端依赖..."
        npm install 2>&1 | tail -5
    fi
    info "前端依赖就绪 ✓"
}

ensure_frontend_build() {
    if [[ ! -f "$DIST_DIR/index.html" ]]; then
        info "前端未构建，开始构建..."
        do_build
    else
        info "前端已构建 ✓"
    fi
}

# 一键检查并安装所有缺失依赖
ensure_all_deps() {
    echo -e "${CYAN}========== 检查依赖 ==========${NC}"
    ensure_basics
    ensure_python
    ensure_poetry
    ensure_node
    ensure_python_deps
    ensure_node_deps
    ensure_frontend_build
    echo -e "${CYAN}==============================${NC}"
}

# ---------- 构建前端 ----------
do_build() {
    info "正在构建前端..."
    cd "$FRONTEND_DIR"
    npm run build 2>&1 | grep -E "(built|error|✓)" || true

    if [[ -f "$DIST_DIR/index.html" ]]; then
        info "前端构建成功 ✓"
    else
        error "前端构建失败"
        exit 1
    fi
}

# ---------- 启动服务 ----------
do_start() {
    info "========== 启动 JavSP Web =========="

    # 检查是否已运行
    if [[ -f "$PID_FILE" ]]; then
        local old_pid
        old_pid=$(cat "$PID_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            warn "服务已在运行中 (PID: $old_pid)"
            warn "使用 './deploy.sh restart' 重启"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi

    # 一键检查并安装所有依赖
    ensure_all_deps

    cd "$SCRIPT_DIR"
    info "启动 Web 服务 ($HOST:$PORT)..."
    nohup poetry run python -m javsp.webapp.server --host "$HOST" --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 等待启动（最多 10 秒）
    local wait_count=0
    while [[ $wait_count -lt 10 ]]; do
        sleep 1
        wait_count=$((wait_count + 1))
        # 检查是否已经有输出或端口在监听
        if ! kill -0 "$pid" 2>/dev/null; then
            error "服务启动失败，查看日志: $LOG_FILE"
            tail -20 "$LOG_FILE" 2>/dev/null
            rm -f "$PID_FILE"
            exit 1
        fi
        # 检查端口是否已开始监听
        if curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
            break
        fi
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo ""
        info "=========================================="
        info "  JavSP Web 启动成功!"
        info "=========================================="
        info "  PID:       $pid"
        info "  地址:      http://$HOST:$PORT"
        info "  日志:      $LOG_FILE"
        info "  数据库:    $DB_FILE"
        info "  停止:      ./deploy.sh stop"
        info "  重启:      ./deploy.sh restart"
        info "  查看状态:  ./deploy.sh status"
        info "  实时日志:  ./deploy.sh logs"
        info "=========================================="
    else
        error "服务启动失败，查看日志: $LOG_FILE"
        tail -20 "$LOG_FILE" 2>/dev/null
        rm -f "$PID_FILE"
        exit 1
    fi
}

# ---------- 停止服务 ----------
do_stop() {
    info "========== 停止 JavSP Web =========="

    if [[ ! -f "$PID_FILE" ]]; then
        warn "未找到 PID 文件，服务可能未在运行"
        # 尝试通过端口查找进程（兼容 Linux / macOS）
        local port_pid=""
        if command -v lsof &>/dev/null; then
            port_pid=$(lsof -ti ":$PORT" 2>/dev/null || true)
        elif command -v ss &>/dev/null; then
            port_pid=$(ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K\d+' || true)
        elif command -v fuser &>/dev/null; then
            port_pid=$(fuser "$PORT/tcp" 2>/dev/null | tr -d ' ' || true)
        fi
        if [[ -n "$port_pid" ]]; then
            warn "发现端口 $PORT 上的进程 (PID: $port_pid)，正在停止..."
            kill "$port_pid" 2>/dev/null || true
            sleep 1
            info "已停止"
        fi
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        info "正在停止服务 (PID: $pid)..."
        kill "$pid"
        local wait_count=0
        while kill -0 "$pid" 2>/dev/null && [[ $wait_count -lt 10 ]]; do
            sleep 1
            wait_count=$((wait_count + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            warn "进程未响应，强制终止..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        info "服务已停止 ✓"
    else
        warn "进程 $pid 已不存在"
    fi
    rm -f "$PID_FILE"
}

# ---------- 重启服务 ----------
do_restart() {
    do_stop
    sleep 1
    do_start
}

# ---------- 重新构建并重启 ----------
do_rebuild() {
    info "========== 重新构建并重启 =========="
    do_stop
    # 强制重新构建前端
    rm -rf "$DIST_DIR"
    ensure_all_deps
    do_start
}

# ---------- 查看状态 ----------
do_status() {
    echo -e "${CYAN}========== JavSP Web 状态 ==========${NC}"

    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  服务状态:  ${GREEN}运行中${NC}"
            echo -e "  PID:       $pid"
            echo -e "  监听地址:  $HOST:$PORT"
            echo -e "  日志文件:  $LOG_FILE"

            if [[ "$OS" == "macos" ]]; then
                local mem cpu
                mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1f MB", $1/1024}')
                cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
                echo -e "  内存占用:  ${mem:-N/A}"
                echo -e "  CPU 占用:  ${cpu:-N/A}%"
            else
                local mem
                mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1f MB", $1/1024}')
                echo -e "  内存占用:  ${mem:-N/A}"
            fi
        else
            echo -e "  服务状态:  ${RED}已停止${NC} (PID 文件残留)"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "  服务状态:  ${RED}未运行${NC}"
    fi

    # 依赖检查
    echo ""
    echo -e "  ${CYAN}--- 依赖状态 ---${NC}"
    command -v python3 &>/dev/null && echo -e "  Python:    ${GREEN}$(python3 --version 2>&1 | awk '{print $2}')${NC}" || echo -e "  Python:    ${RED}未安装${NC}"
    command -v poetry  &>/dev/null && echo -e "  Poetry:    ${GREEN}$(poetry --version 2>&1 | awk '{print $3}')${NC}" || echo -e "  Poetry:    ${RED}未安装${NC}"
    command -v node    &>/dev/null && echo -e "  Node.js:   ${GREEN}$(node -v)${NC}" || echo -e "  Node.js:   ${RED}未安装${NC}"

    if [[ -f "$DIST_DIR/index.html" ]]; then
        local build_time
        build_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$DIST_DIR/index.html" 2>/dev/null || stat -c "%y" "$DIST_DIR/index.html" 2>/dev/null | cut -d. -f1)
        echo -e "  前端构建:  ${GREEN}已构建${NC} ($build_time)"
    else
        echo -e "  前端构建:  ${YELLOW}未构建${NC}"
    fi

    if [[ -f "$DB_FILE" ]]; then
        local db_size
        db_size=$(du -h "$DB_FILE" 2>/dev/null | cut -f1)
        echo -e "  数据库:    ${GREEN}存在${NC} ($db_size)"
    else
        echo -e "  数据库:    ${YELLOW}未创建${NC}"
    fi

    echo -e "${CYAN}====================================${NC}"
}

# ---------- 查看日志 ----------
do_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        info "实时日志 (Ctrl+C 退出):"
        tail -f "$LOG_FILE"
    else
        warn "日志文件不存在: $LOG_FILE"
    fi
}

# ---------- 帮助信息 ----------
show_help() {
    echo -e "${CYAN}JavSP Web 一键部署脚本${NC}  (macOS / Linux)"
    echo ""
    echo "用法: $0 <command>"
    echo ""
    echo "命令:"
    echo "  start     一键启动 (自动检查/安装依赖 → 构建前端 → 启动服务)"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  rebuild   重新构建前端并重启"
    echo "  status    查看运行状态和依赖信息"
    echo "  logs      实时查看日志"
    echo ""
    echo "环境变量:"
    echo "  JAVSP_HOST   监听地址 (默认: 0.0.0.0)"
    echo "  JAVSP_PORT   监听端口 (默认: 5001)"
    echo ""
    echo "快速开始:"
    echo "  chmod +x deploy.sh"
    echo "  ./deploy.sh start"
    echo ""
    echo "  # 自定义端口:"
    echo "  JAVSP_PORT=8080 ./deploy.sh start"
}

# ---------- 主入口 ----------
case "${1:-help}" in
    start)    do_start ;;
    stop)     do_stop ;;
    restart)  do_restart ;;
    rebuild)  do_rebuild ;;
    status)   do_status ;;
    logs)     do_logs ;;
    help|*)   show_help ;;
esac
