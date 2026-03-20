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
| Web UI — all four live screens | ✅ |
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
  "phase": "2.5",
  "rules": 2,
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

## Step 3 — Run the Automated Test Suite

Open a second terminal and run the dummy OC harness. This sends 27 requests to the
server that simulate exactly what the OpenClaw plugin would send:

```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken python3 /Users/lewtucker/Documents/dev/OC_Policy/src/server/test_server.py
```

Expected output:

```
=== OC Policy Server — Phase 2 acceptance tests ===
    Server: http://localhost:8080

── Baseline rules ──────────────────────────────────────────────
  1. git exec → ALLOW (from YAML)        [PASS]
  2. ls exec → DENY (no matching rule)   [PASS]
  3. unknown tool → DENY                 [PASS]
  4. git with args → ALLOW               [PASS]
  5. empty command → DENY                [PASS]

── Policy CRUD ─────────────────────────────────────────────────
  6.  GET /policies lists rules           [PASS]
  7.  POST /policies adds allow-npm       [PASS]
  8.  npm exec → ALLOW after adding       [PASS]
  9.  DELETE /policies/allow-npm          [PASS]
  10. npm exec → DENY after removing      [PASS]

── Priority ────────────────────────────────────────────────────
  11. Add allow-wget (priority 5)         [PASS]
  12. wget → ALLOW                        [PASS]
  13. Add deny-wget (priority 50)         [PASS]
  14. wget → DENY (high-priority wins)    [PASS]
  15. Cleanup                             [PASS]
  16. Reload from disk                    [PASS]

── Approvals queue ─────────────────────────────────────────────
  17. curl → PENDING                      [PASS]
  18. GET /approvals shows record         [PASS]
  19. GET /approvals/{id}                 [PASS]
  20. Approve → allow                     [PASS]
  21. Record shows resolved               [PASS]
  22. curl → PENDING (second)             [PASS]
  23. Deny with reason                    [PASS]
  24. Re-resolve → 404                    [PASS]

── Audit log ───────────────────────────────────────────────────
  25. GET /audit returns entries          [PASS]
  26. Entries have required fields        [PASS]
  27. Includes pending entries            [PASS]

=== Results: 27/27 passed ===
```

While this runs, switch to the browser — the Dashboard activity feed updates within
10 seconds showing a mix of allow, deny, and pending entries.

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
2. Fill in: ID = `allow-npm`, Effect = `allow`, Tool = `exec`, Program = `npm`, Priority = `10`
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
  effect: deny
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
