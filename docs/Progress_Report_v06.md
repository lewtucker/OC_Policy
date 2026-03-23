# OC Policy — Progress Report v06

**Date**: 2026-03-23
**Phase**: 3c (agent identity, multi-runtime support)

---

## Summary

This report covers the work done since Phase 3 security hardening (v05). The focus was establishing distinct identities for each agent runtime (nanoclaw, OpenClaw) so the policy server can distinguish where requests originate, write agent-scoped rules, and show agent attribution in the UI.

---

## What Was Built

### Agent Identity Model

Each agent runtime now has its own entry in `identities.yaml` with a unique bearer token:

```yaml
agents:
  - id: nanoclaw
    name: Nanoclaw (lew-mac)
    token: nanoclaw-token-abc
  - id: openclaw-kyle
    name: OpenClaw (kyle-mac)
    token: openclaw-token-xyz
```

When the policy server receives a `/check` request, it resolves the bearer token to an `Agent` identity and records it throughout the system. Previously both runtimes shared a single `OC_POLICY_AGENT_TOKEN` and requests were indistinguishable.

A legacy fallback remains: if the token matches `OC_POLICY_AGENT_TOKEN` from the environment but isn't in `identities.yaml`, the request is accepted with `agent_id=None`. This keeps backwards compatibility during migration.

### Agent-Scoped Policy Rules

The policy engine now supports an `agent` match condition:

```yaml
- id: allow-openclaw-heartbeat
  result: allow
  match:
    agent: openclaw-kyle
    tool: read
```

This lets administrators write rules that apply only to requests from a specific agent runtime — e.g., auto-allow OpenClaw's heartbeat reads while still requiring approval for nanoclaw requests.

### Agent in Audit Log

Every audit entry now includes `agent_id`, identifying which runtime made the request:

```json
{
  "tool": "exec",
  "verdict": "pending",
  "agent_id": "openclaw-kyle",
  "subject_id": "lew"
}
```

Older entries (before this change) show no `agent_id` field and display as "—" in the UI.

### Agent in Approvals

Approval records now carry `agent_id`, shown in the approval card as a blue badge (⚙ openclaw-kyle) alongside the existing person badge (👤 lew). Approvers can see both who triggered the request and which runtime sent it.

### Agent Dropdown in Add/Edit Policy UI

The Add Policy Rule modal now includes an Agent dropdown populated from a new `GET /agents` endpoint. This sits between the Path field and the Person/Group dropdowns, making it easy to scope rules to a specific agent runtime.

### Dashboard UI Improvements

- **Column headers** added to Recent Activity feed — Status, Requester, Agent, Rule, Time, Request
- **Column reorder** — the request command (often long) moved to the last column so it truncates gracefully instead of pushing other columns off screen
- **Full-width activity feed** — Active Policies moved from a side-by-side layout to below the activity feed, giving the feed the full page width
- **Agent column** in the activity feed shows which runtime sent each request

### Shell Environment Fix

Discovered and fixed a bug in `~/.zshrc` where `OC_POLICY_SERVER_URL` and `OC_POLICY_AGENT_TOKEN` were on the same line separated by spaces, causing the token to be set to `mytoken` instead of `ltdemotoken`. This was the root cause of nanoclaw's 401 errors after the policy server was restarted with a known token.

---

## Architecture Changes

```
Before:
  Single OC_POLICY_AGENT_TOKEN → both nanoclaw and OpenClaw
  No way to distinguish agent runtimes in audit or policy rules

After:
  identities.yaml agents section → per-runtime tokens
  nanoclaw  → token: ltdemotoken     → agent_id: "nanoclaw"
  OpenClaw  → token: openclaw-token  → agent_id: "openclaw-kyle"
  Policy rules can match on agent: <id>
  Audit log records agent_id on every entry
  Approval records carry agent_id
  UI shows agent identity throughout
```

---

## Files Added or Significantly Changed

| File | Change |
| --- | --- |
| `src/server/identity.py` | Added `Agent` dataclass, `resolve_agent()`, `is_valid_agent_token()`, `list_agents()` |
| `src/server/identities.yaml` | Added `agents` section with nanoclaw and openclaw-kyle entries |
| `src/server/audit.py` | Added `agent_id` field to `AuditEntry`, persisted to JSONL |
| `src/server/approvals.py` | Added `agent_id` field to `ApprovalRecord` |
| `src/server/policy_engine.py` | Added `agent` match condition, `agent_id` parameter on `evaluate()` |
| `src/server/server.py` | Agent resolution from token, `GET /agents` endpoint, pass `agent_id` through check/audit/approvals |
| `src/server/static/index.html` | Activity feed headers + reorder, agent column, agent dropdown in policy form, full-width layout |

---

## What's Next

- **Per-person identity for OpenClaw** — map OpenClaw's Telegram sender IDs to person identities (currently `subject_id` is null for OpenClaw requests)
- **Improved plugin error messages** — distinguish 401 auth errors from network unreachable in the plugin's block reason
- **Phase C** — Policy change proposals for non-admins
- **Phase D Tier 3** — LLM-assisted policy analysis via chat
- **Identity provider migration** — replace YAML tokens with 1Password / LDAP / OAuth
