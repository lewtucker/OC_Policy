# OC Policy — Progress Report

**Version**: v02
**Date**: 2026-03-19
**Status**: Phases 1, 2, and 2.5 complete

---

## Summary

Three phases of the OC Policy enforcement system are built, tested, and pushed to GitHub. The full enforcement loop is working end-to-end: intercept a tool call, evaluate it against a YAML policy file, allow / deny / hold for human approval. Every check is audited. Testing uses a dummy OC harness — no live OpenClaw installation required.

---

## What Was Built

### Phase 1 — Enforcement Plugin + Minimal Policy Server

**Goal**: Prove that a tool call can be intercepted and blocked before it executes.

| File | Description |
| --- | --- |
| `src/plugin/src/index.ts` | TypeScript OpenClaw plugin — registers `before_tool_call` hook, POSTs to policy server, polls for approvals, fails closed if server unreachable |
| `src/plugin/package.json` | Plugin manifest with `"openclaw"` extension entry point |
| `src/plugin/tsconfig.json` | TypeScript compiler config |
| `src/server/server.py` | FastAPI policy server |
| `src/server/requirements.txt` | Python dependencies |
| `src/server/test_server.py` | Dummy OC test harness |

**Key design decisions**:

- Fail closed — if the policy server is unreachable, the plugin returns `block: true`. OpenClaw never executes the tool.
- Bearer token auth — plugin and server share `OC_POLICY_AGENT_TOKEN` via environment variable. No tokens in committed files.
- Approval polling — plugin polls `/approvals/{id}` every 2 seconds up to 120 seconds for `pending` verdicts, enabling human-in-the-loop approval flows.

---

### Phase 2 — Policy Engine with YAML Rules and CRUD API

**Goal**: Replace the hardcoded allowlist with a real policy engine backed by a YAML file, with live rule management via REST endpoints.

| File | Description |
| --- | --- |
| `src/server/policy_engine.py` | Rule parser and evaluator — loads YAML, matches rules, first-match-wins by priority |
| `src/server/policies.yaml` | Default policy file — ships with `allow-git` and `require-approval-for-curl` rules |
| `src/server/server.py` | Updated server — delegates to engine, adds CRUD endpoints |

**Policy schema**:

```yaml
version: 1
policies:
  - id: allow-git
    description: Allow git commands in any directory
    effect: allow          # allow | deny | pending
    priority: 10           # higher = evaluated first; first match wins
    match:
      tool: exec           # tool name
      program: git         # first word of exec command; supports * glob
```

**Endpoints**:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/policies` | List all rules |
| `POST` | `/policies` | Add a rule (persisted to YAML) |
| `DELETE` | `/policies/{id}` | Remove a rule (persisted to YAML) |
| `POST` | `/policies/reload` | Reload rules from disk |

---

### Phase 2.5 — Approvals Queue and Audit Log

**Goal**: Complete the human-in-the-loop flow and make every check observable.

| File | Description |
| --- | --- |
| `src/server/approvals.py` | In-memory approval store — create, get, resolve records |
| `src/server/audit.py` | Append-only audit log — every check recorded with timestamp, verdict, rule ID |
| `src/server/server.py` | Updated — wires approvals and audit into `/check`; adds approval and audit endpoints |

**Approvals flow**:

```
Plugin          Policy Server              Human
  |                   |                     |
  |-- POST /check --> |                     |
  |              effect=pending             |
  |              create ApprovalRecord      |
  |<-- {verdict:"pending",                  |
  |     approvalId:"abc"} --|               |
  |                         |<- GET /approvals
  |-- GET /approvals/abc -> |               |
  |   (polls every 2s)      |<- POST /approvals/abc
  |                         |   {verdict:"allow"}
  |<-- {verdict:"allow"} ---|               |
  | (unblocks, tool runs)   |               |
```

**New endpoints**:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/approvals` | List all approvals (pass `?pending_only=true` to filter) |
| `GET` | `/approvals/{id}` | Get one approval record |
| `POST` | `/approvals/{id}` | Resolve: `{"verdict":"allow"\|"deny","reason":"..."}` |
| `GET` | `/audit` | Recent check log (pass `?limit=N`, default 100) |

---

## Test Results

All tests run using the dummy OC harness (`src/server/test_server.py`) against a live local server. No OpenClaw installation required.

### Phase 1 — 5/5 passed

| # | Test | Result |
| --- | --- | --- |
| 1 | `git status` → allow | **PASS** |
| 2 | `ls -la /tmp` → deny | **PASS** |
| 3 | `read_file /etc/passwd` (unknown tool) → deny | **PASS** |
| 4 | `git log --oneline -5` → allow | **PASS** |
| 5 | Empty command → deny | **PASS** |

Fail-closed verified manually: server stopped → plugin returns `block: true`, reason: "OC Policy Server unreachable — failing closed".

