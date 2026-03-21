# OC Policy — Project Overview

**Date**: 2026-03-21
**Author(s)**: Lew Tucker
**Status**: Active development — Phase 3 live integration complete

---

## What We Are Building

Autonomous AI agents can take actions that have real consequences: deleting files, making network calls, running shell commands, pushing code. Most of the time those actions are exactly what you wanted. Sometimes they are not — and by the time you notice, the damage is done.

**OC Policy** is a policy enforcement system for AI agents. Its purpose is to give operators control over what an agent is allowed to do, in real time, without having to trust that the agent will stay within safe boundaries on its own. Every tool call an agent attempts passes through a policy gate before it executes. The gate can allow it, deny it outright, or hold it for a human to approve.

The system is designed around three ideas:

1. **Intercept before execution** — the enforcement point is a hook that fires before every tool call, not after. A blocked action never runs.
2. **Human-in-the-loop** — for actions that require judgment, execution is suspended until a human approves or denies. The agent waits.
3. **Policy as the source of truth** — what is allowed and what is not is written in an explicit, readable policy file. There are no implicit permissions.

---

## System Architecture

The system has three layers that work together.

```text
┌──────────────────────────────────────────────────────────────┐
│                    Nanoclaw Host Process                      │
│  (Node.js orchestrator — runs as a launchd service)          │
│                                                              │
│  Receives Telegram message → spawns Docker container         │
│  Injects OC_POLICY_AGENT_TOKEN into container environment    │
└──────────────────────────────┬───────────────────────────────┘
                               │ docker run
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    Agent Container (Docker)                   │
│                                                              │
│  Claude Agent SDK — query()                                  │
│  │                                                           │
│  └─ PreToolUse hook fires before EVERY tool call             │
│       │                                                      │
│       ├── POST /check  { tool, params }                      │
│       │      ↓                                               │
│       │   verdict: allow  → tool executes                    │
│       │   verdict: deny   → tool blocked, reason returned    │
│       │   verdict: pending → hook polls /approvals/{id}      │
│       │                      every 500ms until resolved      │
│       │                      or 2-minute timeout (deny)      │
│       │                                                      │
│       └── Fails closed: if server unreachable → block        │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP (host.docker.internal:8080)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│               OC Policy Server (Python / FastAPI)            │
│                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Policy Engine  │  │  Approvals   │  │   Audit Log    │  │
│  │  (YAML rules,   │  │  Queue       │  │   (JSONL,      │  │
│  │  priority eval) │  │  (in-memory) │  │   persistent)  │  │
│  └─────────────────┘  └──────────────┘  └────────────────┘  │
│                                                              │
│  policies.yaml — the source of truth for all rules          │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP (localhost:8080)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                     Policy UI (Web Browser)                  │
│                                                              │
│  Dashboard    — live stats, recent activity                  │
│  Approvals    — pending actions, Approve / Deny buttons      │
│  Policies     — rule table, add / delete rules               │
└──────────────────────────────────────────────────────────────┘
```

### Layer 1 — The Enforcement Hook

The enforcement point lives inside the Docker container where the agent runs. It is a `PreToolUse` hook registered with the Claude Agent SDK. Before every tool call — whether initiated by the user or by the agent acting autonomously — the hook fires and POSTs the tool name and parameters to the policy server. Execution is suspended until the server responds.

The hook is embedded in the Nanoclaw `agent-runner` source, which is compiled fresh inside each container on every start. If the policy server cannot be reached for any reason, the hook returns `block` — it never fails open.

### Layer 2 — The Policy Server

A Python FastAPI server that runs on the host, outside the container the agent cannot reach it. It:

- Evaluates tool calls against rules loaded from `policies.yaml`
- Returns `allow`, `deny`, or `pending` verdicts
- Creates approval records for `pending` verdicts and waits for human resolution
- Records every check to a persistent JSONL audit log
- Exposes a REST API for rule management and approval resolution

Rule evaluation is priority-based: rules are sorted by `priority` (higher = evaluated first), and the first match wins. If no rule matches, the default is `deny`.

### Layer 3 — The Policy UI

A single-page web app served by the policy server at `http://localhost:8080`. It shows live policy state, surfaces pending approval requests, and lets operators add or remove rules without touching the YAML file directly.

---

## What Has Been Implemented

### Policy Server (`src/server/`)

| Capability | Status |
| --- | --- |
| Rule evaluation — allow / deny / pending | ✅ |
| YAML policy file — load, parse, priority sort | ✅ |
| Hot reload from disk (`POST /policies/reload`) | ✅ |
| REST CRUD for rules | ✅ |
| Approvals queue — create, poll, resolve | ✅ |
| Audit log — every check recorded to JSONL file | ✅ |
| Bearer token auth on all endpoints | ✅ |

### Enforcement Hook (`nanoclaw/container/agent-runner/`)

| Capability | Status |
| --- | --- |
| `PreToolUse` hook intercepts all tool calls | ✅ |
| POSTs to policy server with tool name + params | ✅ |
| Handles allow / deny / pending verdicts | ✅ |
| Polls for approval resolution (500ms interval, 2min timeout) | ✅ |
| Fails closed if policy server is unreachable | ✅ |
| Token injected via container environment | ✅ |
| End-to-end approval flow verified live | ✅ |

### Web UI (`src/server/static/`)

