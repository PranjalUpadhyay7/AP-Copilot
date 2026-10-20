#!/usr/bin/env bash
# Stop leftover AP-Copilot processes of this checkout (backend, frontend, simulator).
#   ./scripts/stop.sh            stop them (SIGTERM, then SIGKILL after 8 s)
#   ./scripts/stop.sh --dry-run  only list what would be stopped
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

pids=()
descs=()
for p in /proc/[0-9]*; do
    pid="${p#/proc/}"
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    cwd="$(readlink "$p/cwd" 2>/dev/null)" || continue
    cmd="$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)" || continue
    match=""
    case "$cwd" in
        "$REPO_ROOT/backend"*) [[ "$cmd" == *uvicorn* ]] && match="backend" ;;
        "$REPO_ROOT/frontend"*) [[ "$cmd" == *vite* || "$cmd" == *"npm run dev"* ]] && match="frontend" ;;
    esac
    [[ -z "$match" && ( "$cmd" == *Tools/autotest/sim_vehicle.py* || "$cmd" == *build/sitl/bin/ardu* ) ]] && match="simulator"
    if [[ -n "$match" ]]; then
        pids+=("$pid")
        descs+=("$match pid $pid: ${cmd:0:80}")
    fi
done

if (( ${#pids[@]} == 0 )); then
    echo "Nothing to stop: no AP-Copilot processes are running."
else
    printf '%s\n' "${descs[@]}"
    if (( DRY_RUN )); then
        echo "(dry run: nothing stopped)"
        exit 0
    fi
    kill -TERM "${pids[@]}" 2>/dev/null
    for _ in $(seq 1 8); do
        alive=0
        for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1; done
        (( alive )) || break
        sleep 1
    done
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "pid $pid ignored SIGTERM -- killing it"
            kill -KILL "$pid" 2>/dev/null
        fi
    done
    echo "Stopped."
fi

# Warn about other programs still holding a serial device
for dev in /dev/ttyACM* /dev/ttyUSB*; do
    [[ -e "$dev" ]] || continue
    holders="$(fuser "$dev" 2>/dev/null)"
    [[ -n "$holders" ]] && echo "WARNING: $dev is still open by pid(s):$holders -- close that program before connecting."
done
exit 0
