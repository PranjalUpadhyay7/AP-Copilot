#!/usr/bin/env bash
# Start the backend (port 8000) and frontend (port 5173); Ctrl+C stops both.
set -um

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRACEFUL_SHUTDOWN_TIMEOUT=20

BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=0

pgid_of() { ps -o pgid= -p "$1" 2>/dev/null | tr -d ' '; }

# Each job is its own process group (set -m), so signal the whole group, not just uv/npm.
signal_group() {
    local pid="$1" sig="$2"
    [[ -z "$pid" ]] && return
    kill -0 "$pid" 2>/dev/null || return
    if [[ "$(pgid_of "$pid")" == "$pid" ]]; then
        kill "-$sig" -- "-$pid" 2>/dev/null
    else
        kill "-$sig" "$pid" 2>/dev/null
    fi
}

cleanup() {
    [[ "$CLEANED_UP" == 1 ]] && return
    CLEANED_UP=1
    echo
    echo "Stopping AP-Copilot..."
    signal_group "$BACKEND_PID" TERM
    signal_group "$FRONTEND_PID" TERM

    local waited=0
    while (( waited < GRACEFUL_SHUTDOWN_TIMEOUT )); do
        kill -0 "$BACKEND_PID" 2>/dev/null || kill -0 "$FRONTEND_PID" 2>/dev/null || break
        sleep 1
        ((waited++))
    done

    signal_group "$BACKEND_PID" KILL
    signal_group "$FRONTEND_PID" KILL
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    echo "Stopped."
}
trap cleanup EXIT INT TERM

# Optional local settings (ARDUPILOT_ROOT, AP_COPILOT_HOME, uv caches...); not committed.
if [[ -f "$REPO_ROOT/env.sh" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/env.sh"
fi
echo "  Data home: ${AP_COPILOT_HOME:-$HOME/.ap-copilot}"

# Node comes from nvm in most setups; load it when this shell did not (non-interactive or fresh terminals).
if ! command -v npm >/dev/null 2>&1; then
    export NVM_DIR="${NVM_HOME:-$HOME/.nvm}"
    # shellcheck disable=SC1091
    if [[ -s "$NVM_DIR/nvm.sh" ]]; then
        set +u
        source "$NVM_DIR/nvm.sh" >/dev/null 2>&1
        command -v npm >/dev/null 2>&1 || nvm use --silent node >/dev/null 2>&1
        set -u
    fi
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found. Install Node.js 20+ (https://nodejs.org or nvm) and run this again." >&2
    exit 1
fi

# Always run the backend in its own environment, even if the shell exports another uv project's.
export UV_PROJECT_ENVIRONMENT="$REPO_ROOT/backend/.venv"

# Two backends on one machine would fight over the flight controller's serial port.
for port in 8000 5173; do
    holder="$(ss -ltnp 2>/dev/null | grep -E "[:.]${port}\\b" | head -1)"
    if [[ -n "$holder" ]]; then
        echo "Port $port is already in use -- AP-Copilot looks like it is already running:" >&2
        echo "  $holder" >&2
        echo "Run ./scripts/stop.sh first, then start again." >&2
        exit 1
    fi
done

(cd "$REPO_ROOT/backend" && exec uv run uvicorn app.main:app --timeout-graceful-shutdown 5) &
BACKEND_PID=$!

(cd "$REPO_ROOT/frontend" && exec npm run dev -- --strictPort) &
FRONTEND_PID=$!

echo "AP-Copilot starting..."
echo "  Backend:  http://127.0.0.1:8000"
echo "  Frontend: http://127.0.0.1:5173  <- open this in your browser"
echo "Press Ctrl+C to stop both."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
