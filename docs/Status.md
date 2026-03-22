# OC Policy — Status

**Date**: 2026-03-22

---

## What's Working Right Now

### Policy Server (`src/server/`)

Start with:

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mytoken OC_POLICY_ADMIN_TOKEN=myadmintoken ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY ./start.sh
```

| Capability | Status |
| --- | --- |
| Rule evaluation — allow / deny / pending | ✅ Working |
| YAML policy file — load, parse, persist | ✅ Working |
| Hot reload from disk (`POST /policies/reload`) | ✅ Working |
| REST CRUD for rules (add, edit, delete, list) | ✅ Working |
| Protected rules — `protected: true` blocks delete/edit via API | ✅ Working |
| Approvals queue — create, resolve, list; subject_id stored | ✅ Working |
| Audit log — persists to JSONL file, survives restarts | ✅ Working |
| Fail-closed — blocks all calls if server is down | ✅ Working |
| Two-token auth — agent token (enforcement) / admin token (management) | ✅ Working |
| Per-person API tokens — resolves token → Person → admin check | ✅ Working |
| Admin-only policy writes — 403 for non-admin callers | ✅ Working |
| Identity resolution — chatJid → Person → groups | ✅ Working |
| Group-based rule matching (`match.group`) | ✅ Working |
| Person-specific rule matching (`match.person`) | ✅ Working |
| Identity store — load from `identities.yaml`, `/identities` API | ✅ Working |
| Subject ID recorded in audit log and approval records | ✅ Working |
| Policy change attribution — `changed_by` in audit log | ✅ Working |
| `GET /me` — resolves caller token to identity | ✅ Working |
| Policy Analyzer Tier 1 — shadow, conflict, orphan, gap detection | ✅ Working |
| Policy Analyzer Tier 2 — unused rules, broad allows, uncovered groups | ✅ Working |
| `GET /policies/analyze` endpoint | ✅ Working |
| NL policy chat — describe rules in plain English, Claude proposes YAML | ✅ Working |
| Token security — 12-char random hex tokens; identities.yaml gitignored | ✅ Working |

### Web UI (`http://localhost:8080`)

| Screen | Status |
| --- | --- |
| Dashboard — stat cards, policy table, activity feed | ✅ Live data, auto-refreshes every 10s |
| Approvals — pending cards with requester identity (👤 bob); Approve / Deny | ✅ Live data, auto-refreshes every 5s |
| Policies — rule table with 🔒 lock on protected rules; add/edit/delete; policy health panel | ✅ Live CRUD |
| Policy Health panel — collapsible summary badges + findings list; shown on Policies page | ✅ Working |
| Identities — person cards with group pills | ✅ Live data |
| Policy Assistant — floating draggable chat panel, context-aware splash, NL rule authoring | ✅ Working |
| Add Rule modal — Display Name auto-fills Rule ID as kebab-case | ✅ Working |
| Identity bar — shows logged-in user and admin status in sidebar | ✅ Working |
| Token modal — Show/Hide toggle on token input | ✅ Working |
| Plugins | 🔲 Placeholder — Phase 4 |

### Nanoclaw Hook (`~/dev/nanoclaw/container/agent-runner/src/index.ts`)

| Capability | Status |
| --- | --- |
| `PreToolUse` hook — POSTs to policy server | ✅ Live |
| Handles allow / deny / pending verdicts | ✅ Live |
| Polls `/approvals/{id}` until resolved or timeout | ✅ Live |
| Fails closed if server is unreachable | ✅ Live |
| Passes `channel_id` (Telegram chatJid) for identity resolution | ✅ Live |
| Uses separate agent token (not admin token) | ✅ Live |

### Testing

| Test | Status |
| --- | --- |
| Automated tests (`test_server.py`) | ✅ Passing |
| Container identity test (`test_container_identity.py`) | ✅ Passing |
| Rule smoke tests (`test_rules.sh`) — 17 checks across all identities | ✅ 17/17 passing |
| Approval flow tested end-to-end via live Telegram session | ✅ Verified |

---

## What's Next

### Phase C — Policy change proposals for non-admins (postponed)

Non-admins can request rule changes via the chat panel; requests go into an admin approval queue with Telegram notification. Reuses the existing approval pattern extended to the management plane.

### Phase D Tier 3 — LLM-assisted policy analysis

Use the NL chat panel to answer sophisticated policy questions:

- "What can Bob do and not do?"
- "Are there any ways engineering could access financial data?"
- "Compare last week's rules to today's — what changed?"

The chat panel already has Tier 1/2 findings in its system prompt. Tier 3 extends this with richer reasoning prompts.

### Phase 3c — Semantic categories and named lists

- **Semantic request categories** — map `(tool, params)` → `read | write | search | fetch` so rules can match by intent rather than exact tool names
- **Named lists** — domain allowlists and path patterns reusable across rules

### Phase 3c — Approval routing

Notify the requesting user via Telegram when their action is held pending, rather than requiring the admin to notice in the UI.

### Phase 4 — Plugin capabilities and credential injection

When a plugin is installed, it declares what capabilities and credentials it needs. The server auto-generates policies and prompts for approval.

### Phase 4 — Tamper prevention

- Separate OS user for the agent process
- Split ports: agent on 8080, admin UI on 8443
- HMAC-signed policy files
- Signed subject tokens (containers cannot forge their own identity)

### Backlog

| Item | Notes |
| --- | --- |
| `when:` clause in policy schema | Time-of-day, rate limits per OCPL design |
| Block reason surfaced to user | Agent explains why action was blocked |
| Rate limiting | Persistent counter store keyed by (subject, request, window) |
| Multi-person approval | Approval records with multi-approver quorum state |
| Plugin trust registry | Admin allowlist of approved plugin names/hashes |
| Identity provider migration | Replace identities.yaml tokens with 1Password / LDAP / OAuth |

---

## Key Files

| File | Purpose |
| --- | --- |
| `src/server/start.sh` | One-command server startup (kills existing, generates tokens) |
| `src/server/kill-server.sh` | Kill any process on port 8080 |
| `src/server/server.py` | FastAPI application — all endpoints |
| `src/server/policy_engine.py` | Rule parser, evaluator, protected rule enforcement |
| `src/server/policy_analyzer.py` | Tier 1+2 analysis — shadows, conflicts, gaps, unused, broad, uncovered |
| `src/server/nl_policy.py` | NL policy chat — Claude-powered rule authoring |
| `src/server/policies.yaml` | Active policy rules (edit directly or via UI) |
| `src/server/identities.yaml` | People, groups, API tokens — **gitignored, never commit** |
| `src/server/identity.py` | Identity store — chatJid / token → Person lookup |
| `src/server/approvals.py` | Approval queue with subject attribution |
| `src/server/audit.py` | Persistent audit log (JSONL) with policy change attribution |
| `src/server/test_server.py` | Automated test harness |
| `src/server/test_rules.sh` | Rule smoke tests — all identities and key actions |
| `src/server/static/index.html` | Web UI |
| `~/dev/nanoclaw/container/agent-runner/src/index.ts` | Nanoclaw enforcement hook |
| `docs/Demo.md` | Five-minute demo walkthrough |
| `docs/Testing_Without_OpenClaw.md` | Full test guide |
| `docs/Plan_Policy_Change_Authorization.md` | Two-token auth, protected rules, policy analyzer design |
