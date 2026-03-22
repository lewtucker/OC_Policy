# Plan: Rules and Identity on Policy Changes

**Version**: v01
**Date**: 2026-03-22
**Status**: Design — not yet implemented

---

## Problem

The policy system controls what actions an agent can perform, but nothing controls who can modify the policies themselves. This is a privilege escalation vector.

Today, anyone with the shared `OC_POLICY_AGENT_TOKEN` can:

- Create a rule like `{ result: allow, priority: 100, match: {} }` that overrides every restriction
- Delete protective deny rules
- Grant themselves or their group permissions they were never meant to have
- Modify rules through the NL chat panel or the API with no identity check

The system enforces policy on agents but has no policy on policy authors.

### Three gaps

1. **No identity on policy operations.** The API uses a single shared token. The server cannot distinguish Lew (admin) from Bob (engineering) from an anonymous chat user. Every caller has the same privilege level.

2. **No authorization for policy CRUD.** Anyone who can reach `POST /policies` can create any rule. There is no check on whether the caller should be allowed to modify the rule set.

3. **No escalation guard.** Even with authorization in place, nothing would prevent a user from creating a rule that grants more access than they themselves have — for example, an admin creating a rule that exempts a group from all restrictions, or lowering the priority of a critical deny rule.

---

## Design Principles

- **Least privilege**: users can only create rules within the scope of their own access.
- **Separation of concerns**: the enforcement plane (what agents can do) and the management plane (who can change rules) are distinct but use the same identity model.
- **Defense in depth**: identity resolution, role checks, and escalation guards are independent controls — each adds protection even if another is bypassed.
- **Protected invariants**: certain foundational rules (the admin gate itself, the fallback deny) cannot be removed through the API.
- **Auditability**: every policy change is attributed to a specific person and logged.

---

## Proposed Controls

### Control 1 — Identity on policy operations

The server needs to know who is calling the policy CRUD and chat endpoints.

**Current state**: A single `OC_POLICY_AGENT_TOKEN` is shared by the UI, the chat panel, and the enforcement plugin. It authenticates the caller as "someone who has the token" with no further identity.

**Target state**: Each person in `identities.yaml` has their own API token. The server resolves the token to a person and their groups before processing any request.

#### Implementation options

| Approach | Security | Complexity | Notes |
| --- | --- | --- | --- |
| **Per-person tokens in identities.yaml** | Medium | Low | Each person gets a `token` field. Server looks up token → person on every request. Tokens are static strings — better than shared, but no expiry or rotation. |
| **UI identity selector** | Low | Very low | Dropdown in the UI header: "Acting as: [Lew ▾]". Not secure (anyone can pick any name), but establishes the identity pattern for development. |
| **Session auth with login** | High | High | Username/password or OAuth flow. Full session management. Overkill for current stage. |

**Recommendation**: Start with **per-person tokens** for API security and an **identity selector** in the UI for development convenience. The selector can be hardened later with real auth.

#### Schema change

```yaml
# identities.yaml
people:
- id: lew
  name: Lew Tucker
  telegram_id: "tg:6741893378"
  groups: [admin]
  api_token: "lew-secret-token-here"    # new field

- id: bob
  name: Bob
  telegram_id: "tg:444555666"
  groups: [engineering]
  api_token: "bob-secret-token-here"    # new field
```

The shared `OC_POLICY_AGENT_TOKEN` would remain for the enforcement plugin (agent → server communication), which has no human identity. Policy CRUD endpoints would require a person token instead of (or in addition to) the agent token.

---

### Control 2 — Admin-only policy writes

Only people in a designated group (default: `admin`) can create, modify, or delete policies.

**Affected endpoints**:
- `POST /policies` — create rule
- `PUT /policies/{id}` — update rule
- `DELETE /policies/{id}` — delete rule
- `POST /chat` — NL policy authoring (proposes and applies rules)

