# OC Policy — Progress Report

**Version**: v04
**Date**: 2026-03-21
**Author(s)**: Lew Tucker
**Status**: Phase 3b complete — identity-aware policy enforcement live

---

## Summary

Phase 3b delivers identity-aware policies: rules can now match on who is making a request, not just what tool they're using. The full stack — identity YAML, resolution module, policy engine, API, and UI — is implemented and working. Nanoclaw passes the Telegram chat JID on every tool call, the server resolves it to a `Person` with group memberships, and rules like "admin group can read the employee database" evaluate correctly.

---

## What Was Built in This Phase

### Phase 3b — Identity and Person Support

**Goal**: Extend the policy engine with a subject dimension so rules can match on who is making a request, not only what tool they're using.

**Files added:**

| File | Purpose |
| --- | --- |
| `src/server/identities.yaml` | People registry — id, name, telegram_id, groups |
| `src/server/identity.py` | `Person` dataclass + `IdentityStore` — O(1) lookup by Telegram chat ID |
| `src/server/test_container_identity.py` | Test script for container identity resolution without Telegram |

**Files modified:**

| File | Change |
| --- | --- |
| `src/server/policy_engine.py` | `evaluate()` takes optional `subject: Person`; `_matches()` gains `group` and `person` match keys; fixed `rule.result` bug (was `rule.effect`) |
| `src/server/server.py` | `CheckRequest` gains optional `channel_id`; wired `IdentityStore`; added `/identities` and `/identities/reload` endpoints; `RuleIn` renamed `effect` → `result` |
| `src/server/policies.yaml` | Migrated all `effect:` keys to `result:`; added group-based example rules |
| `src/server/audit.py` | Added `subject_id` field to `AuditEntry` — records which person triggered each action |
| `src/server/static/index.html` | Identities page wired to live `/identities` API; Person and Group dropdowns in add/edit policy form (populated from identity store); `← Dashboard` button on Policies and Approvals pages; display fixed to use `r.result` |

**How group-based rules work:**

```yaml
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
```

- Alice (admin group) → matches admin rule at priority 60 → **allowed**
- Bob (engineering group) → skips admin rule (not in admin group) → matches engineering rule → **denied**
- Anonymous request (no `channel_id`) → both group rules skip (no subject) → falls through to identity-agnostic rules

**Safe default**: if a rule has a `group` or `person` condition and no subject is present, the rule does not match. Anonymous requests fall through to lower-priority identity-agnostic rules.

---

### Terminology rename — `effect` → `result`

The field name `effect` was renamed to `result` across all layers:

- `Rule.result` in the policy engine
- `RuleIn.result` in the server API model
- `result:` key in `policies.yaml`
- UI form and table display

The `reload()` method retains a fallback `p.get("result", p.get("effect", "deny"))` for any old YAML files.

---

### Bug fixes

| Bug | Fix |
| --- | --- |
| `rule.effect` AttributeError on every `/check` call | Changed to `rule.result` in `evaluate()` |
| `engine.add/update` KeyError when called via API | `RuleIn.effect` renamed to `RuleIn.result` |

---

## End-to-End Identity Flow

```
Telegram message → Nanoclaw container
  → PreToolUse hook fires
  → POST /check { tool, params, channel_id: "tg:123456789" }
  → IdentityStore.resolve_by_telegram("tg:123456789") → Person(id="lew", groups=["admin"])
  → PolicyEngine.evaluate(tool, params, subject=lew)
  → First matching rule returned
  → Verdict + subject_id written to audit log
```

---

## What Is Not Yet Built

| Item | Phase | Notes |
| --- | --- | --- |
| Approval routing to requesting user | 3c | Notify requester via Telegram when their action is pending |
| Semantic request categories | 3c | Map `(tool, params)` → `read \| write \| search \| fetch` |
| Named lists in policy | 3c | Domain lists, path lists referenced by name |
| Rate limiting | 4 | Persistent counter keyed by (subject, request, window) |
| Resource ownership | 4 | Record file creator; enable owner-approval rules |
| Plugin trust registry | 5 | Admin allowlist of approved plugin names/hashes |
| Signed subject tokens | 5 | Host-signed token so containers cannot forge their own identity |

---

## Running the System

**Start the policy server:**

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mysecrettoken uvicorn server:app --port 8080 --reload
```

**Start Nanoclaw:**

```bash
cd ~/Documents/dev/nanoclaw && npm run dev
```

**Trigger a live identity-aware approval** by sending a message from a known Telegram identity. The audit log entry will show `subject_id` matching the person's ID from `identities.yaml`.
