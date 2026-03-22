# Testing Without OpenClaw

This document explains how to run and test the full OC Policy system without a live
OpenClaw installation. Everything except the final step — actually blocking an OpenClaw
tool call — can be exercised this way.

---

## What You Can Test

| Capability | Testable without OC |
| --- | --- |
| Policy server starts and serves the UI | ✅ |
| Add, delete, and reload policy rules | ✅ |
| Tool call evaluation (allow / deny / pending) | ✅ via dummy OC |
| Human approval flow (approve / deny) | ✅ via UI or curl |
| Audit log | ✅ |
| Fail-closed behaviour (server offline) | ✅ |
| Web UI — all five live screens | ✅ |
| Actual blocking of an OpenClaw tool call | ❌ needs OC + plugin |

---

## Prerequisites

Python 3.11 or later. Install dependencies once:

```bash
cd /Users/lewtucker/Documents/dev/OC_Policy/src/server
pip3 install -r requirements.txt
```

---

## Step 1 — Start the Policy Server

Open a terminal and run:

```bash
cd /Users/lewtucker/Documents/dev/OC_Policy/src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

The `--reload` flag watches for file changes, so you can edit `policies.yaml` or
`server.py` and the server restarts automatically.

Verify it is up:

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

Expected response:

```json
{
  "status": "ok",
  "phase": "3b",
  "rules": 9,
  "identities": 3,
  "pending_approvals": 0,
  "audit_entries": 0
}
```

---

## Step 2 — Open the Web UI

Navigate to **http://localhost:8080** in a browser.

On first visit a dialog asks for the server URL and token:

- **Server URL**: `http://localhost:8080`
- **Agent Token**: `mysecrettoken`

After connecting, the Dashboard loads with live rule counts and an empty activity feed.

---

## Step 3 — Run the Pytest Suite (no running server needed)

The pytest suite is **self-contained** — it creates temporary policies, identities, and
audit files, sets env vars, and tests against an in-process FastAPI `TestClient`. No
running server required.

```bash
cd src/server
python -m pytest test_policy_suite.py -v
```

Expected output (59 tests across 8 categories):

```
test_policy_suite.py::TestAuth::test_health_no_auth PASSED
test_policy_suite.py::TestAuth::test_check_requires_agent_token PASSED
test_policy_suite.py::TestAuth::test_admin_token_grants_access PASSED
...
test_policy_suite.py::TestProtectedRules::test_cannot_delete_protected_rule PASSED
test_policy_suite.py::TestPolicyEvaluation::test_deny_rm_for_everyone PASSED
test_policy_suite.py::TestPolicyAnalyzer::test_shadow_detection PASSED
test_policy_suite.py::TestApprovalFlow::test_approve_flow PASSED
test_policy_suite.py::TestAuditTrail::test_audit_records_check PASSED
test_policy_suite.py::TestPolicyCRUD::test_add_rule PASSED
test_policy_suite.py::TestIdentities::test_list_identities PASSED
...
========================= 59 passed in 0.5s =========================
```

| Category | What it covers |
| --- | --- |
| Auth & Authorization (12) | Token validation, role checks, `/me` endpoint |
| Protected Rules (3) | Delete/update blocked, visible in list |
| Policy Evaluation (9) | Deny/allow/pending verdicts, priority ordering, anonymous identity |
| Policy Analyzer (6) | Shadow, conflict, orphan, uncovered group, unused rule detection |
| Approval Flow (9) | Approve/deny, double-resolve prevention, subject_id |
| Audit Trail (5) | Check logging, subject_id, approval_id, limit param |
| Policy CRUD (11) | Add/update/delete, duplicates, inline warnings, non-admin blocked |
| Identities (4) | List, groups, admin check, reload |

---

## Step 3b — Run the Legacy Test Harness (requires running server)

The original acceptance test script (`test_server.py`) sends 27 HTTP requests to a
**running** server. Start the server first (Step 1), then:

```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken python3 src/server/test_server.py
```

While this runs, switch to the browser — the Dashboard activity feed updates within
10 seconds showing a mix of allow, deny, and pending entries.

---

## Step 3c — Run the Rule Smoke Tests (requires running server)

`test_rules.sh` sends 17 `/check` calls covering all identities (Lew, Alice, Bob,
anonymous) and key actions, verifying expected verdicts:

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mytoken ./test_rules.sh
```

**Note**: use the **agent token** (the one passed to `OC_POLICY_AGENT_TOKEN` when starting
the server), not a personal API token.

---

## Step 4 — Test the Approvals Flow in the UI

The `curl` tool has a `pending` rule in `policies.yaml`. Trigger it manually:

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"curl https://example.com"}}' \
  | python3 -m json.tool
```

Response:

```json
{
  "verdict": "pending",
  "reason": "curl requires human approval before execution",
  "approval_id": "a64620f5-..."
}
```

Switch to the **Approvals** screen in the browser. Within 5 seconds the request appears
as a card. Click **Approve** or **Deny** — the card animates out and the badge clears.

---

## Step 5 — Test the Policies UI

Go to the **Policies** screen in the browser.

**Add a rule:**
1. Click **+ Add Rule**
2. Fill in: ID = `allow-npm`, Result = `allow`, Tool = `exec`, Program = `npm`, Priority = `10`
3. Click **Add Rule**
4. The table updates immediately

**Verify the rule works:**

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"npm install"}}' \
  | python3 -m json.tool
```

Expected: `"verdict": "allow"`

**Delete the rule:**
Click ✕ next to `allow-npm` in the table. Verify npm is denied again.

---

## Step 6 — Test Fail-Closed Behaviour

Stop the server (Ctrl-C in Terminal 1). Then check that the plugin would block:

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"git status"}}' 2>&1
```

Expected: connection refused. The TypeScript plugin catches this and returns
`block: true` with reason `"OC Policy Server unreachable — failing closed"`.
OpenClaw would never execute the tool.

The browser UI also shows the server as unreachable (red dot in the sidebar).

Restart the server and the UI reconnects automatically on the next poll.

---

## Step 7 — Edit Policies on Disk

With the server running, open `src/server/policies.yaml` in an editor and add a rule:

```yaml
- id: deny-rm
  description: Block rm — destructive
  result: deny
  priority: 100
  match:
    tool: exec
    program: rm
```

Save the file, then trigger a reload:

```bash
curl -s -X POST http://localhost:8080/policies/reload \
  -H "Authorization: Bearer mysecrettoken" \
  | python3 -m json.tool
```

Expected: `{"reloaded": 3}`. The new rule is now active without restarting the server.

---

## What Connecting OpenClaw Adds

When the TypeScript plugin is installed into OpenClaw, it registers a `before_tool_call`
hook that calls this same server before every tool execution. The policy server does not
change — it simply starts receiving real tool calls from OpenClaw instead of simulated
ones from the test harness or curl.

The only steps needed to go from this test setup to a live setup are:

1. Install the plugin into OpenClaw (see `plans/Plan_Phase1_EnforcementPlugin_v01.md`, Step 3)
2. Set `OC_POLICY_AGENT_TOKEN` in OpenClaw's environment to match the server's token
3. Start the server before starting OpenClaw

From that point on, every tool OpenClaw attempts is evaluated here first.
