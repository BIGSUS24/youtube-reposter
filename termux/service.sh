#!/data/data/com.termux/files/usr/bin/sh
# Supervisor for Termux: restarts only after an unexpected process exit.
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
LOG="$ROOT/logs/service.log"
CHILD=""

stop() {
    [ -n "$CHILD" ] && kill "$CHILD" 2>/dev/null || true
    exit 0
}
trap stop INT TERM HUP

if [ ! -x "$PYTHON" ]; then
    echo "Run ./termux/install.sh first." >&2
    exit 1
fi

mkdir -p "$ROOT/logs"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

delay=5
while :; do
    cd "$ROOT" || exit 1
    "$PYTHON" -u main.py >>"$LOG" 2>&1 &
    CHILD=$!
    wait "$CHILD"
    status=$?
    CHILD=""
    [ "$status" -eq 0 ] && exit 0
    echo "$(date -Iseconds) main.py exited ($status); restarting in ${delay}s" >>"$LOG"
    sleep "$delay"
    [ "$delay" -lt 300 ] && delay=$((delay * 2))
    [ "$delay" -gt 300 ] && delay=300
done
