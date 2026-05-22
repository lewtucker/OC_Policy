#!/usr/bin/env bash
# Install the OC Policy enforcement hook into a nanoclaw repository.
#
# Usage:
#   ./install.sh <path-to-nanoclaw-repo>
#
# What it patches:
#   - src/config.ts                        — adds OC Policy vars to .env allowlist
#   - src/container-runner.ts              — passes OC Policy vars into Docker containers
#   - container/agent-runner/src/index.ts  — registers the PreToolUse enforcement hook
#
# After applying, the hook is controlled by three vars in nanoclaw/.env:
#   OC_POLICY_SERVER_URL=http://host.docker.internal:8080
#   OC_POLICY_AGENT_TOKEN=<your-agent-token>   # must match policy server
#   OC_POLICY_ENABLED=true                     # set to "false" to disable without removing token

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH="$SCRIPT_DIR/oc-policy-hook.patch"

if [ -z "$1" ]; then
  echo "Usage: $0 <path-to-nanoclaw-repo>"
  exit 1
fi

NANOCLAW_DIR="$(cd "$1" && pwd)"

if [ ! -f "$NANOCLAW_DIR/package.json" ]; then
  echo "Error: $NANOCLAW_DIR does not look like a nanoclaw repo (no package.json found)"
  exit 1
fi

echo ""
echo "Applying OC Policy hook to: $NANOCLAW_DIR"
echo ""

cd "$NANOCLAW_DIR"
git apply "$PATCH"

echo "Patch applied successfully."
echo ""
echo "Files changed:"
echo "  src/config.ts                       — OC Policy vars added to .env allowlist"
echo "  src/container-runner.ts             — OC Policy vars passed into Docker containers"
echo "  container/agent-runner/src/index.ts — PreToolUse enforcement hook registered"
echo ""
echo "Next steps:"
echo ""
echo "  1. Add to $NANOCLAW_DIR/.env:"
echo "       OC_POLICY_SERVER_URL=http://host.docker.internal:8080"
echo "       OC_POLICY_AGENT_TOKEN=<your-agent-token>   # must match policy server"
echo "       OC_POLICY_ENABLED=true                     # set to false to disable"
echo ""
echo "  2. Clear the per-group agent-runner cache:"
echo "       rm -rf $NANOCLAW_DIR/data/sessions/*/agent-runner-src/"
echo ""
echo "  3. Rebuild the Docker image:"
echo "       cd $NANOCLAW_DIR/container && docker build -t nanoclaw-agent ."
echo ""
echo "  4. Start nanoclaw:"
echo "       cd $NANOCLAW_DIR && npx tsx src/index.ts"
echo ""
