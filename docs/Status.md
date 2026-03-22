# OC Policy — Status

**Date**: 2026-03-21

---

## What's Working Right Now

### Policy Server (`src/server/`)

The server runs locally and is fully functional. Start it with:

```bash
cd src/server && OC_POLICY_AGENT_TOKEN=mysecrettoken ./start.sh
```

| Capability | Status |
| --- | --- |
| Rule evaluation — allow / deny / pending | ✅ Working |
| YAML policy file — load, parse, persist | ✅ Working |
| Hot reload from disk (`POST /policies/reload`) | ✅ Working |
| REST CRUD for rules (add, edit, delete, list) | ✅ Working |
| Approvals queue — create, resolve, list | ✅ Working |
| Audit log — persists to JSONL file, survives restarts | ✅ Working |
| Fail-closed — blocks all calls if server is down | ✅ Working |
| Bearer token auth on all endpoints | ✅ Working |
| Identity resolution — chatJid → Person → groups | ✅ Working |
| Group-based rule matching (`match.group`) | ✅ Working |
| Person-specific rule matching (`match.person`) | ✅ Working |
| Identity store — load from `identities.yaml`, `/identities` API | ✅ Working |
| Subject ID recorded in audit log | ✅ Working |

### Web UI (`http://localhost:8080`)

Served directly from the policy server — no external deployment.

| Screen | Status |
| --- | --- |
| Dashboard — stat cards, policy table, activity feed | ✅ Live data, auto-refreshes every 10s |
| Approvals — pending cards with Approve / Deny; ← Dashboard button | ✅ Live data, auto-refreshes every 5s |
| Policies — rule table, add/edit/delete; person & group dropdowns; ← Dashboard button | ✅ Live CRUD |
| Identities — person cards with group pills | ✅ Live data |
| Plugins | 🔲 Placeholder — Phase 4 |

### Nanoclaw Hook (`~/dev/nanoclaw/container/agent-runner/src/index.ts`)

| Capability | Status |
| --- | --- |
| `PreToolUse` hook — POSTs to policy server | ✅ Live |
| Handles allow / deny / pending verdicts | ✅ Live |
| Polls `/approvals/{id}` until resolved or timeout | ✅ Live |
| Fails closed if server is unreachable | ✅ Live |
| Passes `channel_id` (Telegram chatJid) for identity resolution | ✅ Live |

### Testing

| Test | Status |
| --- | --- |
| Automated tests (`test_server.py`) | ✅ Passing |
| Container identity test (`test_container_identity.py`) | ✅ Passing |
| Approval flow tested end-to-end via live Telegram session | ✅ Verified |
| Group-based rules (Alice/admin, Bob/engineering) | ✅ Verified in server |

---

## What's Next

### Phase 3c — Semantic categories and named lists

The policy language currently matches on raw tool names and exact program strings. The next layer adds:

- **Semantic request categories** — a mapping table from `(tool, params)` → `read | write | search | fetch | …` so rules can say `match: { category: write }` instead of listing every write tool
- **Named lists** — domain lists, path lists, program lists referenced by name in rules (e.g. `match: { domain_list: approved-sites }`)

### Phase 3c — Approval routing

When a request is held pending, notify the requesting user via Telegram rather than requiring the admin to check the UI.

### Phase 4 — Plugin capabilities and credential injection

When a plugin is installed, it declares what capabilities and credentials it needs. The server auto-generates policies and prompts for approval. Credentials are stored encrypted, scoped per plugin, and injected at runtime.

### Phase 4 — Tamper prevention

Prevent the agent from modifying its own policies:

- Separate OS user for the agent process
- Split ports: agent on 8080, admin UI on 8443
- File immutability on `policies.yaml`
- HMAC-signed policy files
- Signed subject tokens (containers cannot forge their own identity)

### Backlog

| Item | Notes |
| --- | --- |
| Policy conflict detection | Flag overlapping / contradictory rules in the UI |
| `when:` clause in policy schema | Time-of-day, rate limits per OCPL design |
| Block reason surfaced to user | Agent explains why action was blocked |
| Rate limiting | Persistent counter store keyed by (subject, request, window) |
| Multi-person approval | Approval records with multi-approver quorum state |
| Plugin trust registry | Admin allowlist of approved plugin names/hashes |

---

## Key Files

| File | Purpose |
| --- | --- |
| `src/server/start.sh` | One-command server startup |
| `src/server/server.py` | FastAPI application |
| `src/server/policy_engine.py` | Rule parser and evaluator |
| `src/server/policies.yaml` | Active policy rules (edit directly or via UI) |
| `src/server/identities.yaml` | People and group memberships |
| `src/server/identity.py` | Identity store — chatJid → Person lookup |
| `src/server/approvals.py` | Approval queue |
| `src/server/audit.py` | Persistent audit log (JSONL) |
| `src/server/test_server.py` | Automated test harness |
| `src/server/test_container_identity.py` | Container identity test |
| `src/server/static/index.html` | Web UI |
| `~/dev/nanoclaw/container/agent-runner/src/index.ts` | Nanoclaw enforcement hook |
| `docs/Demo.md` | Five-minute demo walkthrough |
| `docs/Testing_Without_OpenClaw.md` | Full test guide |
| `docs/OC_Policy_Control_v01.md` | Architecture and design reference |
| `docs/Trust_and_Security_Model_v02.md` | Full security model and OCPL spec |
