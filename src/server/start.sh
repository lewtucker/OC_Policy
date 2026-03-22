#!/usr/bin/env bash
# Start the OC Policy server.
# Usage:
#   ./start.sh                          # uses existing OC_POLICY_AGENT_TOKEN or generates one
#   OC_POLICY_AGENT_TOKEN=mytoken ./start.sh

set -e

cd "$(dirname "$0")"

# Kill any existing server on port 8080
pids=$(lsof -ti :8080 2>/dev/null || true)
if [ -n "$pids" ]; then
  echo "$pids" | xargs kill -9
  echo "  Killed existing server on port 8080."
fi

# Agent token — used by nanoclaw enforcement plugin only
if [ -z "$OC_POLICY_AGENT_TOKEN" ]; then
  export OC_POLICY_AGENT_TOKEN=$(openssl rand -hex 32)
  echo ""
  echo "  Generated agent token (for nanoclaw plugin only):"
  echo "    OC_POLICY_AGENT_TOKEN=$OC_POLICY_AGENT_TOKEN"
fi

# Admin token — used by the UI and CLI (humans managing policies)
if [ -z "$OC_POLICY_ADMIN_TOKEN" ]; then
  export OC_POLICY_ADMIN_TOKEN=$(openssl rand -hex 32)
  echo ""
  echo "  Generated admin token (for UI and /add-policy skill):"
  echo "    OC_POLICY_ADMIN_TOKEN=$OC_POLICY_ADMIN_TOKEN"
  echo ""
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "  Note: TELEGRAM_BOT_TOKEN not set — approval notifications disabled."
else
  echo "  Telegram notifications: enabled."
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "  Note: ANTHROPIC_API_KEY not set — NL policy chat disabled."
else
  echo "  NL policy chat: enabled."
fi
echo ""
echo "  Starting OC Policy Server on http://localhost:8080"
echo "  Open http://localhost:8080 in your browser to access the UI."
echo "  Press Ctrl-C to stop."
echo ""

uvicorn server:app --host 0.0.0.0 --port 8080 --reload
