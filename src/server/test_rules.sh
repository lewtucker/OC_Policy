#!/usr/bin/env bash
# test_rules.sh — smoke-test policy rules against the running server.
# Usage:
#   OC_POLICY_AGENT_TOKEN=mytoken ./test_rules.sh
#   OC_POLICY_AGENT_TOKEN=mytoken ./test_rules.sh http://localhost:8080

set -euo pipefail

SERVER="${1:-http://localhost:8080}"
TOKEN="${OC_POLICY_AGENT_TOKEN:?OC_POLICY_AGENT_TOKEN must be set}"

# Telegram channel IDs from identities.yaml
LEW="tg:6741893378"
ALICE="tg:111222333"
BOB="tg:444555666"
LEW_SHALA="tg:-5235231470"
UNKNOWN=""   # no channel_id = anonymous

PASS=0; FAIL=0

check() {
  local desc="$1" channel="$2" tool="$3" params="$4" want="$5"

  local body
  if [ -n "$channel" ]; then
    body=$(printf '{"tool":"%s","params":%s,"channel_id":"%s"}' "$tool" "$params" "$channel")
  else
    body=$(printf '{"tool":"%s","params":%s}' "$tool" "$params")
  fi

  local response verdict
  response=$(curl -s -X POST "$SERVER/check" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body")
  verdict=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('verdict','ERROR'))")

  local subject="${channel:-anonymous}"
  if [ "$verdict" = "$want" ]; then
    printf "  ✓  %-45s  %-12s  → %s\n" "$desc" "($subject)" "$verdict"
    PASS=$((PASS+1))
  else
    printf "  ✗  %-45s  %-12s  → %s (expected %s)\n" "$desc" "($subject)" "$verdict" "$want"
    FAIL=$((FAIL+1))
  fi
}

echo ""
echo "OC Policy Rule Tests  —  $SERVER"
echo "─────────────────────────────────────────────────────────────────────"

echo ""
echo "Lew (admin, person-scoped allow-all):"
check "git commit — Lew"          "$LEW"      "Bash" '{"command":"git commit -m test"}' "allow"
check "rm -rf /tmp — Lew"         "$LEW"      "Bash" '{"command":"rm -rf /tmp"}'        "allow"
check "ls /workspace — Lew"       "$LEW"      "Bash" '{"command":"ls /workspace"}'      "allow"
check "WebFetch — Lew"            "$LEW"      "WebFetch" '{"url":"https://example.com"}' "allow"

echo ""
echo "Alice (admin group, no personal override):"
check "ls /workspace — Alice"     "$ALICE"    "Bash" '{"command":"ls /workspace"}'      "allow"
check "cat README — Alice"        "$ALICE"    "Bash" '{"command":"cat README"}'          "allow"
check "git push — Alice"          "$ALICE"    "Bash" '{"command":"git push"}'            "pending"
check "rm -rf /tmp — Alice"       "$ALICE"    "Bash" '{"command":"rm -rf /tmp"}'        "deny"

echo ""
echo "Bob (engineering group):"
check "git status — Bob"          "$BOB"      "Bash" '{"command":"git status"}'         "pending"
check "rm -rf /tmp — Bob"         "$BOB"      "Bash" '{"command":"rm -rf /tmp"}'        "deny"
check "ls /workspace — Bob"       "$BOB"      "Bash" '{"command":"ls /workspace"}'      "deny"
check "WebFetch — Bob"            "$BOB"      "WebFetch" '{"url":"https://example.com"}' "deny"

echo ""
echo "Lew+Shala (team group):"
check "git status — Lew+Shala"    "$LEW_SHALA" "Bash" '{"command":"git status"}'        "pending"
check "rm -rf /tmp — Lew+Shala"   "$LEW_SHALA" "Bash" '{"command":"rm -rf /tmp"}'       "deny"

echo ""
echo "Anonymous (no identity):"
check "git status — anonymous"    "$UNKNOWN"  "Bash" '{"command":"git status"}'         "pending"
check "rm -rf /tmp — anonymous"   "$UNKNOWN"  "Bash" '{"command":"rm -rf /tmp"}'        "deny"
check "ls /workspace — anonymous" "$UNKNOWN"  "Bash" '{"command":"ls /workspace"}'      "deny"

echo ""
echo "─────────────────────────────────────────────────────────────────────"
printf "  %d passed, %d failed\n\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
