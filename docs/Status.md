# OC Policy — Status

**Date**: 2026-03-19

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
| REST CRUD for rules (add, delete, list) | ✅ Working |
| Approvals queue — create, resolve, list | ✅ Working |
| Audit log — every check recorded | ✅ Working |
| Fail-closed — blocks all calls if server is down | ✅ Working |
| Bearer token auth on all endpoints | ✅ Working |

### Web UI (`http://localhost:8080`)

Served directly from the policy server — no external deployment.

| Screen | Status |
| --- | --- |
| Dashboard — stat cards, policy table, activity feed | ✅ Live data, auto-refreshes every 10s |
| Approvals — pending cards with Approve / Deny | ✅ Live data, auto-refreshes every 5s |
| Policies — rule table, add rule modal, delete | ✅ Live CRUD |
| Plugins | 🔲 Placeholder — Phase 4 |
| Identities | 🔲 Placeholder — Phase 3+ |

### OpenClaw Plugin (`src/plugin/`)

| Capability | Status |
| --- | --- |
| `before_tool_call` hook registered | ✅ Built |
| POSTs to policy server, handles allow/deny/pending | ✅ Built |
| Polls `/approvals/{id}` until resolved or timeout | ✅ Built |
| Fails closed if server is unreachable | ✅ Built |
| Installed into a live OpenClaw instance | ⏸ Blocked — needs local OC setup |

### Testing

| Test | Status |
| --- | --- |
| 27/27 automated tests passing (`test_server.py`) | ✅ |
| Approval flow tested end-to-end via browser | ✅ |
| Policy CRUD tested via browser and CLI | ✅ |
| Fail-closed verified with server stopped | ✅ |

---

## What's Next

### Immediate — connect to live OpenClaw

Once OpenClaw is running locally, three steps to go live:

1. Install the plugin (see `plans/Plan_Phase1_EnforcementPlugin_v01.md`, Step 3)
2. Set `OC_POLICY_AGENT_TOKEN` in OpenClaw's environment
3. Start the policy server before starting OpenClaw

### Phase 3+ — Identity model and trusted sources

Right now policies match on tool names and programs (`exec where program=git`).
The next layer allows attribute-based rules: _"allow engineering team members to run git"_.

Requires:
- Identity schema: users, groups, attributes
- Trusted source integrations: YAML file, 1Password, LDAP, OAuth
- Policy language extended with `subject:` matching
- Identities screen in the UI wired to live data

### Phase 4 — Plugin capabilities and credential injection

When a plugin is installed, it declares what it needs:

```json
"security": {
  "capabilities": {
    "required": [{ "tool": "exec", "program": "git" }],
    "optional": [{ "tool": "browser", "domain": "github.com" }]
  },
  "credentials": {
    "required": ["GITHUB_TOKEN"]
  }
}
```

The server generates policy entries automatically and prompts for approval.
Credentials are stored encrypted, scoped per plugin, and injected at runtime.
Both capabilities and credentials can be revoked independently from the UI.

### Phase 4 — Tamper prevention

Prevent OpenClaw from modifying its own policies:

- Separate OS user for the OpenClaw process (cannot write server files)
- Split ports: agent calls on 8080, admin UI on 8443 (not accessible to OC)
- File immutability on `policies.yaml` (`chflags schg`)
- HMAC-signed policy files (tampering is detectable)
- Persistent audit log (currently in-memory, lost on restart)

### Backlog

| Item | Notes |
| --- | --- |
| Persistent audit log | Survives restarts; write to append-only file |
| Policy conflict detection | Flag Never vs Allow collisions in the UI |
| `when:` clause in policy schema | Time-of-day, rate limits per ZPL design |
| Block reason back to OpenClaw | Agent explains to user why the action was blocked |
| Autonomous agent case | Policies for tasks with no human initiator |

---

## Key Files

| File | Purpose |
| --- | --- |
| `src/server/start.sh` | One-command server startup |
| `src/server/server.py` | FastAPI application |
| `src/server/policy_engine.py` | Rule parser and evaluator |
| `src/server/policies.yaml` | Active policy rules (edit directly or via UI) |
| `src/server/approvals.py` | Approval queue |
| `src/server/audit.py` | Audit log |
| `src/server/test_server.py` | Automated test harness (dummy OpenClaw) |
| `src/server/static/index.html` | Web UI |
| `src/plugin/src/index.ts` | OpenClaw enforcement plugin |
| `docs/Demo.md` | Five-minute demo walkthrough |
| `docs/Testing_Without_OpenClaw.md` | Full test guide |
| `docs/OC_Policy_Control_v01.md` | Architecture and design reference |