**Behavior**:
- Server resolves the caller's identity from their token (Control 1)
- If the caller is not in the `admin` group → **403 Forbidden**: "Only admins can modify policies"
- `GET /policies` remains open to any authenticated caller (read-only is safe)
- The NL chat endpoint would still allow non-admins to ask questions ("what rules apply to me?", "why was that blocked?") but would block rule creation/deletion

**Edge case — the enforcement plugin**: The plugin calls `POST /check`, not the policy CRUD endpoints. It continues to use the shared agent token. No change needed for the enforcement path.

**Edge case — the chat panel**: When a non-admin uses the chat panel to request a rule, the assistant should explain that they don't have permission and suggest asking an admin. In a later phase, the request could be routed to an approval queue (see Phase C below).

---

### Control 3 — Privilege escalation prevention

Even admins should not be able to accidentally (or intentionally) undermine the policy system's integrity.

#### Protected rules

Certain rules are marked `protected: true` in the schema. Protected rules:
- Cannot be deleted via the API
- Cannot have their priority lowered
- Cannot have their result changed (e.g., deny → allow)
- Can only be modified by editing `policies.yaml` directly on the server

**Which rules should be protected?**

| Rule | Why |
| --- | --- |
| The admin-gate rule itself (once created) | Prevents someone from removing the admin requirement for policy changes |
| The fallback deny rule (`deny all unknown`, priority -1) | Ensures unknown actions are denied by default |
| The fallback catch-all (`ask-everything`, priority 1) | Ensures unmatched actions require approval rather than falling through silently |

#### Escalation checks

When a new rule is created, the server validates:

1. **No override of protected rules**: A new `allow` rule at a higher priority than a protected `deny` rule would effectively nullify it. The server should warn or block this.

2. **Scope check** (future): A caller should not be able to create an `allow` rule for a scope they themselves are denied. For example, if Bob is denied access to `/workspace/finance/*`, he should not be able to create a rule that allows his group to access it. This is complex to implement correctly and may be deferred.

3. **Priority ceiling**: Non-admin callers (if they are ever allowed to propose rules) cannot set priority above a configurable threshold.

#### Schema change

```yaml
# policies.yaml — new optional field
- id: "001"
  name: deny all unknown
  description: Deny anything that isn't recognized
  result: deny
  priority: -1
  match: {}
  protected: true    # new field
```

---

## Implementation Phases

### Phase A — Per-person tokens and admin-only writes

**Goal**: Close the privilege escalation gap. Only admins can modify policies.

**Changes**:

| File | Change |
| --- | --- |
| `identities.yaml` | Add `api_token` field to each person |
| `identity.py` | Add `resolve_by_token(token) → Person` lookup |
| `server.py` | Policy CRUD endpoints resolve caller identity from `Authorization` header. Check `admin` group membership. Return 403 if not admin. |
| `nl_policy.py` | `/chat` endpoint resolves caller identity. Block rule creation for non-admins. Allow read-only queries (explain, list). |
| `static/index.html` | Show current identity in UI header. If not admin, disable "Add Rule" button and show explanation. Chat panel shows "ask your admin" for rule requests from non-admins. |
| `audit.py` | Log `changed_by` field on policy CRUD audit entries |

**Backward compatibility**: The shared `OC_POLICY_AGENT_TOKEN` continues to work for `POST /check` (enforcement). Policy CRUD can accept either a person token or the agent token (agent token implies admin for backward compat during migration).

### Phase B — Protected rules and escalation guards

**Goal**: Prevent even admins from accidentally breaking the policy system.

**Changes**:

| File | Change |
| --- | --- |
| `policies.yaml` | Add `protected: true` to critical rules |
| `policy_engine.py` | `Rule` dataclass gets `protected` field. `remove()` and `update()` reject changes to protected rules. |
| `server.py` | `DELETE /policies/{id}` returns 403 for protected rules. `PUT /policies/{id}` validates no restricted field changes on protected rules. |
| `nl_policy.py` | System prompt tells Claude about protected rules. Claude should not propose deleting or overriding them. |
| `static/index.html` | Protected rules show a lock icon. Edit/delete buttons are disabled with tooltip explaining why. |