### Phase 2 — 16/16 passed

**Baseline**

| # | Test | Result |
| --- | --- | --- |
| 1 | `git status` → allow (from YAML) | **PASS** — reason: "Allow git commands in any directory" |
| 2 | `ls -la /tmp` → deny (no rule) | **PASS** — reason: "No policy permits this action" |
| 3 | `read_file /etc/passwd` → deny | **PASS** |
| 4 | `git log --oneline -5` → allow | **PASS** |
| 5 | Empty command → deny | **PASS** |

**CRUD lifecycle**

| # | Test | Result |
| --- | --- | --- |
| 6 | `GET /policies` returns rules | **PASS** |
| 7 | `POST /policies` adds `allow-npm` | **PASS** |
| 8 | `npm install` after adding rule → allow | **PASS** |
| 9 | `DELETE /policies/allow-npm` → 204 | **PASS** |
| 10 | `npm install` after deleting rule → deny | **PASS** |

**Priority ordering**

| # | Test | Result |
| --- | --- | --- |
| 11 | Add `allow-wget` at priority 5 | **PASS** |
| 12 | `wget https://example.com` → allow | **PASS** |
| 13 | Add `deny-wget` at priority 50 | **PASS** |
| 14 | `wget https://example.com` → deny (high-priority deny wins) | **PASS** |
| 15 | Delete both rules | **PASS** |
| 16 | `POST /policies/reload` → `{"reloaded": 2}` | **PASS** |

### Phase 2.5 — 11/11 passed

**Approvals queue**

| # | Test | Result |
| --- | --- | --- |
| 17 | `curl https://example.com` → pending + approvalId | **PASS** |
| 18 | `GET /approvals?pending_only=true` shows the record | **PASS** |
| 19 | `GET /approvals/{id}` returns record with `verdict: null` | **PASS** |
| 20 | `POST /approvals/{id}` `{"verdict":"allow"}` resolves it | **PASS** |
| 21 | `GET /approvals/{id}` after approval shows `verdict: "allow"` | **PASS** |
| 22 | Second curl → pending (new record) | **PASS** |
| 23 | `POST /approvals/{id}` `{"verdict":"deny","reason":"Suspicious URL"}` | **PASS** |
| 24 | `POST /approvals/{id}` on already-resolved → 404 | **PASS** |

**Audit log**

| # | Test | Result |
| --- | --- | --- |
| 25 | `GET /audit` returns entries | **PASS** |
| 26 | Audit entries have all required fields (`id`, `timestamp`, `tool`, `params`, `verdict`, `rule_id`, `reason`) | **PASS** |
| 27 | Audit includes `pending` entries with `approval_id` | **PASS** |

**Total: 27/27 tests passed across all three phases.**

---

## Current Server API

```
POST   /check                    Tool call evaluation (plugin)
GET    /policies                 List rules
POST   /policies                 Add rule
DELETE /policies/{id}            Remove rule
POST   /policies/reload          Reload from disk
GET    /approvals                List approvals (?pending_only=true)
GET    /approvals/{id}           Get approval record
POST   /approvals/{id}           Resolve approval (allow/deny)
GET    /audit                    Check log (?limit=N)
GET    /health                   Server status
```

---

## What Is Not Yet Built

| Item | Phase | Notes |
| --- | --- | --- |
| Install plugin into live OpenClaw | 1 | Blocked on local OpenClaw setup |
| Web UI wired to server | 3 | Static mockup live at [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app); needs backend connection |
| Identity / trusted sources | 3 | Attribute-based policy matching (user groups, departments) |
| Plugin capability declarations | 4 | Install-time consent flow; auto-generated policy entries |
| Credential injection | 4 | Per-plugin encrypted credentials injected at runtime |
| Tamper prevention | 4 | Separate OS user, split admin port, signed policies, persistent audit log |

---

## Running the System Locally

**Requirements**: Python ≥ 3.11

```bash
pip3 install -r src/server/requirements.txt
```

**Start the server:**
```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

**Run all tests:**
```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken python3 /Users/lewtucker/Documents/dev/OC_Policy/src/server/test_server.py
```

**Manually approve a pending curl request:**
```bash
# Trigger a pending verdict
curl -s -X POST http://localhost:8080/check \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"tool":"exec","params":{"command":"curl https://example.com"}}'

# List pending approvals
curl -s http://localhost:8080/approvals?pending_only=true \
  -H "Authorization: Bearer mysecrettoken"

# Approve it (replace <id> with the approvalId from above)
curl -s -X POST http://localhost:8080/approvals/<id> \
  -H "Authorization: Bearer mysecrettoken" \
  -H "Content-Type: application/json" \
  -d '{"verdict":"allow","reason":"Looks safe"}'
```
