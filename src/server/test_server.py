"""
Dummy OpenClaw — Phase 1 acceptance tests.

Simulates the plugin's HTTP calls to the policy server and verifies
the server returns the correct verdict for each scenario.

Usage:
    OC_POLICY_AGENT_TOKEN=<token> python test_server.py [--url http://localhost:8080]
"""
import os
import sys
import json
import urllib.request
import urllib.error
import argparse

# ── Config ────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8080")
args = parser.parse_args()

SERVER_URL  = args.url.rstrip("/")
AGENT_TOKEN = os.environ.get("OC_POLICY_AGENT_TOKEN", "")

RESET  = "\033[0m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"


# ── HTTP helper ───────────────────────────────────────────────────────────────
def post_check(tool: str, params: dict) -> dict:
    """POST /check and return the parsed response body."""
    payload = json.dumps({"tool": tool, "params": params}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/check",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AGENT_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def get_health() -> dict:
    req = urllib.request.Request(f"{SERVER_URL}/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


# ── Test runner ───────────────────────────────────────────────────────────────
passed = 0
failed = 0


def run(label: str, tool: str, params: dict, expect_verdict: str):
    global passed, failed
    print(f"\n  {BOLD}{label}{RESET}")
    print(f"    tool={tool!r}  params={params}")
    try:
        body = post_check(tool, params)
        verdict = body.get("verdict")
        reason  = body.get("reason", "")
        ok = verdict == expect_verdict
        status = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"    verdict={verdict!r}  reason={reason!r}")
        print(f"    [{status}] expected {expect_verdict!r}, got {verdict!r}")
        if ok:
            passed += 1
        else:
            failed += 1
    except urllib.error.HTTPError as e:
        print(f"    [{RED}ERROR{RESET}] HTTP {e.code}: {e.read().decode()}")
        failed += 1
    except Exception as e:
        print(f"    [{RED}ERROR{RESET}] {e}")
        failed += 1


# ── Tests ─────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}=== OC Policy Server — Phase 1 acceptance tests ==={RESET}")
print(f"    Server: {SERVER_URL}")

# Health check
print(f"\n  {BOLD}0. Health check{RESET}")
try:
    h = get_health()
    print(f"    {GREEN}OK{RESET} — {h}")
except Exception as e:
    print(f"    {RED}FAIL — server not reachable: {e}{RESET}")
    print(f"\n  {YELLOW}Start the server first:{RESET}")
    print(f"    OC_POLICY_AGENT_TOKEN=<token> uvicorn server:app --port 8080 --reload")
    sys.exit(1)

# Test 1 — git should be ALLOWED
run(
    "Test 1 — git exec → ALLOW",
    tool="exec",
    params={"command": "git status"},
    expect_verdict="allow",
)

# Test 2 — ls should be DENIED
run(
    "Test 2 — ls exec → DENY",
    tool="exec",
    params={"command": "ls -la /tmp"},
    expect_verdict="deny",
)

# Test 3 — unknown tool should be DENIED
run(
    "Test 3 — unknown tool → DENY",
    tool="read_file",
    params={"path": "/etc/passwd"},
    expect_verdict="deny",
)

# Test 4 — git with args should be ALLOWED
run(
    "Test 4 — git with args → ALLOW",
    tool="exec",
    params={"command": "git log --oneline -5"},
    expect_verdict="allow",
)

# Test 5 — empty command should be DENIED
run(
    "Test 5 — empty command → DENY",
    tool="exec",
    params={"command": ""},
    expect_verdict="deny",
)

# ── Summary ───────────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{BOLD}=== Results: {passed}/{total} passed ==={RESET}")
if failed:
    print(f"  {RED}{failed} test(s) failed{RESET}")
    sys.exit(1)
else:
    print(f"  {GREEN}All tests passed{RESET}")
