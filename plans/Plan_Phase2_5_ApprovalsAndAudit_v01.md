# Plan: Phase 2.5 — Approvals Queue and Audit Log

**Version**: v01
**Date**: 2026-03-19
**Status**: Ready to build
**Reference**: [docs/OC_Policy_Control_v01.md](../docs/OC_Policy_Control_v01.md) — Phase 2.5

---

## Objective

Two additions to the policy server that complete the human-in-the-loop flow and
make the system observable:

1. **Approvals queue** — rules can return `effect: pending`, causing the server to
   create an approval record and hold the plugin in a poll loop until a human
   approves or denies.
2. **Audit log** — every `/check` request is recorded with timestamp, tool, params,
   verdict, and matched rule. Exposed via `GET /audit`.

Both are in-memory for now (lost on restart). Persistence comes in a later phase.

---

## Approvals Flow

```
Plugin                    Policy Server              Human (UI / curl)
  |                            |                           |
  |-- POST /check -----------> |                           |
  |                      effect=pending                    |
  |                      create ApprovalRecord             |
  |<-- {verdict:"pending",     |                           |
  |     approvalId:"abc"} -----|                           |
  |                            |<-- GET /approvals --------|
  |-- GET /approvals/abc? ---> |   (shows pending record)  |
  |   wait=true (polls)        |                           |
  |                            |<-- POST /approvals/abc ---|
  |                            |    {verdict:"allow"}      |
  |<-- {verdict:"allow"} ------|                           |
  | (unblocks, tool executes)  |                           |
```

---

## New Policy Rule

```yaml
- id: require-approval-for-curl
  description: curl requires human approval before execution
  effect: pending
  priority: 10
  match:
    tool: exec
    program: curl
```

---

## New Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/approvals` | agent token | List all approval records (pending + resolved) |
| `GET` | `/approvals/{id}` | agent token | Get one record; plugin polls this |
| `POST` | `/approvals/{id}` | agent token | Resolve: `{"verdict":"allow"\|"deny","reason":"..."}` |
| `GET` | `/audit` | agent token | Recent check log entries (newest first) |

---

## Data Models

**ApprovalRecord**
```python
@dataclass
class ApprovalRecord:
    id: str               # UUID
    tool: str
    params: dict
    rule_id: str
    created_at: datetime
    verdict: str | None   # None = pending, "allow" | "deny" = resolved
    reason: str | None
    resolved_at: datetime | None
```

**AuditEntry**
```python
@dataclass
class AuditEntry:
    id: str               # UUID
    timestamp: datetime
    tool: str
    params: dict
    verdict: str          # "allow" | "deny" | "pending"
    rule_id: str | None
    reason: str
    approval_id: str | None
```

---

## Files Changed

| File | Change |
| --- | --- |
| `src/server/approvals.py` | New — ApprovalRecord store with create/get/resolve |
| `src/server/audit.py` | New — AuditLog with append/list |
| `src/server/server.py` | Updated — wire in approvals + audit, add endpoints |
| `src/server/policies.yaml` | Add `require-approval-for-curl` rule |
| `src/server/test_server.py` | Add approvals and audit test group |

---

## Acceptance Criteria

- [ ] Rule with `effect: pending` creates an approval record and returns `approvalId`
- [ ] `GET /approvals` lists the pending record
- [ ] `POST /approvals/{id}` with `{"verdict":"allow"}` resolves it
- [ ] `GET /approvals/{id}` after resolution returns the allow verdict
- [ ] `POST /approvals/{id}` with `{"verdict":"deny"}` resolves with deny
- [ ] `GET /audit` shows an entry for every `/check` call
- [ ] Audit entries include tool, params, verdict, rule_id, timestamp
