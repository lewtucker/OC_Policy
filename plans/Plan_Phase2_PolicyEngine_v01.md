# Plan: Phase 2 — Policy Engine

**Version**: v01
**Date**: 2026-03-19
**Status**: Ready to build
**Reference**: [docs/OC_Policy_Control_v01.md](../docs/OC_Policy_Control_v01.md) — Phase 2

---

## Objective

Replace the hardcoded `ALLOWED_PROGRAMS` set in `server.py` with a real policy engine:
a YAML policy file, a rule parser, a rule evaluator, and REST CRUD endpoints to manage
policies at runtime. The plugin and test harness are unchanged — only the server evolves.

---

## Deliverables

```text
src/server/
├── policy_engine.py   # Rule parser + evaluator (new)
├── policies.yaml      # Default policy file (new)
├── server.py          # Updated to use engine + CRUD endpoints
└── test_server.py     # Updated with Phase 2 test cases
```

---

## Policy YAML Schema

```yaml
version: 1
policies:
  - id: allow-git          # unique, used for CRUD operations
    description: Allow git commands in any directory
    effect: allow           # allow | deny | pending
    priority: 10            # higher = evaluated first; first match wins
    match:
      tool: exec            # matches req.tool exactly
      program: git          # matches first word of exec command (supports * glob)

  - id: deny-rm
    description: Block rm commands unconditionally
    effect: deny
    priority: 20            # higher priority than allow rules — evaluated first
    match:
      tool: exec
      program: rm
```

**Match fields** (all optional; omitting a field means "match anything"):

| Field | Applies to | Description |
| --- | --- | --- |
| `tool` | all | Tool name (`exec`, `read_file`, etc.) |
| `program` | `exec` | First word of command string; supports `*` glob |
| `path` | file tools | File path; supports `*` and `**` glob |

**Evaluation order**:
1. All rules where `match` is satisfied are collected.
2. Sorted by `priority` descending (highest first).
3. The first match's `effect` is returned.
4. If no rule matches → implicit `deny`.

---

## New Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/policies` | List all rules |
| `POST` | `/policies` | Append a new rule |
| `DELETE` | `/policies/{id}` | Remove a rule by ID |
| `POST` | `/policies/reload` | Reload from disk (useful if file edited manually) |

---

## Step 1 — Policy Engine Module (`src/server/policy_engine.py`)

- `Rule` dataclass: `id`, `effect`, `match`, `priority`, `description`
- `PolicyEngine` class:
  - `__init__(policy_file: Path)` — loads and sorts rules
  - `reload()` — re-reads YAML from disk
  - `evaluate(tool, params) -> (effect, reason, rule_id)` — first-match evaluator
  - `_matches(rule, tool, params)` — field-by-field matching with glob support
  - `rules` property — sorted list for the list endpoint
  - `add(rule_data)` / `remove(id)` — mutate + persist to YAML

## Step 2 — Default Policy File (`src/server/policies.yaml`)

Ships with a minimal set that mirrors Phase 1 behavior:
- `allow-git` (priority 10)
- Implicit deny for everything else

## Step 3 — Update Server (`src/server/server.py`)

- Remove `ALLOWED_PROGRAMS` and `extract_program`
- Instantiate `PolicyEngine` at startup
- `/check` delegates to `engine.evaluate()`
- Add CRUD endpoints

## Step 4 — Update Tests (`src/server/test_server.py`)

Add tests for:
- Rule that doesn't exist in YAML → deny
- Adding a new rule via `POST /policies` → subsequent check allows it
- Deleting a rule → subsequent check denies it
- Priority: deny rule at higher priority beats an allow rule for the same program

---

## Acceptance Criteria

- [ ] `git` still passes (loaded from YAML, not hardcoded)
- [ ] `ls` still blocked
- [ ] `POST /policies` adds a rule; next check reflects it
- [ ] `DELETE /policies/{id}` removes it; next check reverts
- [ ] High-priority deny beats low-priority allow for same program
- [ ] `policies.yaml` edited on disk + `POST /policies/reload` → new rules take effect
- [ ] No credentials in any committed file
