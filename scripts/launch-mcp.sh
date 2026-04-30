#!/usr/bin/env bash
# launch-mcp.sh — bootstrap and start the baba-credits MCP server (Linux/macOS).
#
# What it does:
#   1. Finds a Python >= 3.10 interpreter (the `mcp` SDK requires it).
#   2. Creates a local virtualenv at <repo>/.venv if missing.
#   3. Installs the three MCP runtime deps (mcp, httpx, pydantic) if missing.
#   4. Loads <repo>/.env.mcp if present (BABA_GATEWAY_URL, MCP_TRANSPORT, …).
#   5. Health-checks the gateway URL (read-only HEAD/POST to /api/Diag/GetSupply).
#   6. Launches `python -m baba_mcp.server` and forwards exit code.
#
# Usage:
#   bash scripts/launch-mcp.sh                    # stdio transport (default)
#   MCP_TRANSPORT=http bash scripts/launch-mcp.sh # HTTP/SSE transport
#   bash scripts/launch-mcp.sh --no-pip           # skip pip install (faster relaunch)
#   bash scripts/launch-mcp.sh --reinstall        # force reinstall of MCP deps
#
# Exit codes:
#   0 — server exited cleanly (e.g. SIGINT)
#   1 — bootstrap failure (Python missing, venv broken, deps install failed)
#   2 — gateway health-check failed (skip with SKIP_GATEWAY_CHECK=1)
#   anything else — propagated from `python -m baba_mcp.server`

set -euo pipefail

# ----- Paths --------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
ENV_FILE="$REPO_ROOT/.env.mcp"

# ----- ANSI helpers -------------------------------------------------------
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BOLD=''; NC=''
fi
ok()    { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
err()   { printf "${RED}✗${NC} %s\n" "$*" >&2; }
step()  { printf "\n${BOLD}%s${NC}\n" "$*"; }

# ----- Args ---------------------------------------------------------------
SKIP_PIP=0
REINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --no-pip)    SKIP_PIP=1 ;;
        --reinstall) REINSTALL=1 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            err "Unknown argument: $arg"
            exit 1
            ;;
    esac
done

# ----- 1. Find Python >= 3.10 ---------------------------------------------
step "1. Locating a Python >= 3.10 interpreter"
PY_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver=$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
        major=${ver%%.*}; minor=${ver##*.}
        if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
            PY_BIN="$cand"
            ok "Found $cand (Python $ver)"
            break
        fi
    fi
done

if [ -z "$PY_BIN" ]; then
    err "No Python >= 3.10 found in PATH."
    err "Install one of:"
    err "  - Linux:  apt install python3.11 python3.11-venv  (or your distro's equivalent)"
    err "  - macOS:  brew install python@3.11"
    err "  - Or use pyenv / asdf to manage multiple versions."
    exit 1
fi

# ----- 2. Create / reuse virtualenv ---------------------------------------
step "2. Setting up virtualenv at $VENV_DIR"
VENV_PY=""
if [ -x "$VENV_DIR/bin/python" ]; then
    VENV_PY="$VENV_DIR/bin/python"
    ver=$("$VENV_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    major=${ver%%.*}; minor=${ver##*.}
    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
        ok "Reusing existing venv (Python $ver)"
    else
        warn "Existing venv has Python $ver, recreating with $PY_BIN"
        rm -rf "$VENV_DIR"
        VENV_PY=""
    fi
fi
if [ -z "$VENV_PY" ]; then
    "$PY_BIN" -m venv "$VENV_DIR" || {
        err "Failed to create venv. On Debian/Ubuntu try:  apt install ${PY_BIN}-venv"
        exit 1
    }
    VENV_PY="$VENV_DIR/bin/python"
    ok "Venv created"
fi

# ----- 3. Install MCP deps ------------------------------------------------
step "3. Verifying MCP dependencies"
need_install=$REINSTALL
if [ $REINSTALL -eq 0 ] && [ $SKIP_PIP -eq 0 ]; then
    if ! "$VENV_PY" -c 'import mcp, httpx, pydantic' 2>/dev/null; then
        need_install=1
    fi
fi
if [ $need_install -eq 1 ] && [ $SKIP_PIP -eq 0 ]; then
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    if [ -f "$REPO_ROOT/requirements.txt" ]; then
        "$VENV_PY" -m pip install -r "$REPO_ROOT/requirements.txt" || {
            err "pip install failed"
            exit 1
        }
    else
        "$VENV_PY" -m pip install 'mcp>=1.0.0' 'httpx>=0.27.0' 'pydantic>=2.5.0' || {
            err "pip install failed"
            exit 1
        }
    fi
    ok "Dependencies installed"
else
    ok "All deps already present (use --reinstall to force)"
fi

# ----- 4. Load .env.mcp ---------------------------------------------------
step "4. Loading environment"
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
    ok "Loaded $ENV_FILE"
else
    warn "$ENV_FILE not found — using defaults / shell env vars only"
fi
: "${BABA_GATEWAY_URL:=http://127.0.0.1:5000}"
: "${MCP_TRANSPORT:=stdio}"
: "${MCP_HTTP_HOST:=127.0.0.1}"
: "${MCP_HTTP_PORT:=7000}"
export BABA_GATEWAY_URL MCP_TRANSPORT MCP_HTTP_HOST MCP_HTTP_PORT
printf "  Gateway:   %s\n" "$BABA_GATEWAY_URL"
printf "  Transport: %s" "$MCP_TRANSPORT"
[ "$MCP_TRANSPORT" = "http" ] && printf " on %s:%s" "$MCP_HTTP_HOST" "$MCP_HTTP_PORT"
echo

# ----- 5. Gateway health-check --------------------------------------------
step "5. Gateway health-check"
if [ "${SKIP_GATEWAY_CHECK:-0}" = "1" ]; then
    warn "Skipped (SKIP_GATEWAY_CHECK=1)"
elif command -v curl >/dev/null 2>&1; then
    if body=$(curl -fsS -m 5 -X POST "$BABA_GATEWAY_URL/api/Diag/GetSupply" \
                  -H "Content-Type: application/json" -d '{}' 2>&1); then
        if echo "$body" | grep -q '"success":[[:space:]]*true'; then
            ok "Gateway reachable (Diag/GetSupply returned success)"
        else
            warn "Gateway reachable but response unexpected: ${body:0:80}"
        fi
    else
        err "Gateway unreachable at $BABA_GATEWAY_URL"
        err "Set BABA_GATEWAY_URL or start the gateway, or pass SKIP_GATEWAY_CHECK=1"
        exit 2
    fi
else
    warn "curl not installed — skipping health-check"
fi

# ----- 6. Launch ----------------------------------------------------------
step "6. Starting MCP server"
cd "$REPO_ROOT"
exec "$VENV_PY" -m baba_mcp.server
