# OC Policy

A policy management system for [OpenClaw](https://openclaw.dev) — an autonomous AI agent. OC Policy lets you define rules that govern what actions OpenClaw is allowed to take, enforced before execution rather than after the fact.

## Quick Start

**Requirements**: Python ≥ 3.11
put the following in your ~/.zshrc
export OC_POLICY_SERVER_URL=http://host.docker.internal:8080
export OC_POLICY_AGENT_TOKEN=ltdemotoken


```bash
# 1. Install dependencies (once)
pip3 install -r src/server/requirements.txt

# 2. Start the server
cd src/server
./start.sh
```

The script generates a token if you don't have one, prints it to the terminal, and starts the server. Open **[http://localhost:8080](http://localhost:8080)** in a browser, enter the server URL and token when prompted, and the UI connects.

To use a specific token instead of a generated one:

```bash
OC_POLICY_AGENT_TOKEN=mytoken ./start.sh
```

## Testing

**Pytest suite** (self-contained, no running server needed):

```bash
cd src/server
python -m pytest test_policy_suite.py -v
```

59 tests across 8 categories: auth & authorization, protected rules, policy evaluation, policy analyzer, approval flow, audit trail, policy CRUD, and identities. Tests create their own temp fixtures and clean up after themselves.

**Rule smoke tests** (requires running server):

```bash
cd src/server
OC_POLICY_AGENT_TOKEN=mytoken ./test_rules.sh
```

17 `/check` calls across all identities verifying expected verdicts.

See [docs/Testing_Without_OpenClaw.md](docs/Testing_Without_OpenClaw.md) for a full walkthrough.

---

## What it does

OpenClaw can read files, run shell commands, make network requests, and call external APIs on your behalf. OC Policy intercepts every tool call and checks it against a set of rules before it executes. If no rule permits the action, it is blocked.

Rules are written in a human-readable policy language and managed through a web UI. Policies are attribute-based (e.g. "allow git commands in project directories") rather than tied to specific users or sessions, so they remain stable as your team and environment change.

## Architecture

```
OpenClaw
  └── TypeScript enforcement plugin
        └── before_tool_call hook → POST /check
              └── Python policy server (FastAPI)
                    ├── Policy rules (YAML)
                    ├── Approvals queue
                    ├── Audit log
                    └── Web UI (http://localhost:8080)
```

Three layers:

1. **Enforcement plugin** — TypeScript plugin inside OpenClaw that intercepts every tool call and asks the Policy Server for a verdict. Fails closed: if the server is unreachable, the call is blocked.
2. **Policy server** — Python/FastAPI service that evaluates incoming tool calls against stored rules and returns `allow`, `deny`, or `pending` (awaiting human approval).
3. **Web UI** — Dashboard for managing policies, reviewing pending approvals, and auditing activity. Served from the policy server — no separate deployment needed.

See [docs/OC_Policy_Control_v01.md](docs/OC_Policy_Control_v01.md) for the full architecture and design.

## Status

Phase 3 (security hardening + policy intelligence). 59 pytest tests passing.

- Two-token auth split (agent vs admin), per-person API tokens, admin-only policy writes
- Protected rules, policy analyzer (Tier 1 + Tier 2), NL policy chat panel
- Identity-aware rule matching (person, group), approval flow with subject attribution
- See [docs/Status.md](docs/Status.md) for current status and [docs/Progress_Report_v05.md](docs/Progress_Report_v05.md) for details

## Repository layout

```
docs/        Design documents, specs, and progress reports
ui/          Original UI mockup source (static HTML)
src/plugin/  OpenClaw TypeScript enforcement plugin
src/server/  Python FastAPI policy server + web UI
  start.sh              One-command server startup
  server.py             FastAPI application
  policy_engine.py      Rule parser and evaluator
  policy_analyzer.py    Tier 1+2 policy analysis engine
  identity.py           Identity store (token/telegram → person)
  policies.yaml         Policy rules (edit directly or via UI)
  identities.yaml       People, groups, API tokens (gitignored)
  approvals.py          Approval queue
  audit.py              Audit log
  nl_policy.py          NL policy chat (Claude-powered)
  conftest.py           Pytest fixtures (self-contained)
  test_policy_suite.py  Pytest test suite (59 tests)
  test_server.py        Legacy acceptance test harness
  test_rules.sh         Rule smoke tests (17 checks)
  static/               Web UI (served at http://localhost:8080)
```
