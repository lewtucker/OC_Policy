#!/usr/bin/env bash
# Start the OC Policy server.
# Usage:
#   ./start.sh                          # uses existing OC_POLICY_AGENT_TOKEN or generates one
#   OC_POLICY_AGENT_TOKEN=mytoken ./start.sh

set -e

cd "$(dirname "$0")"

# Generate a token if one isn't already set
if [ -z "$OC_POLICY_AGENT_TOKEN" ]; then
  export OC_POLICY_AGENT_TOKEN=$(openssl rand -hex 32)
  echo ""
  echo "  Generated token (save this — you'll need it to connect the UI and plugin):"
  echo ""
  echo "    OC_POLICY_AGENT_TOKEN=$OC_POLICY_AGENT_TOKEN"
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
