# OC Policy — Progress Report

**Version**: v01
**Date**: 2026-03-19
**Status**: Phase 1 and Phase 2 complete

---

## Summary

Two phases of the OC Policy enforcement system are built, tested, and pushed to GitHub. The core enforcement loop — intercept a tool call, evaluate it against a policy rule, allow or block — is working end-to-end. Testing was done without a live OpenClaw instance using a dummy test harness that sends HTTP requests directly to the policy server, simulating exactly what the plugin would do.

---

## What Was Built

### Phase 1 — Enforcement Plugin + Minimal Policy Server

**Goal**: Prove that a tool call can be intercepted and blocked before it executes.

| File | Description |
| --- | --- |
| `src/plugin/src/index.ts` | TypeScript OpenClaw plugin — registers `before_tool_call` hook, POSTs to policy server, polls for approvals, fails closed if server is unreachable |
| `src/plugin/package.json` | Plugin manifest with `"openclaw"` extension entry point |
| `src/plugin/tsconfig.json` | TypeScript compiler config |
| `src/server/server.py` | FastAPI policy server (Phase 1 — hardcoded `git` allowlist) |
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
| `src/server/policies.yaml` | Default policy file — ships with `allow-git` rule |
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

**New endpoints**:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/policies` | List all rules |
| `POST` | `/policies` | Add a rule (persisted to YAML) |
| `DELETE` | `/policies/{id}` | Remove a rule (persisted to YAML) |
| `POST` | `/policies/reload` | Reload rules from disk |

---

## Test Results

All tests were run using the dummy OC harness (`src/server/test_server.py`) against a live local server instance. No OpenClaw installation required.

### Phase 1 Tests — 5/5 passed

| # | Test | Expected | Result |
| --- | --- | --- | --- |
| 1 | `git status` | allow | **PASS** |
| 2 | `ls -la /tmp` | deny | **PASS** |
| 3 | `read_file /etc/passwd` (unknown tool) | deny | **PASS** |
| 4 | `git log --oneline -5` | allow | **PASS** |
| 5 | Empty command | deny | **PASS** |

Fail-closed behavior also verified manually: with the server stopped, the plugin returns `block: true` with reason "OC Policy Server unreachable — failing closed".

### Phase 2 Tests — 16/16 passed

**Baseline rules (loaded from `policies.yaml`)**

| # | Test | Expected | Result |
| --- | --- | --- | --- |
| 1 | `git status` — ALLOW from YAML | allow | **PASS** — reason: "Allow git commands in any directory" |
| 2 | `ls -la /tmp` — no matching rule | deny | **PASS** — reason: "No policy permits this action" |
| 3 | `read_file /etc/passwd` — unknown tool | deny | **PASS** |
| 4 | `git log --oneline -5` | allow | **PASS** |
| 5 | Empty command | deny | **PASS** |

**Policy CRUD lifecycle**

| # | Test | Expected | Result |
| --- | --- | --- | --- |
| 6 | `GET /policies` returns rules | policies list | **PASS** |
| 7 | `POST /policies` adds `allow-npm` | rule created | **PASS** |
| 8 | `npm install` after adding rule | allow | **PASS** |
| 9 | `DELETE /policies/allow-npm` | 204 | **PASS** |
| 10 | `npm install` after deleting rule | deny | **PASS** |

**Priority ordering**

| # | Test | Expected | Result |
| --- | --- | --- | --- |
| 11 | Add `allow-curl` at priority 5 | rule created | **PASS** |
| 12 | `curl https://example.com` | allow | **PASS** — matched at priority 5 |
| 13 | Add `deny-curl` at priority 50 | rule created | **PASS** |
| 14 | `curl https://example.com` — high-priority deny beats low-priority allow | deny | **PASS** — reason: "Block curl — use approved HTTP clients only" |

**Cleanup and reload**

| # | Test | Expected | Result |
| --- | --- | --- | --- |
| 15 | Delete `allow-curl` and `deny-curl` | 204 | **PASS** |
| 16 | `POST /policies/reload` — reload from disk | `{"reloaded": 1}` | **PASS** |

**Total: 21/21 tests passed across both phases.**

---

## What Is Not Yet Built

The following items are designed in [docs/OC_Policy_Control_v01.md](OC_Policy_Control_v01.md) but not yet implemented:

| Item | Phase | Notes |
| --- | --- | --- |
| Install plugin into live OpenClaw | 1 | Blocked on local OpenClaw setup |
| Approvals queue — `pending` verdict flow | 2.5 | Plugin polling code is ready; server endpoint not yet built |
| Audit log | 2.5 | Every check should be logged with timestamp, verdict, rule ID |
| Web UI wired to server | 3 | Static mockup is live at [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app); needs backend connection |
| Identity / trusted sources | 3 | Attribute-based policy matching (user groups, departments) |
| Plugin capability declarations | 4 | Install-time consent flow; auto-generated policy entries |
| Credential injection | 4 | Per-plugin encrypted credentials injected at runtime |
| Tamper prevention | 4 | Separate OS user, split admin port, signed policies, append-only audit log |

---

## Running the System Locally

**Requirements**: Python ≥ 3.11, `pip install -r src/server/requirements.txt`

**Start the server:**
```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

**Run the tests:**
```bash
OC_POLICY_AGENT_TOKEN=mysecrettoken python3 /Users/lewtucker/Documents/dev/OC_Policy/src/server/test_server.py
```

**Manually add a rule:**
```bash
curl -s -X POST http://localhost:8080/policies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mysecrettoken" \
  -d '{"id":"allow-npm","description":"Allow npm","effect":"allow","priority":10,"match":{"tool":"exec","program":"npm"}}' \
  | python3 -m json.tool
```
