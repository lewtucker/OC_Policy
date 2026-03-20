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

# Use wget (no existing rule) to test priority ordering cleanly
run("11. Add low-priority allow-wget (priority 5)",
    lambda: request("POST", "/policies", {
        "id": "allow-wget",
        "effect": "allow",
        "priority": 5,
        "match": {"tool": "exec", "program": "wget"},
    }),
    lambda r: r["id"] == "allow-wget")

run("12. wget → ALLOW at priority 5",
    lambda: check("exec", {"command": "wget https://example.com"}),
    lambda r: r["verdict"] == "allow")

run("13. Add high-priority deny-wget (priority 50)",
    lambda: request("POST", "/policies", {
        "id": "deny-wget",
        "description": "Block wget — use approved HTTP clients only",
        "effect": "deny",
        "priority": 50,
        "match": {"tool": "exec", "program": "wget"},
    }),
    lambda r: r["id"] == "deny-wget")

run("14. wget → DENY — high-priority deny beats low-priority allow",
    lambda: check("exec", {"command": "wget https://example.com"}),
    lambda r: r["verdict"] == "deny")

# ── Cleanup ───────────────────────────────────────────────────────────────────
print(f"\n{DIM}── Cleanup ──────────────────────────────────────────────────────{RESET}")

run("15. Remove allow-wget and deny-wget",
    lambda: (
        request("DELETE", "/policies/allow-wget"),
        request("DELETE", "/policies/deny-wget"),
    ),
    lambda r: True)

run("16. POST /policies/reload — rules reload from disk",
    lambda: request("POST", "/policies/reload"),
    lambda r: "reloaded" in r)

# ── Group 4: approvals queue ──────────────────────────────────────────────────
print(f"\n{DIM}── Approvals queue ─────────────────────────────────────────────{RESET}")

# curl has a pending rule in policies.yaml
_approval_id = None

def _trigger_pending():
    global _approval_id
    r = check("exec", {"command": "curl https://example.com"})
    _approval_id = r.get("approval_id")
    return r

run("17. curl → PENDING (requires approval)",
    _trigger_pending,
    lambda r: r["verdict"] == "pending" and r.get("approval_id") is not None)

run("18. GET /approvals lists the pending record",
    lambda: request("GET", "/approvals?pending_only=true"),
    lambda r: any(a["id"] == _approval_id for a in r.get("approvals", [])))

run("19. GET /approvals/{id} returns the record",
    lambda: request("GET", f"/approvals/{_approval_id}"),
    lambda r: r["id"] == _approval_id and r["verdict"] is None)

run("20. POST /approvals/{id} approves it",
    lambda: request("POST", f"/approvals/{_approval_id}", {
        "verdict": "allow",
        "reason": "Approved by test harness",
    }),
    lambda r: r["verdict"] == "allow" and r["resolved_at"] is not None)

run("21. GET /approvals/{id} after approval shows resolved",
    lambda: request("GET", f"/approvals/{_approval_id}"),
    lambda r: r["verdict"] == "allow")

# Test deny path with a second approval
_approval_id_2 = None

def _trigger_pending_2():
    global _approval_id_2
    r = check("exec", {"command": "curl https://evil.example.com"})
    _approval_id_2 = r.get("approval_id")
    return r

run("22. curl → PENDING (second request)",
    _trigger_pending_2,
    lambda r: r["verdict"] == "pending" and r.get("approval_id") is not None)

run("23. POST /approvals/{id} denies it",
    lambda: request("POST", f"/approvals/{_approval_id_2}", {
        "verdict": "deny",
        "reason": "Suspicious URL",
    }),
    lambda r: r["verdict"] == "deny" and r["reason"] == "Suspicious URL")

# Test 24 expects a 404 error — handled inline
print(f"\n  {BOLD}24. POST /approvals/{{id}} on already-resolved → 404{RESET}")
try:
    request("POST", f"/approvals/{_approval_id}", {"verdict": "deny"})
    print(f"    [{RED}FAIL{RESET}] expected 404, got success")
    failed += 1
except RuntimeError as e:
    if "404" in str(e):
        print(f"    result=404 as expected")
        print(f"    [{GREEN}PASS{RESET}]")
        passed += 1
    else:
        print(f"    [{RED}FAIL{RESET}] unexpected error: {e}")
        failed += 1

# ── Group 5: audit log ────────────────────────────────────────────────────────
print(f"\n{DIM}── Audit log ───────────────────────────────────────────────────{RESET}")

run("25. GET /audit returns entries",
    lambda: request("GET", "/audit"),
    lambda r: "entries" in r and len(r["entries"]) > 0)

run("26. Audit entries have required fields",
    lambda: request("GET", "/audit?limit=1"),
    lambda r: all(
        k in r["entries"][0]
        for k in ("id", "timestamp", "tool", "params", "verdict", "rule_id", "reason")
    ))

run("27. Audit log includes the pending/approval entries",
    lambda: request("GET", "/audit"),
    lambda r: any(e["verdict"] == "pending" for e in r["entries"]))

# ── Summary ───────────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{BOLD}=== Results: {passed}/{total} passed ==={RESET}")
if failed:
    print(f"  {RED}{failed} test(s) failed{RESET}")
    sys.exit(1)
else:
    print(f"  {GREEN}All tests passed{RESET}")
