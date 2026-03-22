# Plan: Identity/Person Support (Phase 3b)

## Context

The policy server currently evaluates rules based only on tool name, program, and file path — it has no concept of *who* is making the request. The design docs (Trust_and_Security_Model_v02, OC_Policy_Control_v01) specify an identity model where people have Telegram IDs, belong to groups, and rules can match on group membership.

**Goal**: Start with two people (Bob in engineering, Alice in admin) and demonstrate group-based rules like "admins can read the employee database, developers cannot."

---

## Implementation Steps

### 1. Create `identities.yaml` — the employee file
**File**: `src/server/identities.yaml`

```yaml
version: 1
people:
  - id: alice
    name: Alice
    telegram_id: "111222333"
    groups: [admin]
  - id: bob
    name: Bob
    telegram_id: "444555666"
    groups: [engineering]
```

The "Protected Employee file" from the design docs. Telegram IDs are the raw numeric chat IDs that nanoclaw's `chatJid` provides.

---

### 2. Create `identity.py` — identity resolution module
**File**: `src/server/identity.py`

Follows the same dataclass + store pattern as `approvals.py`:

- **`Person` dataclass**: `id, name, telegram_id, groups: list[str]`
- **`IdentityStore` class**:
  - `__init__(identity_file: Path)` — loads YAML on startup
  - `resolve_by_telegram(telegram_id: str) -> Person | None` — O(1) lookup by Telegram chat ID
  - `list_all() -> list[Person]` — for the API/UI
  - `reload()` — re-read YAML (same pattern as `PolicyEngine.reload()`)

Builds an internal `dict[str, Person]` keyed by `telegram_id` for fast resolution.

---

### 3. Extend `CheckRequest` — add optional `channel_id`
**File**: `src/server/server.py`

```python
class CheckRequest(BaseModel):
    tool: str
    params: dict
    channel_id: str | None = None  # Telegram chat JID for identity resolution
```

Making it optional preserves backward compatibility — requests without `channel_id` work exactly as before.

---

### 4. Extend policy engine — subject matching
**File**: `src/server/policy_engine.py`

**`evaluate()` signature change:**
```python
def evaluate(self, tool: str, params: dict, subject: Person | None = None) -> tuple[Effect, str, str | None]:
```

**`_matches()` gains new match keys** (after existing tool/program/path checks):

```python
# Group match
if "group" in m:
    if subject is None or m["group"] not in subject.groups:
        return False

# Person match (for person-specific rules)
if "person" in m:
    if subject is None or m["person"] != subject.id:
        return False
```

**Key behavior**: If a rule has a `group` or `person` condition and no subject is provided, the rule does NOT match. This is the safe default — anonymous requests fall through to identity-agnostic rules.

No changes to Rule or RuleIn models needed — `match` is already a generic dict that gains new recognized keys.

---

### 5. Wire identity resolution into `/check`
**File**: `src/server/server.py`

```python
# At module level:
IDENTITY_FILE = Path(os.environ.get("OC_IDENTITY_FILE", Path(__file__).parent / "identities.yaml"))
identities = IdentityStore(IDENTITY_FILE)

# In /check handler:
subject = None
if req.channel_id:
    subject = identities.resolve_by_telegram(req.channel_id)

effect, reason, rule_id = engine.evaluate(req.tool, req.params, subject)
```

Also passes `subject.id` (if resolved) to the audit log.

---

### 6. Extend audit log with subject
**File**: `src/server/audit.py`

- Add `subject_id: str | None = None` field to `AuditEntry`
- Include in `to_dict()` output
- Add to `append()` method signature
- Handle in `_load()` with `.get("subject_id")`

This provides the audit trail of which person triggered each action (per Principle P7 from the Trust & Security Model).

---

### 7. Add `/identities` API endpoints
**File**: `src/server/server.py`

```python
GET  /identities         → {"people": [{"id": "alice", "name": "Alice", ...}, ...]}
POST /identities/reload  → {"reloaded": 2}
```

Read-only for now. CRUD on identities is a future step.

---

### 8. Add example group-based rules
**File**: `src/server/policies.yaml`

```yaml
- id: admin-read-employees
  name: Admins read employee DB
  description: Admin group can read employee files
  effect: allow
  priority: 60
  match:
    group: admin
    path: "/workspace/employees/*"

- id: deny-eng-read-employees
  name: Deny engineering employee DB
  description: Engineering group cannot read employee files
  effect: deny
  priority: 50
  match:
    group: engineering
    path: "/workspace/employees/*"
```

**How it works with first-match-wins:**
- Alice (admin group) → matches admin rule at priority 60 → **allowed**
- Bob (engineering group) → skips admin rule (not in admin group) → matches engineering rule at priority 50 → **denied**
- Unknown user (no channel_id) → both group rules skip (no subject) → falls through to existing identity-agnostic rules

---

### 9. Build Identities UI page
**File**: `src/server/static/index.html`

Replace the placeholder Identities page with:
- Fetches from `GET /identities` when page is shown
- Card per person showing: name, ID, Telegram ID (partially masked), groups as colored pill badges
- Read-only (no add/edit/delete in this phase)
- Same styling patterns as existing Policies and Approvals pages

---

### 10. Extend nanoclaw plugin — pass `chatJid`
**File**: `~/Documents/dev/nanoclaw/container/agent-runner/src/index.ts`

Currently the beforeToolCall hook sends:
```typescript
body: JSON.stringify({ tool: toolName, params: event.tool_input ?? {} })
```

Change to:
```typescript
body: JSON.stringify({
  tool: toolName,
  params: event.tool_input ?? {},
  channel_id: containerInput.chatJid
})
```

This requires threading `chatJid` through to `createPolicyHook()`.

---

## Execution Order

| Phase | Steps | What |
|-------|-------|------|
| 1 | 1, 2 | Data file + identity module (foundation) |
| 2 | 3, 4 | Extend CheckRequest + policy engine (core logic) |
| 3 | 5, 6 | Wire /check + audit (integration) |
| 4 | 7, 8 | API endpoints + example rules |
| 5 | 9 | Identities UI page |
| 6 | 10 | Nanoclaw plugin (end-to-end) |

---

## Verification Plan

1. Start server, `POST /check` with `channel_id: "111222333"` (Alice) + employee file path → expect **allow**
2. `POST /check` with `channel_id: "444555666"` (Bob) + same path → expect **deny**
3. `POST /check` with no `channel_id` + same path → group rules skip, falls through to existing rules
4. `GET /identities` → returns both people with correct groups
5. UI Identities page shows both people with group badges
6. End-to-end with demo.sh: nanoclaw passes chatJid, group-based rules enforce correctly

---

## Key Design Decisions

- **`channel_id` is optional** → fully backward compatible with current nanoclaw
- **No subject = group rules don't match** → safe default, anonymous requests fall through
- **Identities are YAML-managed** → read-only API, no CRUD UI yet (keeps Phase 3b simple)
- **Groups only, no roles** → can add roles later without breaking anything
- **Same patterns as existing modules** → `approvals.py` and `audit.py` for consistency

## Files Modified

| File | Change |
|------|--------|
| `src/server/identities.yaml` | **New** — employee data |
| `src/server/identity.py` | **New** — identity resolution |
| `src/server/policy_engine.py` | Extend `evaluate()` + `_matches()` with subject |
| `src/server/server.py` | Extend CheckRequest, wire identity, add `/identities` endpoints |
| `src/server/audit.py` | Add `subject_id` field |
| `src/server/static/index.html` | Build Identities page |
| `~/Documents/dev/nanoclaw/.../index.ts` | Pass `chatJid` in POST body |