| Screen | Status |
| --- | --- |
| Dashboard — stats, policy table, activity feed | ✅ Live, auto-refreshes |
| Approvals — pending cards with Approve / Deny | ✅ Live, auto-refreshes |
| Policies — rule table, add rule, delete | ✅ Live CRUD |
| Identities | 🔲 Placeholder — Phase 3+ |
| Plugins | 🔲 Placeholder — Phase 4 |

---

## How It Works — The Approval Loop

A concrete example: the operator has set a rule requiring approval before any web search.

```text
1.  User sends Telegram message: "Search for today's headlines"

2.  Nanoclaw spawns a container, agent starts

3.  Agent decides to call WebSearch

4.  PreToolUse hook fires — BEFORE the search executes

5.  Hook POSTs to policy server:
      { "tool": "WebSearch", "params": { "query": "today's headlines" } }

6.  Policy server matches rule "ask-websearch":
      result: pending → creates approval record, returns:
      { "verdict": "pending", "approval_id": "abc-123" }

7.  Hook begins polling GET /approvals/abc-123 every 500ms
    Agent is suspended — nothing executes

8.  Approval card appears in the UI at http://localhost:8080

9.  Operator clicks Approve

10. Next poll returns { "verdict": "allow" }

11. Hook returns {} to the SDK — tool call proceeds

12. Agent completes the search and replies to Telegram
```

If the operator clicks Deny, the hook returns `{ decision: "block", reason: "Denied by approver" }` and the agent is informed the action was not permitted.

---

## Policy Rules

Rules are stored in `src/server/policies.yaml`. The current active rules:

```yaml
- id: ask-websearch
  description: Require approval before any web search
  result: pending
  priority: 20
  match:
    tool: WebSearch

- id: ask-webfetch
  description: Require approval before fetching any URL
  result: pending
  priority: 20
  match:
    tool: WebFetch

- id: allow-all
  description: Allow everything not matched above
  result: allow
  priority: 0
  match: {}
```

Rules can be added, modified, and deleted via the UI or directly in the YAML file (with `POST /policies/reload` to pick up changes).

---

## What Is Not Yet Built

| Item | Phase | Description |
| --- | --- | --- |
| Subject identity | 3a | Rules currently treat all tool calls identically. The `subject` field (who is acting — human session, subagent, scheduled task) is not yet wired through. |
| Role-based rules | 3b | Person registry mapping Telegram IDs to roles; rules that match on role |
| Approval routing | 3b | Notify the requesting user via Telegram when their request is pending |
| Semantic request categories | 3c | Map tool names to categories (`read`, `write`, `search`, `fetch`, etc.) for higher-level rules |
| Named lists | 3c | Domain allowlists, path patterns reusable across rules |
| Persistent approvals | — | Approval queue is in-memory; lost on server restart |
| Rate limiting | 4 | Counter-based conditions (`max 10 searches per day`) |
| Resource ownership | 4 | Track file creators; enable owner-approval rules |
| Multi-person approval | 4 | Quorum requirements (two admins must approve) |
| UI wired to backend | — | Static mockup at [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app) not yet connected |
| Plugin trust registry | 5 | Admin allowlist of approved plugins |
| Signed subject tokens | 5 | Cryptographic proof of actor identity from the host |

---

## Design Documents

### [Trust_and_Security_Model_v02.md](Trust_and_Security_Model_v02.md)

The formal security model for the system. Starts from ten concrete policy examples and derives the abstractions needed to express them. Defines:

- Eight governing principles (Default Deny, Least Privilege, No Upward Inheritance, and others)
- Six abstraction categories: Subjects, Requests, Resources, Conditions, Named Entities, Trust Levels
- **OCPL** (OC Policy Language) — a declarative rule language with `entities`, `rules`, and `defaults` blocks, with all ten examples written in full
- The evaluation algorithm the policy server implements
- An implementation roadmap ordered by cost and value
- An honest account of what this model cannot solve: the identity root problem, emergent behavior, policy correctness, and approval fatigue

### [Identity_and_Plugin_Trust_v01.md](Identity_and_Plugin_Trust_v01.md)

A discussion document that identifies the structural gaps in the current prototype and proposes solutions. Key issues covered:

- **No subject identity** — every tool call looks the same to the policy server; there is no distinction between a human request and an autonomous subagent decision
- **Two dimensions of identity** — autonomous vs. human-initiated actors (single user) and multi-user team identity (multiple people sharing one agent instance)
- **The subject forgery problem** — the hook runs inside the container the agent controls; a compromised agent could forge its own identity; host-signed tokens are the correct fix
- **Plugin trust** — installation-time control (who can add a plugin) and runtime control (what a plugin is allowed to do once installed); four levels from `verified` to `blocked`
- A pragmatic build order from the simplest safe improvement (subject types, Phase 3a) to the hardest (cryptographic signing, Phase 5)

---

## Running the System

**Start the policy server:**

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

Open `http://localhost:8080` for the UI.

**Nanoclaw** must also be running with `OC_POLICY_AGENT_TOKEN` set in its environment (configured in `~/Library/LaunchAgents/com.nanoclaw.plist`). Any tool call Nanoclaw's agent attempts will then pass through the policy gate.

**Key files:**

| File | Purpose |
| --- | --- |
| `src/server/server.py` | FastAPI application — all endpoints |
| `src/server/policy_engine.py` | Rule parser and evaluator |
| `src/server/policies.yaml` | Active rules (edit directly or via UI) |
| `src/server/approvals.py` | Approval queue |
| `src/server/audit.py` | Persistent audit log |
| `src/server/static/index.html` | Web UI |
| `nanoclaw/container/agent-runner/src/index.ts` | PreToolUse enforcement hook |
