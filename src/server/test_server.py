"""
Dummy OpenClaw — Phase 2 acceptance tests.

Simulates the plugin's HTTP calls to the policy server and verifies
correct verdicts, plus exercises the policy CRUD endpoints.

Usage:
    OC_POLICY_AGENT_TOKEN=<token> python3 test_server.py [--url http://localhost:8080]
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
DIM    = "\033[2m"

passed = 0
failed = 0


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def request(method: str, path: str, body: dict | None = None) -> dict | None:
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
    if payload:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{SERVER_URL}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


def check(tool: str, params: dict) -> dict:
    return request("POST", "/check", {"tool": tool, "params": params})


# ── Test runner ───────────────────────────────────────────────────────────────

def run(label: str, fn, expect):
    global passed, failed
    print(f"\n  {BOLD}{label}{RESET}")
    try:
        result = fn()
        ok = expect(result)
        status = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"    result={result}")
        print(f"    [{status}]")
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"    [{RED}ERROR{RESET}] {e}")
        failed += 1


# ── Tests ─────────────────────────────────────────────────────────────────────

print(f"\n{BOLD}=== OC Policy Server — Phase 2 acceptance tests ==={RESET}")
print(f"    Server: {SERVER_URL}")

# Health
print(f"\n  {BOLD}0. Health check{RESET}")
try:
    h = request("GET", "/health")
    print(f"    {GREEN}OK{RESET} — {h}")
except Exception as e:
    print(f"    {RED}FAIL — server not reachable: {e}{RESET}")
    print(f"\n  {YELLOW}Start the server first:{RESET}")
    print(f"    OC_POLICY_AGENT_TOKEN=<token> uvicorn server:app --port 8080 --reload")
    sys.exit(1)

# ── Group 1: baseline rules (from policies.yaml) ──────────────────────────────
print(f"\n{DIM}── Baseline rules ──────────────────────────────────────────────{RESET}")

run("1. git exec → ALLOW (from YAML)",
    lambda: check("exec", {"command": "git status"}),
    lambda r: r["verdict"] == "allow")

run("2. ls exec → DENY (no matching rule)",
    lambda: check("exec", {"command": "ls -la /tmp"}),
    lambda r: r["verdict"] == "deny")

run("3. unknown tool → DENY",
    lambda: check("read_file", {"path": "/etc/passwd"}),
    lambda r: r["verdict"] == "deny")

run("4. git with args → ALLOW",
    lambda: check("exec", {"command": "git log --oneline -5"}),
    lambda r: r["verdict"] == "allow")

run("5. empty command → DENY",
    lambda: check("exec", {"command": ""}),
    lambda r: r["verdict"] == "deny")

# ── Group 2: policy CRUD ──────────────────────────────────────────────────────
print(f"\n{DIM}── Policy CRUD ─────────────────────────────────────────────────{RESET}")

run("6. GET /policies lists rules",
    lambda: request("GET", "/policies"),
    lambda r: "policies" in r and len(r["policies"]) > 0)

run("7. POST /policies adds allow-npm rule",
    lambda: request("POST", "/policies", {
        "id": "allow-npm",
        "description": "Allow npm commands",
        "effect": "allow",
        "priority": 10,
        "match": {"tool": "exec", "program": "npm"},
    }),
    lambda r: r["id"] == "allow-npm")

run("8. npm exec → ALLOW after adding rule",
    lambda: check("exec", {"command": "npm install"}),
    lambda r: r["verdict"] == "allow")

run("9. DELETE /policies/allow-npm removes it",
    lambda: request("DELETE", "/policies/allow-npm"),
    lambda r: r is None)  # 204 No Content

run("10. npm exec → DENY after removing rule",
    lambda: check("exec", {"command": "npm install"}),
    lambda r: r["verdict"] == "deny")

# ── Group 3: priority ─────────────────────────────────────────────────────────
print(f"\n{DIM}── Priority: deny beats allow for same program ─────────────────{RESET}")

# Add a low-priority allow for curl, then a high-priority deny
run("11. Add low-priority allow-curl (priority 5)",
    lambda: request("POST", "/policies", {
        "id": "allow-curl",
        "effect": "allow",
        "priority": 5,
        "match": {"tool": "exec", "program": "curl"},
    }),
    lambda r: r["id"] == "allow-curl")

run("12. curl → ALLOW at priority 5",
    lambda: check("exec", {"command": "curl https://example.com"}),
    lambda r: r["verdict"] == "allow")

run("13. Add high-priority deny-curl (priority 50)",
    lambda: request("POST", "/policies", {
        "id": "deny-curl",
        "description": "Block curl — use approved HTTP clients only",
        "effect": "deny",
        "priority": 50,
        "match": {"tool": "exec", "program": "curl"},
    }),
    lambda r: r["id"] == "deny-curl")

run("14. curl → DENY — high-priority deny beats low-priority allow",
    lambda: check("exec", {"command": "curl https://example.com"}),
    lambda r: r["verdict"] == "deny")

# ── Cleanup ───────────────────────────────────────────────────────────────────
print(f"\n{DIM}── Cleanup ──────────────────────────────────────────────────────{RESET}")

run("15. Remove allow-curl and deny-curl",
    lambda: (
        request("DELETE", "/policies/allow-curl"),
        request("DELETE", "/policies/deny-curl"),
    ),
    lambda r: True)

run("16. POST /policies/reload — rules reload from disk",
    lambda: request("POST", "/policies/reload"),
    lambda r: "reloaded" in r)

# ── Summary ───────────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{BOLD}=== Results: {passed}/{total} passed ==={RESET}")
if failed:
    print(f"  {RED}{failed} test(s) failed{RESET}")
    sys.exit(1)
else:
    print(f"  {GREEN}All tests passed{RESET}")
