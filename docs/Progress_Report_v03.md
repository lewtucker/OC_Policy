# OC Policy — Progress Report

**Version**: v03
**Date**: 2026-03-21
**Author(s)**: Lew Tucker
**Status**: Phase 3 live integration complete; identity model design in progress

---

## Summary

The enforcement loop is now connected to a live agentic system. Tool calls made inside Nanoclaw containers are intercepted by the OC Policy hook before execution, evaluated against the policy server, and held for human approval when policy requires it. The full cycle — intercept → evaluate → approve → execute — has been proven end-to-end with a real Telegram conversation. Design work on the identity and trust model is underway, documented in two new specification documents.

---

## What Was Built in This Phase

### Phase 3 — Live Integration with Nanoclaw

**Goal**: Connect the policy enforcement hook to a real running agent system and prove the approval loop works with a live user interaction.

**Nanoclaw architecture** (relevant to this work):

- Node.js orchestrator running as a launchd service on the host
- Spawns a Docker container per Telegram message
- Each container runs the Claude Agent SDK via `query()`, recompiling TypeScript from source on each start
- The `PreToolUse` hook in the Agent SDK fires before every tool call inside the container

**Files modified**:

| File | Change |
| --- | --- |
| `~/dev/nanoclaw/container/agent-runner/src/index.ts` | Added `PreToolUse` hook — POSTs to policy server, polls for approvals, fails closed |
| `~/dev/nanoclaw/src/container-runner.ts` | Injects `OC_POLICY_AGENT_TOKEN` env var into container `docker run` args |
| `~/Library/LaunchAgents/com.nanoclaw.plist` | Added `OC_POLICY_AGENT_TOKEN` to launchd environment; reloaded service |
| `src/server/policies.yaml` | Replaced old `exec`-based rules with `WebSearch` and `WebFetch` pending rules |
| `src/server/audit.py` | Rewrote to persist audit entries to a JSONL file — survives server restarts |
| `src/server/server.py` | Wired `AUDIT_FILE` path into `AuditLog` constructor |

**Hook implementation** (in `agent-runner/src/index.ts`):

```typescript
// On every tool call, before execution:
POST /check  { tool: "WebSearch", params: { query: "..." } }

// Server responds with one of:
{ verdict: "allow" }                          // → proceed
{ verdict: "deny", reason: "..." }            // → block with reason
{ verdict: "pending", approval_id: "abc" }   // → poll for resolution
```

The hook polls `/approvals/{id}` every 500 ms for up to 2 minutes. If the server is unreachable for any reason, the hook fails closed — the tool call is blocked.

**Active policies**:

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
  description: Allow everything not matched by a higher-priority rule
  result: allow
  priority: 0
  match: {}
```

**End-to-end approval flow proven**:

1. User asks Nanoclaw (via Telegram) to search for today's news headlines
2. Nanoclaw attempts `WebSearch` → `PreToolUse` hook fires
3. Hook POSTs to policy server → `pending` verdict + `approval_id`
4. Hook begins polling `/approvals/{id}` every 500 ms
5. Approval card appears in the OC Policy UI
6. User clicks Approve
7. Next poll returns `{ verdict: "allow" }` → tool executes
8. Nanoclaw returns search results to Telegram

**Issues resolved during integration**:

| Issue | Fix |
| --- | --- |
| TypeScript compile error: `_toolUseId: string` not assignable to `HookCallback` | Changed signature to `_toolUseId?: string` (SDK type is `string \| undefined`) |
| Token not reaching containers | `container-runner.ts` changes require `npm run build`; rebuilt nanoclaw |
| launchd restarting service without new token | Added token to plist `EnvironmentVariables`; reloaded with `launchctl unload/load` |
| Stale policy rules cached in running server | Called `POST /policies/reload` to pick up updated `policies.yaml` |
| Running containers using old compiled hook | Stopped all containers with `docker stop` before testing |

---

### Phase 3 — Persistent Audit Log

The audit log previously lived only in memory and was lost on server restart. `audit.py` was rewritten to:

- Load existing entries from a JSONL file on startup
- Append each new entry to disk atomically
- Trim in-memory copy to the most recent 1,000 entries while preserving the full file

The audit file path is configurable via `OC_AUDIT_FILE` environment variable; defaults to `src/server/audit.jsonl`.

---

### Design Work — Identity and Trust Model

Two specification documents produced:

**`docs/Identity_and_Plugin_Trust_v01.md`**

Identifies the structural gaps in the current design:

- No subject identity — every tool call looks identical to the policy server regardless of whether a human or autonomous subagent made it
- Subject is set inside the container — a compromised agent can forge its own identity
- Approvals do not route to the right person in multi-user deployments
- Default `allow-all` catch-all inverts the correct security posture
- Policy conflicts are silent

Proposes two identity dimensions: autonomous vs. human-initiated actors (single user) and multi-user team identity, with a recommended build order.

**`docs/Trust_and_Security_Model_v02.md`**

Full security model derived from ten concrete policy examples. Defines:

- **8 governing principles** (P1 Default Deny through P8 Legibility)
- **6 abstraction categories**: Subjects, Requests, Resources, Conditions, Named Entities, Trust Levels
- **OCPL** — OC Policy Language: a declarative rule language with `entities`, `rules`, and `defaults` blocks
- **Evaluation model**: priority-sorted rule matching, stateful rate limiting, conflict detection on load
- **Implementation roadmap**: Phases 3a–5 with complexity ratings
- **Honest limits**: identity root problem, emergent behavior, policy correctness, approval fatigue

---

## What Is Not Yet Built

| Item | Phase | Notes |
| --- | --- | --- |
| Subject identity in hook | 3a | Wire `isMain` / `isScheduledTask` from container input into `subject` field sent to policy server |
| Role-based rules | 3b | Person registry (`identities.yaml`), chatJid → role lookup |
| Approval routing | 3b | Notify requesting user via Telegram when their request is pending |
| Semantic request categories | 3c | Mapping table: tool + params → `read \| write \| search \| fetch \| …` |
| Named lists in policy | 3c | Domain lists, path lists usable in rules |
| Web UI wired to server | — | Static mockup live at [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app); needs backend connection |
| Rate limiting | 4 | Persistent counter store keyed by (subject, request, window) |
| Resource ownership | 4 | Record file creator at write time; enable owner-approval rules |
| Multi-person approval | 4 | Approval records with multi-approver quorum state |
| Plugin trust registry | 5 | Admin allowlist of approved plugin names/hashes |
| Signed subject tokens | 5 | Host-signed token so containers cannot forge their own identity |

---

## Immediate Next Step — Phase 3a

The single highest-value, lowest-cost item: wire subject identity through the hook.

Nanoclaw's container runner already sets per-container context indicating whether the session was initiated by a human (`isMain`) or is a scheduled task. Exposing this as a `subject` field in the `/check` payload — and adding subject-aware rules to `policies.yaml` — would immediately enable different policies for human sessions, subagents, and scheduled tasks with no cryptographic infrastructure required.

---

## Running the System

**Start the policy server:**

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

**Start Nanoclaw** (separate terminal or via launchctl):

```bash
launchctl start com.nanoclaw
```

**Trigger a live approval** by asking Nanoclaw anything that requires a web search. The approval card will appear at `http://localhost:8080`.
