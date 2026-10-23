#!/usr/bin/env bash
set -euo pipefail

# === Optional duration ===
if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [seconds]"
  exit 1
fi

DURATION="${1:-}"
if [ -n "$DURATION" ] && { ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [ "$DURATION" -lt 1 ]; }; then
  echo "Duration must be a positive whole number of seconds."
  exit 1
fi
ROOT_DIR="$(pwd)"
DAEMON_DIR="$ROOT_DIR/daemon"
LOG_PATH="$DAEMON_DIR/logs/data.log"
ETC_DIR="$DAEMON_DIR/etc"

# === Paths for venv Python + Pip ===
VENV_BIN="$ROOT_DIR/venv/bin"
PYTHON="$VENV_BIN/python"
PIP="$VENV_BIN/pip"
STARTED_LOCAL_QDRANT=0
DAEMON_PID=""
MAIN_PID=""
TMP_RUN=""

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM
  echo "[INFO] Stopping processes..."
  if [ -n "$DAEMON_PID" ]; then
    kill -TERM "$DAEMON_PID" 2>/dev/null || true
    wait "$DAEMON_PID" 2>/dev/null || true
  fi

  # Let Fluentd flush final records during normal/timed shutdown. Ctrl+C means
  # stop promptly and leave queued records for a later run.
  if [ "$exit_status" -ne 130 ] && [ "$exit_status" -ne 143 ]; then
    sleep 2
  fi

  echo "[INFO] Stopping Fluentd container..."
  docker stop fluentd >/dev/null 2>&1 || true
  docker rm fluentd >/dev/null 2>&1 || true

  # Drain flushed records on normal/timed shutdown. Ctrl+C interrupts the active
  # request and skips the queue so the user can stop the service promptly.
  if [ -n "$MAIN_PID" ]; then
    if [ "$exit_status" -eq 130 ]; then
      kill -INT "$MAIN_PID" 2>/dev/null || true
    else
      kill -TERM "$MAIN_PID" 2>/dev/null || true
    fi
    wait "$MAIN_PID" 2>/dev/null || true
  fi

  if [ "$STARTED_LOCAL_QDRANT" -eq 1 ]; then
    echo "[INFO] Stopping local Qdrant container..."
    docker stop qdrant >/dev/null 2>&1 || true
  fi

  if [ -n "$TMP_RUN" ]; then
    rm -f "$TMP_RUN"
  fi

  # === Clear logs inside data.log (file or dir) ===
  if [ -f "$LOG_PATH" ]; then
    > "$LOG_PATH"
    echo "[INFO] Cleared file: $LOG_PATH"
  elif [ -d "$LOG_PATH" ]; then
    rm -rf "$LOG_PATH"/* || true
    echo "[INFO] Cleared directory contents: $LOG_PATH"
  else
    echo "[WARN] $LOG_PATH not found"
  fi

  echo "[INFO] Done."
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# === 0. Prep fix for docker mount ===
mkdir -p "$ETC_DIR"
cp "$DAEMON_DIR/fluent.conf" "$ETC_DIR/fluent.conf"

# === 1. Stop & remove any old fluentd container ===
if docker ps -a --filter "name=fluentd" --format '{{.Names}}' | grep -q '^fluentd$'; then
  echo "[INFO] Removing existing Fluentd container..."
  docker stop fluentd >/dev/null 2>&1 || true
  docker rm fluentd >/dev/null 2>&1 || true
fi

# === 2. Run docker_run script (patched with UID:GID and correct paths) ===
echo "[INFO] Starting Fluentd container..."
TMP_RUN=$(mktemp)

# Replace paths inside docker_run with absolute daemon paths
sed \
  -e "s|\$(pwd)/logs|$DAEMON_DIR/logs|" \
  -e "s|\$(pwd)/fluent.conf|$DAEMON_DIR/fluent.conf|" \
  -e "s|--user root|--user $(id -u):$(id -g)|" \
  "$DAEMON_DIR/docker_run" > "$TMP_RUN"

bash "$TMP_RUN"
rm -f "$TMP_RUN"
TMP_RUN=""

# === 3. Start local Qdrant if the configured endpoint is the local default ===
if [ -z "${QDRANT_HOST:-}" ] && [ -z "$(grep '^QDRANT_HOST=' "$ROOT_DIR/.env" 2>/dev/null || true)" ]; then
  echo "[INFO] Starting local Qdrant container..."
  if docker ps -a --filter 'name=^/qdrant$' --format '{{.Names}}' | grep -q '^qdrant$'; then
    if ! docker ps --filter 'name=^/qdrant$' --format '{{.Names}}' | grep -q '^qdrant$'; then
      docker start qdrant >/dev/null
      STARTED_LOCAL_QDRANT=1
    fi
  else
    docker run -d \
      -p 6333:6333 \
      -p 6334:6334 \
      -v lad_qdrant_storage:/qdrant/storage \
      --name qdrant \
      qdrant/qdrant
    STARTED_LOCAL_QDRANT=1
  fi
fi

# Give Fluentd and local Qdrant a little time to start
sleep 3

# === 4. Ensure Python deps (inside venv only) ===
echo "[INFO] Ensuring Python dependencies..."
if [ -f "$ROOT_DIR/requirements.txt" ]; then
  "$PIP" install -q -r "$ROOT_DIR/requirements.txt"
else
  echo "[WARN] requirements.txt not found, skipping pip install"
fi

# === 5. Run daemon.py ===
echo "[INFO] Starting daemon.py..."
"$PYTHON" "$DAEMON_DIR/daemon.py" "$DAEMON_DIR/config.yaml" &
DAEMON_PID=$!

# === 6. Run main.py ===
echo "[INFO] Starting main.py..."
"$PYTHON" "$ROOT_DIR/scripts/main.py" "$DAEMON_DIR/config.yaml" &
MAIN_PID=$!

# === 7. Run until the optional duration expires or the user presses Ctrl+C ===
if [ -n "$DURATION" ]; then
  echo "[INFO] Running for $DURATION seconds... (Ctrl+C to stop)"
  sleep "$DURATION"
else
  echo "[INFO] Running until Ctrl+C..."
  while true; do
    sleep 3600 &
    wait "$!" || true
  done
fi
