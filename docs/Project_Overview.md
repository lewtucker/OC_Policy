# OC Policy — Project Overview

**Date**: 2026-03-21
**Author(s)**: Lew Tucker
**Status**: Active development — Phase 3b complete (identity-aware policies live)

---

## What We Are Building

Autonomous AI agents can take actions that have real consequences: deleting files, making network calls, running shell commands, pushing code. Most of the time those actions are exactly what you wanted. Sometimes they are not — and by the time you notice, the damage is done.

**OC Policy** is a policy enforcement system for AI agents. Its purpose is to give operators control over what an agent is allowed to do, in real time, without having to trust that the agent will stay within safe boundaries on its own. Every tool call an agent attempts passes through a policy gate before it executes. The gate can allow it, deny it outright, or hold it for a human to approve. This approach is inspired by the policy language made for the Zero-Trust Packet Routing system, an identity-aware network security layer (see [zpr.org](https://zpr.org)).

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
│  Receives Telegram message (chatJid) → spawns Docker         │
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
│       ├── POST /check  { tool, params, channel_id }          │
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
│  │  priority eval, │  │  (in-memory) │  │   persistent)  │  │
│  │  subject match) │  └──────────────┘  └────────────────┘  │
│  └─────────────────┘                                         │
│  ┌─────────────────┐                                         │
│  │ Identity Store  │  chatJid → Person → groups              │
│  │ (identities.yaml│                                         │
│  └─────────────────┘                                         │
│  policies.yaml — the source of truth for all rules           │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP (localhost:8080)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                     Policy UI (Web Browser)                  │
│                                                              │
│  Dashboard    — live stats, recent activity with subject     │
│  Approvals    — pending actions, Approve / Deny buttons      │
│  Policies     — rule table, add / edit / delete rules        │
│  Identities   — person cards with group memberships          │
└──────────────────────────────────────────────────────────────┘
```

### Layer 1 — The Enforcement Hook

The enforcement point lives inside the Docker container where the agent runs. It is a `PreToolUse` hook registered with the Claude Agent SDK. Before every tool call — whether initiated by the user or by the agent acting autonomously — the hook fires and POSTs the tool name, parameters, and the Telegram `channel_id` (chat JID) to the policy server. Execution is suspended until the server responds.

The hook is embedded in the Nanoclaw `agent-runner` source, which is compiled fresh inside each container on every start. If the policy server cannot be reached for any reason, the hook returns `block` — it never fails open.

### Layer 2 — The Policy Server

A Python FastAPI server that runs on the host, outside the container so the agent cannot reach it directly. It:

- Resolves the `channel_id` (Telegram chat JID) to a `Person` with group memberships via `identities.yaml`
- Evaluates tool calls against rules loaded from `policies.yaml`, matching on tool, program, path, person, and/or group
- Returns `allow`, `deny`, or `pending` verdicts
- Creates approval records for `pending` verdicts and waits for human resolution
- Records every check — including the resolved subject ID — to a persistent JSONL audit log
- Exposes a REST API for rule management, approval resolution, and identity lookup

Rule evaluation is priority-based: rules are sorted by `priority` (higher = evaluated first), and the first match wins. If no rule matches, the default is `deny`. Rules with `group` or `person` conditions only match when a subject is known — anonymous requests fall through to identity-agnostic rules.

### Layer 3 — The Policy UI

A single-page web app served by the policy server at `http://localhost:8080`. It shows live policy state, surfaces pending approval requests, lets operators add or edit rules (with person and group dropdowns populated from the identity store), and displays the people registry.

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
| Identity store — load from `identities.yaml` | ✅ |
| chatJid → Person resolution | ✅ |
| Group-based rule matching (`match.group`) | ✅ |
| Person-specific rule matching (`match.person`) | ✅ |
| Subject ID in audit log entries | ✅ |

### Enforcement Hook (`nanoclaw/container/agent-runner/`)

| Capability | Status |
| --- | --- |
| `PreToolUse` hook intercepts all tool calls | ✅ |
| POSTs tool name, params, and `channel_id` | ✅ |
| Handles allow / deny / pending verdicts | ✅ |
| Polls for approval resolution (500ms, 2min timeout) | ✅ |
| Fails closed if policy server is unreachable | ✅ |
| Token injected via container environment | ✅ |
| End-to-end approval flow verified live | ✅ |

### Web UI (`src/server/static/`)

| Screen | Status |
| --- | --- |
| Dashboard — stats, policy table, activity feed (with subject) | ✅ Live, auto-refreshes |
| Approvals — pending cards with Approve / Deny | ✅ Live, auto-refreshes |
| Policies — rule table, add / edit / delete; person & group dropdowns | ✅ Live CRUD |
| Identities — person cards with group pills | ✅ Live |
| Plugins | 🔲 Placeholder — Phase 4 |

---

## How It Works — The Approval Loop

A concrete example: the operator has set a rule requiring approval before any web search.

```text
1.  User (Lew, tg:123456789) sends Telegram: "Search for today's headlines"

2.  Nanoclaw spawns a container, passes chatJid = "tg:123456789"

3.  Agent decides to call WebSearch

4.  PreToolUse hook fires — BEFORE the search executes

5.  Hook POSTs to policy server:
      { "tool": "WebSearch", "params": { "query": "today's headlines" },
        "channel_id": "tg:123456789" }

6.  Server resolves chatJid → Person(id="lew", groups=["admin"])

7.  Policy engine evaluates rules in priority order — matches "ask-websearch":
      result: pending → creates approval record, returns:
      { "verdict": "pending", "approval_id": "abc-123" }

8.  Hook begins polling GET /approvals/abc-123 every 500ms
    Agent is suspended — nothing executes

9.  Approval card appears in the UI at http://localhost:8080

10. Operator clicks Approve

11. Next poll returns { "verdict": "allow" }

12. Hook returns {} to the SDK — tool call proceeds

13. Agent completes the search and replies to Telegram
```

If the operator clicks Deny, the hook returns `{ decision: "block", reason: "Denied by approver" }` and the agent is informed the action was not permitted.

---

## Policy Rules

Rules are stored in `src/server/policies.yaml`. Example active rules:

```yaml
# Person-specific rule — Lew's git commands require approval
- id: lew-can-git
  result: pending
  priority: 70
  match:
    program: git
    person: lew

# Group-based rules — admin can read employee data, engineering cannot
- id: admin-read-employees
  result: allow
  priority: 60
  match:
    group: admin
    path: /workspace/employees/*

- id: deny-eng-read-employees
  result: deny
  priority: 50
  match:
    group: engineering
    path: /workspace/employees/*

# Tool-level rules — approve web access
- id: ask-websearch
  result: pending
  priority: 20
  match:
    tool: WebSearch

# Catch-all
- id: allow-all
  result: allow
  priority: 0
  match: {}
```

Rules support five match conditions (all optional, all must match when present):

| Condition | Matches on |
| --- | --- |
| `tool` | Tool name (e.g. `WebSearch`, `Bash`) |
| `program` | First word of a shell command; `*` glob supported |
| `path` | File path; `*` and `**` glob supported |
| `person` | Person ID from `identities.yaml` |
| `group` | Group membership from `identities.yaml` |

---

## What Is Not Yet Built

| Item | Phase | Description |
| --- | --- | --- |
| Approval routing | 3c | Notify the requesting user via Telegram when their request is pending |
| Semantic request categories | 3c | Map `(tool, params)` → `read \| write \| search \| fetch` for higher-level rules |
| Named lists | 3c | Domain allowlists, path patterns reusable across rules |
| Rate limiting | 4 | Counter-based conditions (`max 10 searches per day`) |
| Resource ownership | 4 | Track file creators; enable owner-approval rules |
| Multi-person approval | 4 | Quorum requirements (two admins must approve) |
| Plugin trust registry | 5 | Admin allowlist of approved plugins |
| Signed subject tokens | 5 | Host-signed token so containers cannot forge their own identity |

---

## Design Documents

### [Trust_and_Security_Model_v02.md](Trust_and_Security_Model_v02.md)

The formal security model for the system. Starts from ten concrete policy examples and derives the abstractions needed to express them. Defines eight governing principles, six abstraction categories, the **OCPL** policy language, the evaluation algorithm, and an implementation roadmap.

### [Controlling_OpenClaw_Agents_v02.md](Controlling_OpenClaw_Agents_v02.md)

Identifies structural gaps in the prototype: no subject identity, the subject forgery problem, and plugin trust levels. Proposes a pragmatic build order from simplest safe improvement to hardest.

---

## Running the System

**Start the policy server:**

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

Open `http://localhost:8080` for the UI.

**Start Nanoclaw:**

```bash
cd ~/Documents/dev/nanoclaw && npm run dev
```

**Key files:**

| File | Purpose |
| --- | --- |
| `src/server/server.py` | FastAPI application — all endpoints |
| `src/server/policy_engine.py` | Rule parser and evaluator (subject-aware) |
| `src/server/policies.yaml` | Active rules (edit directly or via UI) |
| `src/server/identities.yaml` | People registry — IDs, Telegram IDs, groups |
| `src/server/identity.py` | Identity store — chatJid → Person lookup |
| `src/server/approvals.py` | Approval queue |
| `src/server/audit.py` | Persistent audit log |
| `src/server/static/index.html` | Web UI |
| `nanoclaw/container/agent-runner/src/index.ts` | PreToolUse enforcement hook |