### Phase C — Policy change proposals for non-admins

**Goal**: Non-admins can request policy changes, but changes go through admin approval.

**Changes**:

| Concept | Detail |
| --- | --- |
| Policy change queue | New data structure similar to `ApprovalStore` but for proposed policy changes |
| Chat flow | Non-admin uses chat → assistant creates a proposal → proposal appears in admin's approval queue |
| Admin review | Admin sees proposed rule, who requested it, and why. Can approve (rule is applied) or reject (requester is notified). |
| Notification | Telegram notification to admins when a policy change is proposed |

This phase reuses the existing approval pattern and extends it to the management plane.

### Phase D — Policy Analysis Agent

**Goal**: An automated agent that analyzes the rule set as a whole, catching problems that no single rule check would find. Initially simple and deterministic; grows into a sophisticated policy intelligence layer over time.

This is distinct from the enforcement engine (which evaluates a single request against rules) and from the escalation guards (which validate a single rule at write time). The analysis agent looks at the *entire rule set* and asks: is this policy coherent, complete, and safe?

#### Tier 1 — Deterministic checks (run on every policy change)

These are fast, algorithmic checks that run server-side whenever a rule is added, modified, or deleted. They produce warnings or hard blocks.

| Check | Description | Severity |
| --- | --- | --- |
| **Shadow detection** | A higher-priority rule completely covers a lower-priority rule's match conditions, making the lower rule unreachable. Example: `allow Bash *` at priority 50 shadows `deny Bash curl` at priority 30. | Warning |
| **Conflict detection** | Two rules at the same priority match the same conditions but have different results. First-match-wins makes the outcome depend on insertion order — fragile. | Warning |
| **Orphan identity references** | A rule references a person or group that doesn't exist in `identities.yaml`. The rule will never fire. | Warning |
| **Override of protected rules** | A new allow rule at higher priority would effectively nullify a protected deny rule. | Block |
| **Gap detection** | A tool or program that appears in audit logs has no explicit rule — it falls through to the catch-all. May indicate a missing policy. | Info |
| **Priority collision** | Multiple unrelated rules share the same priority. Not a bug, but makes ordering ambiguous and harder to reason about. | Info |

#### Tier 2 — Heuristic analysis (run on demand or periodically)

More expensive checks that may involve reviewing audit history or reasoning about rule interactions.

| Check | Description |
| --- | --- |
| **Unused rules** | Rules that haven't matched any request in the audit log over a configurable window. May be stale or misconfigured. |
| **Overly broad allows** | An allow rule with very few match conditions (e.g., just `tool: Bash`) that covers a wide surface area. Flag for review. |
| **Deny-then-allow chains** | A deny rule exists for a scope, but a higher-priority allow rule for a subset of the same scope also exists. This is valid (allow-specific-deny-general), but worth surfacing so the admin understands the interaction. |
| **Group coverage gaps** | A rule applies to group A but not group B, and both groups have members who use the same tool. May be intentional, but worth flagging. |
| **Temporal patterns** | Rules that were added and deleted repeatedly (from audit history), suggesting uncertainty about the right policy. |

#### Tier 3 — LLM-assisted analysis (future)

Use Claude to reason about the policy set in context:

- "Summarize what each group can and cannot do"
- "What would happen if Alice tried to run `curl https://internal-api/secrets`? Walk through every rule."
- "Are there any ways an engineering group member could access financial data?"
- "Suggest a minimal rule set that achieves the same effective policy with fewer rules"
- "Compare the current policy to last week's — what changed and what are the implications?"

This tier turns the analysis agent into a policy advisor that can answer natural-language questions about the security posture, not just flag mechanical issues.

#### Architecture

