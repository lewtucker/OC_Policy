# OC Policy — Progress Report v05

**Date**: 2026-03-22
**Phase**: 3 (security hardening, policy intelligence, NL authoring)

---

## Summary

This report covers the work done since Phase 3b (identity-aware rules). The focus was closing the policy management security gap, building a policy intelligence layer, and improving the UI for day-to-day use.

---

## What Was Built

### Two-Token Auth Split

The single shared `OC_POLICY_AGENT_TOKEN` was split into two separate tokens with different scopes:

| Token | Who holds it | What it can do |
| --- | --- | --- |
| `OC_POLICY_AGENT_TOKEN` | Nanoclaw enforcement plugin | Call `/check` and poll `/approvals/{id}` only |
| `OC_POLICY_ADMIN_TOKEN` | Humans managing policies | Full policy CRUD, approvals, audit, identities |

This closes the privilege escalation gap where the enforcement plugin had the same token as human administrators and could create, modify, or delete rules.

### Per-Person API Tokens (Phase A)

Each person in `identities.yaml` now has an `api_token` field. The server resolves the token to a `Person` on every management request and checks group membership before allowing policy writes. Non-admin callers receive 403.

A bootstrap `OC_POLICY_ADMIN_TOKEN` env var remains as a superuser fallback for initial setup.

- `GET /me` endpoint — returns the identity of the calling token
- Sidebar shows logged-in user and admin badge
- `changed_by` field added to audit log entries for policy CRUD

Tokens were upgraded from placeholder strings (`lew-token`) to 12-character random hex secrets generated via `secrets.token_hex(6)`. `identities.yaml` is now gitignored.

### Protected Rules (Phase B)

Rules can be marked `protected: true` in `policies.yaml`. Protected rules:
- Cannot be deleted via the API (returns 403)
- Cannot be modified via the API (returns 403)
- Show a 🔒 icon in the UI with edit/delete buttons replaced by "locked"
- Are skipped by "Delete All"
- Can only be changed by editing `policies.yaml` directly

`deny-non-admin-rm` is the first rule marked protected.

### Policy Analyzer — Tier 1 (deterministic)

A new `policy_analyzer.py` module runs on every policy write and returns structured findings:

| Check | Severity | Description |
| --- | --- | --- |
| Shadow | Warning | A higher-priority rule makes a lower rule unreachable |
| Conflict | Warning | Two rules at equal priority with overlapping conditions but different results |
| Orphan | Warning | Rule references a person or group not in identities |
| Gap | Warning/Info | A catch-all `match: {}` rule permits or queues everything |

Findings are returned inline in `POST /policies` and `PUT /policies` responses.

### Policy Analyzer — Tier 2 (heuristic)

Available via `GET /policies/analyze`, with audit history included:

| Check | Severity | Description |
| --- | --- | --- |
| Broad allow | Info | Allow rule with only 1 match condition (very permissive) |
| Uncovered group | Info | A group in identities has no rules targeting it |
| Unused rule | Info | Rule has never matched any request in the audit log |

### Policy Health Panel

A collapsible health panel on the Policies page shows analyzer findings at a glance:
- Collapsed: colored badges (✕ errors · ⚠ warnings · ℹ info) or "✓ No issues found"
- Expanded: full finding list with severity pills and rule references
- Refreshed on every `loadPolicies()` call

### NL Policy Chat Panel

A floating, draggable chat window powered by Claude that lets operators describe rules in plain English:
- Parses `PROPOSED_RULE` JSON blocks from responses and shows Add / Cancel buttons
- System prompt includes: all current rules, identities, last 20 audit entries, analyzer findings
- Context-aware splash message per page (Dashboard, Policies, Approvals, Identities)
- Resets to default position and clears history on close
- Chat panel is positioned top-right with size clamped to viewport

### Approvals — Subject Attribution

The person who triggered a pending action is now stored on the approval record and shown in the approval card (`👤 bob`). Previously the approver had no way to know who made the request.

### UI Improvements

- Add Rule modal: Display Name field moved first; Rule ID auto-fills as kebab-case as you type; stops auto-filling once manually edited
- Token modal: Show/Hide toggle on the token input field
- Delete All: skips protected rules
- `start.sh`: kills existing server on port 8080 at startup; separate `kill-server.sh` script

### Rule Smoke Test Script

`test_rules.sh` runs 17 `/check` calls covering all identities (Lew, Alice, Bob, Lew+Shala, anonymous) and key actions, verifying expected verdicts. All 17 pass against the current rule set.

---

## Architecture Changes

```
Before:
  Single OC_POLICY_AGENT_TOKEN → all endpoints

After:
  OC_POLICY_AGENT_TOKEN  → /check, GET /approvals/{id}  (enforcement plugin only)
  OC_POLICY_ADMIN_TOKEN  → all management endpoints      (bootstrap superuser)
  Per-person api_token   → all management endpoints      (individual humans, checked for admin group)
```

---

## Files Added or Significantly Changed

| File | Change |
| --- | --- |
| `src/server/policy_analyzer.py` | New — Tier 1+2 analysis engine |
| `src/server/nl_policy.py` | New — NL chat endpoint (Claude-powered) |
| `src/server/identity.py` | Added `api_token`, `is_admin()`, `resolve_by_token()` |
| `src/server/server.py` | Two-token split, per-person auth, `/me`, analysis wiring |
| `src/server/policy_engine.py` | `protected` field, `PermissionError` on locked rules |
| `src/server/approvals.py` | `subject_id` stored on approval records |
| `src/server/audit.py` | `changed_by` field for policy CRUD attribution |
| `src/server/identities.yaml` | `api_token` fields, proper random secrets, gitignored |
| `src/server/start.sh` | Kill-on-start, two tokens generated, ANTHROPIC_API_KEY status |
| `src/server/kill-server.sh` | New — standalone kill script |
| `src/server/test_rules.sh` | New — rule smoke test (17 checks, 17 passing) |
| `src/server/static/index.html` | Policy Health panel, protected rule UI, NL chat panel, identity bar, auto-fill rule ID, Show/Hide token |
| `.gitignore` | Added `src/server/identities.yaml` |

---

## What's Next

- **Phase C** — Policy change proposals for non-admins (postponed — revisit after Phase D Tier 3)
- **Phase D Tier 3** — LLM-assisted policy analysis via chat ("what can Bob do?", "find gaps")
- **Phase 3c** — Semantic request categories and named lists
- **Phase 3c** — Approval routing (notify requesting user via Telegram)
- **Identity provider migration** — replace YAML tokens with 1Password / LDAP / OAuth
