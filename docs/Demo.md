# OC Policy — Demo

A self-contained walkthrough you can run in about five minutes. No OpenClaw required.

---

## Prerequisites

Python 3.11 or later. Install dependencies once:

```bash
pip3 install -r /Users/lewtucker/Documents/dev/OC_Policy/src/server/requirements.txt
```

---

## 1. Start the Server

Open a terminal and run:

```bash
cd /Users/lewtucker/Documents/dev/OC_Policy/src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken ./start.sh
```

You should see:

```
  Starting OC Policy Server on http://localhost:8080
  Open http://localhost:8080 in your browser to access the UI.
  Press Ctrl-C to stop.

INFO:     Uvicorn running on http://0.0.0.0:8080
INFO:     Application startup complete.
```

Leave this terminal running for the rest of the demo.

---

## 2. Open the Web UI

Navigate to **http://localhost:8080** in a browser.

A connection dialog appears. Enter:

- **Server URL**: `http://localhost:8080`
- **Token**: `mysecrettoken`

Click **Connect**. The Dashboard loads showing 2 active rules and an empty activity feed.

> If the dialog does not appear and the sidebar shows "● Unreachable", click that text
> to open the connection dialog.

---

## 3. Run the Automated Tests

Open a **second terminal** and run:

```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken python3 /Users/lewtucker/Documents/dev/OC_Policy/src/server/test_server.py
```

This sends 27 requests to the server — the same calls the OpenClaw plugin would make.
Watch the Dashboard **Recent Activity** feed update live as tests run. You should see
a mix of `allow`, `deny`, and `pending` entries appear.

Expected result: `27/27 passed`

---

## 4. Approve a Pending Request

The `curl` tool has a `pending` rule — it requires human approval. Trigger one manually
in a terminal:

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"curl https://example.com"}}' \
  | python3 -m json.tool
```

You will see:

```json
{
  "verdict": "pending",
  "reason": "curl requires human approval before execution",
  "approval_id": "..."
}
```

Switch to the browser and click **Approvals** in the sidebar. Within 5 seconds the
request appears as a card. Click **Approve** — the card animates out and the badge clears.

---

## 5. Add a Policy Rule

Click **Policies** in the sidebar, then **+ Add Rule**. Fill in:

| Field | Value |
| --- | --- |
| Rule ID | `allow-npm` |
| Description | `Allow npm commands` |
| Effect | `allow` |
| Priority | `10` |
| Tool | `exec` |
| Program | `npm` |

Click **Add Rule**. The table updates immediately.

Verify the rule works:

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"npm install"}}' \
  | python3 -m json.tool
```

Expected: `"verdict": "allow"`

Delete the rule by clicking **✕** next to `allow-npm`. Run the same curl again —
it returns `"verdict": "deny"`.

---

## 6. Verify Fail-Closed Behaviour

Stop the server with **Ctrl-C** in Terminal 1.

Try a check:

```bash
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"git status"}}' 2>&1
```

Expected: connection refused. The OpenClaw plugin catches this and returns
`block: true` — no tool executes while the server is offline.

The browser sidebar switches to **● Unreachable**.

Restart the server:

```bash
cd /Users/lewtucker/Documents/dev/OC_Policy/src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken ./start.sh
```

The UI reconnects automatically within 10 seconds — no page refresh needed.