```
                    ┌─────────────────────┐
                    │   Policy Analysis   │
                    │       Agent         │
                    └─────┬───────┬───────┘
                          │       │
              ┌───────────┘       └───────────┐
              ▼                               ▼
    ┌──────────────────┐           ┌─────────────────────┐
    │  Tier 1: Static  │           │  Tier 2: Heuristic  │
    │  (every write)   │           │  (on demand / cron)  │
    └──────────────────┘           └─────────────────────┘
              │                               │
              ▼                               ▼
    ┌──────────────────┐           ┌─────────────────────┐
    │ Warnings / Blocks│           │  Reports / Alerts   │
    │ (inline in API)  │           │  (dashboard + chat) │
    └──────────────────┘           └─────────────────────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │  Tier 3: LLM-based  │
                                   │  (chat / scheduled)  │
                                   └─────────────────────┘
```

**Tier 1** runs synchronously inside the policy CRUD endpoints. When a rule is added or modified, the engine runs all Tier 1 checks and returns warnings in the API response. Hard blocks (override of protected rules) prevent the write.

**Tier 2** runs on demand via a `GET /policies/analyze` endpoint or on a schedule. Results appear in the dashboard as a "Policy Health" panel and can be queried through the chat assistant.

**Tier 3** is invoked through the chat panel ("analyze my policies", "what can Bob do?") and uses the same NL infrastructure from the chat endpoint, with an expanded system prompt that includes the full rule set, identities, and recent audit history.

**Chat panel as the unified interface**: The existing chat panel serves double duty — it handles both rule authoring ("block curl") and policy analysis ("what can Bob do?", "are there any gaps?"). When the user asks a question rather than requesting a rule change, the backend injects Tier 1/2 analysis results into Claude's system prompt alongside the policies and identities. This means Claude answers with awareness of shadows, conflicts, and gaps — not just the raw rules. No separate analysis UI is needed; the chat panel *is* the interface to the policy analyst.

#### Implementation

| File | Phase | Purpose |
| --- | --- | --- |
| `policy_analyzer.py` (new) | D | Core analysis engine — Tier 1 and Tier 2 checks |
| `policy_engine.py` | D | Call Tier 1 checks from `add()` and `update()`, return warnings |
| `server.py` | D | `GET /policies/analyze` endpoint for Tier 2. Include warnings in POST/PUT responses. |
| `nl_policy.py` | D | Expand system prompt with analysis capabilities for Tier 3 |
| `static/index.html` | D | "Policy Health" dashboard panel showing warnings, shadow/conflict indicators on rule rows |

---

## Open Questions

1. **Should the agent token imply admin?** During the transition, the shared token needs to keep working. But long-term, the enforcement plugin should not have policy-write access. Separate the "check" token from the "admin" token?

2. **Group-scoped admin?** Could there be group-level admins who can only modify rules scoped to their group? For example, an engineering lead who can adjust engineering rules but not admin rules. This adds complexity — defer unless needed.

3. **Immutable rules via config vs. database?** Protected rules could be defined in a separate file (`system_policies.yaml`) that the API cannot touch, while user-created rules live in `policies.yaml`. This gives a clean separation between system invariants and user rules.

4. **Audit granularity for policy changes?** Should the audit log capture the full before/after diff of a rule change, or just the fact that it was changed?

5. **Token rotation?** Per-person tokens in YAML are static. Is there a lightweight rotation mechanism worth building, or is this acceptable for the current stage?

---

## Files to Create or Modify

| File | Phase | Purpose |
| --- | --- | --- |
| `identities.yaml` | A | Add `api_token` fields |
| `identity.py` | A | Token → person lookup |
| `server.py` | A, B | Admin checks on CRUD, protected rule enforcement |
| `nl_policy.py` | A, B | Identity-aware chat, protected rule awareness |
| `policy_engine.py` | B | `protected` field, escalation validation |
| `policies.yaml` | B | Mark critical rules as protected |
| `static/index.html` | A, B | Identity display, admin-only controls, lock icons |
| `audit.py` | A | `changed_by` attribution on policy changes |
| `approval_store.py` (new) | C | Policy change proposal queue |
| `policy_analyzer.py` (new) | D | Tier 1/2 analysis checks — shadows, conflicts, gaps, orphan refs |
