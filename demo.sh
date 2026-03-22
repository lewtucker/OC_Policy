#!/usr/bin/env bash
# demo.sh — Start both the OC Policy server and nanoclaw with a shared token.
# Usage: ./demo.sh
#
# NOTE: If you changed the nanoclaw policy hook (container/agent-runner/src/index.ts),
# you must also rebuild the Docker image and clear the per-group source cache:
#   rm -rf ~/Documents/dev/nanoclaw/data/sessions/telegram_main/agent-runner-src/
#   cd ~/Documents/dev/nanoclaw/container && docker build -t nanoclaw-agent .
# Then run this script. The hook runs inside Docker, not in the host tsx process.

set -e

TOKEN="mytoken"
SERVER_DIR="$HOME/Documents/dev/OC_Policy/src/server"
NANOCLAW_DIR="$HOME/Documents/dev/nanoclaw"

echo "=== OC Policy Demo ==="
echo "  Token: $TOKEN"
echo ""

# ── Kill existing processes ──────────────────────────────────────────────────
echo "Stopping any running server or nanoclaw..."

# Stop the launchd-managed nanoclaw service (prevents auto-restart)
UID_NUM=$(id -u)
if launchctl list com.nanoclaw &>/dev/null; then
  launchctl bootout "gui/$UID_NUM/com.nanoclaw" 2>/dev/null && echo "  Stopped launchd service com.nanoclaw" || true
  sleep 1
fi

pkill -9 -f "uvicorn server:app" 2>/dev/null && echo "  Killed uvicorn" || true
pkill -9 -f "tsx src/index.ts" 2>/dev/null && echo "  Killed nanoclaw (tsx)" || true
pkill -9 -f "node dist/index.js" 2>/dev/null && echo "  Killed nanoclaw (node)" || true

# Kill anything still holding ports 8080 (server) and 3001 (nanoclaw)
for port in 8080 3001; do
  pid=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill -9 $pid 2>/dev/null && echo "  Killed pid $pid on port $port" || true
  fi
done

sleep 2
echo ""

# ── Launch Policy Server in a new terminal ───────────────────────────────────
osascript -e 'tell application "Terminal"' \
          -e 'activate' \
          -e "do script \"echo '=== OC Policy Server ==='; export OC_POLICY_AGENT_TOKEN=$TOKEN; echo OC_POLICY_AGENT_TOKEN=$TOKEN; echo; cd $SERVER_DIR; uvicorn server:app --host 0.0.0.0 --port 8080 --reload\"" \
          -e 'end tell'

echo "Launched Policy Server in new Terminal window."

sleep 2

# ── Launch Nanoclaw in a new terminal ────────────────────────────────────────
osascript -e 'tell application "Terminal"' \
          -e 'activate' \
          -e "do script \"echo '=== Nanoclaw ==='; export OC_POLICY_AGENT_TOKEN=$TOKEN; echo OC_POLICY_AGENT_TOKEN=$TOKEN; echo; cd $NANOCLAW_DIR; npx tsx src/index.ts\"" \
          -e 'end tell'

echo "Launched Nanoclaw in new Terminal window."

# ── Open the UI in the browser ───────────────────────────────────────────────
sleep 2
open "http://localhost:8080?token=$TOKEN"
echo "Opened UI in browser."

echo ""
echo "=== Both processes started ==="
echo "  Server:   http://localhost:8080"
echo "  Token:    $TOKEN"
echo "  Check both Terminal windows for output."
