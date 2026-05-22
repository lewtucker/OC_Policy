# OC Policy — Deployment Guide

**Date**: 2026-03-22
**Author(s)**: Lew Tucker

---

## System Overview

The OC Policy system has three independently running components:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Host Machine                                                        │
│                                                                      │
│  ┌─────────────────────────┐     ┌──────────────────────────────┐   │
│  │  OC Policy Server       │     │  Nanoclaw Host Process       │   │
│  │  (Python/FastAPI)       │     │  (Node.js on host)           │   │
│  │  port 8080              │     │                              │   │
│  │                         │     │  ├── Telegram adapter        │   │
│  │  ├── policies.yaml      │     │  ├── Message router          │   │
│  │  ├── identities.yaml    │     │  ├── Credential proxy :3001  │   │
│  │  ├── audit.jsonl        │     │  └── Container spawner       │   │
│  │  └── Web UI             │     │      (docker run per msg)    │   │
│  └─────────────────────────┘     └──────────┬───────────────────┘   │
│           ▲                                  │                       │
│           │  POST /check                     │ docker run            │
│           │  GET /approvals/{id}             ▼                       │
│  ┌────────┴──────────────────────────────────────────────────────┐   │
│  │  Docker Container (nanoclaw-agent)                             │   │
│  │                                                                │   │
│  │  /app/         Agent runner (compiled TypeScript)              │   │
│  │  /workspace/                                                   │   │
│  │    group/      Per-group persistent storage (mounted)          │   │
│  │    global/     Shared CLAUDE.md (mounted, read-only)           │   │
│  │    ipc/        Inter-process communication files               │   │
│  │                                                                │   │
│  │  PreToolUse hook → POST /check → policy server                │   │
│  │  Anthropic API  → http://host.docker.internal:3001 → proxy    │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## What Lives Where

### Policy Server (this repo: `src/server/`)

Runs directly on the host as a Python process. **Not containerized.**

| File | Purpose | Persists across restarts? |
| --- | --- | --- |
| `server.py` | FastAPI application — all endpoints | N/A (code) |
| `policies.yaml` | Active policy rules | Yes (on disk) |
| `identities.yaml` | People, groups, API tokens | Yes (on disk, gitignored) |
| `audit.jsonl` | Append-only audit log | Yes (on disk) |
| `policy_engine.py` | Rule parser and evaluator | N/A (code) |
| `policy_analyzer.py` | Tier 1+2 analysis engine | N/A (code) |
| `identity.py` | Token/telegram → person resolution | N/A (code) |
| `nl_policy.py` | NL chat endpoint (Claude-powered) | N/A (code) |
| `approvals.py` | Approval queue | No (in-memory, lost on restart) |
| `static/index.html` | Web UI | N/A (code) |

### Nanoclaw Host Process (`~/Documents/dev/nanoclaw/`)

Runs on the host as a Node.js process. **Not containerized.** Manages Telegram connections, message routing, and container lifecycle.

| Component | Purpose |
| --- | --- |
| `src/index.ts` | Entry point — Telegram adapter, message routing, database |
| `src/container-runner.ts` | Spawns Docker containers via `docker run` |
| `src/credential-proxy.ts` | HTTP proxy that injects Anthropic API keys into container requests |
| `src/config.ts` | Reads `.env` for configuration |
| `store/` | SQLite database for conversation state |
| `data/sessions/` | Per-group cached data (see below) |

### Docker Container (nanoclaw-agent)

Ephemeral — spawned per message, auto-removed after idle timeout (default 30 min). The container runs the Claude Agent SDK with the policy enforcement hook.

| Path inside container | Access | Notes |
| --- | --- | --- |
| `/workspace/project` | Read-only | Nanoclaw project root |
| `/workspace/project/.env` | Read-only | Nanoclaw `.env` (tokens visible to agent) |
| `/workspace/project/store` | Read-write | SQLite database |
| `/workspace/group` | Read-write | Per-group persistent storage (`data/sessions/<group>/`) |
| `/workspace/global` | Read-write | Shared CLAUDE.md and global config |
| `/home/node/.claude` | Read-write | Per-group Claude session cache |
| `/home/node/.gmail-mcp` | Read-write | Gmail MCP credentials |
| `/workspace/ipc` | Read-write | IPC messages and close sentinel |
| `/workspace/extra/nanoclaw_share` | Read-only | Shared read-only data across groups |

**Entrypoint sequence** (`entrypoint.sh`):
1. Recompile TypeScript from `/app/src/` → `/tmp/dist/`
2. Read JSON input from stdin (prompt, session ID, group info, chatJid)
3. Run `node /tmp/dist/index.js`

---

## The Policy Hook

The policy enforcement hook is defined in `container/agent-runner/src/index.ts` inside the `createPolicyHook()` function. It is registered as a `PreToolUse` hook on the Claude Agent SDK:

```typescript
hooks: {
  PreToolUse: [{ hooks: [createPolicyHook(containerInput.chatJid)] }],
}
```

**What happens on every tool call:**

1. Agent SDK calls the hook before executing any tool (Bash, Read, Write, etc.)
2. Hook sends `POST /check` to the policy server with:
   - `tool`: the tool name (e.g. "Bash")
   - `params`: the tool input (e.g. `{"command": "rm -rf /"}`)
   - `channel_id`: the Telegram chatJid for identity resolution (e.g. `"tg:6741893378"`)
3. Policy server evaluates against rules and returns a verdict:
   - `allow` → hook returns `{}` (no block)
   - `deny` → hook returns `{ decision: 'block', reason: '...' }`
   - `pending` → hook polls `GET /approvals/{id}` every 500ms for up to 2 minutes
4. If the policy server is unreachable, the hook **fails closed** — blocks the action

**Authentication**: The container uses `OC_POLICY_AGENT_TOKEN` (injected as an env var by the host process). This token can only call `/check` and `GET /approvals/{id}` — it cannot modify policies.

---

## The Caching Gotcha

Nanoclaw copies `container/agent-runner/src/` into a per-group cache at `data/sessions/<group>/agent-runner-src/` on the **first container spawn** for that group. It **never updates this cache automatically**.

The Docker container bind-mounts this cached copy at `/app/src/` — not the original source. The entrypoint recompiles from `/app/src/` on every container start, but if the cache is stale, it recompiles stale code.

**This means**: editing `container/agent-runner/src/index.ts` has **no effect** until you clear the cache.

---

## What Can Be Changed Without Restarting

### Policy server — hot changes (no restart needed)

| Change | How | Takes effect |
| --- | --- | --- |
| Add/edit/delete policy rules | Web UI, API, or edit `policies.yaml` + `POST /policies/reload` | Immediately |
| Edit `identities.yaml` | Edit file + `POST /identities/reload` | Immediately |
| Modify `server.py` or other Python files | Saved to disk | Automatically (uvicorn `--reload` watches for changes) |
| Modify `static/index.html` | Saved to disk | Next browser refresh |

### Policy server — requires restart

| Change | Why |
| --- | --- |
| Change `OC_POLICY_AGENT_TOKEN` | Read once at module import time from env var |
| Change `OC_POLICY_ADMIN_TOKEN` | Read once at module import time from env var |
| Change `OC_POLICY_FILE` path | Read once at module import time from env var |
| Change `OC_AUDIT_FILE` path | Read once at module import time from env var |
| Change `OC_IDENTITY_FILE` path | Read once at module import time from env var |
| Change `ANTHROPIC_API_KEY` | Read once by NL chat module |
| Install new Python dependencies | Requires process restart to pick up |

### Nanoclaw — hot changes

| Change | How | Takes effect |
| --- | --- | --- |
| Change `OC_POLICY_AGENT_TOKEN` in `.env` | Edit `.env` | Next container spawn (each container reads env at startup) |
| Change `OC_POLICY_SERVER_URL` in `.env` | Edit `.env` | Next container spawn |

### Nanoclaw — requires cache clear + image rebuild

| Change | Steps required |
| --- | --- |
| Modify `container/agent-runner/src/index.ts` (the policy hook) | 1. Delete group cache 2. Rebuild Docker image 3. Restart nanoclaw |
| Modify `container/Dockerfile` | 1. Rebuild Docker image 2. Restart nanoclaw |
| Modify nanoclaw host code (`src/index.ts`, etc.) | Restart nanoclaw host process |

---

## Deployment Steps — New Installation

### Prerequisites

- macOS or Linux host
- Python ≥ 3.11
- Node.js ≥ 22
- Docker Desktop (macOS) or Docker Engine (Linux)
- An Anthropic API key or Claude OAuth token
- A Telegram bot token (optional — for chat and approval notifications)

### Step 1 — Start the Policy Server

```bash
cd ~/Documents/dev/OC_Policy/src/server
pip3 install -r requirements.txt
./start.sh
```

`start.sh` has fixed default tokens:

- **Agent token** (`OC_POLICY_AGENT_TOKEN=ltdemotoken`) — used by nanoclaw to call `/check`
- **Admin token** (`OC_POLICY_ADMIN_TOKEN=myadmintoken`) — used by the browser UI

Override them by setting the env vars before running:

```bash
OC_POLICY_AGENT_TOKEN=mytoken OC_POLICY_ADMIN_TOKEN=myadmintoken ./start.sh
```

Verify:
```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

Open http://localhost:8080 and enter the **admin token** in the UI token field.

### Step 2 — Configure Identities

Edit `src/server/identities.yaml` to add people:

```yaml
version: 1
people:
- id: lew
  name: Lew Tucker
  telegram_id: "tg:6741893378"    # Telegram numeric user ID with tg: prefix
  groups: [admin]
  api_token: "your-12-char-hex"   # generate with: python3 -c "import secrets; print(secrets.token_hex(6))"

- id: bob
  name: Bob
  telegram_id: "tg:444555666"
  groups: [engineering]
  api_token: "another-12-char-hex"
```

Reload without restarting:
```bash
curl -s -X POST http://localhost:8080/identities/reload \
  -H "Authorization: Bearer $OC_POLICY_ADMIN_TOKEN"
```

### Step 3 — Configure Policies

Edit `src/server/policies.yaml` or use the Web UI. Example starter set:

```yaml
version: 1
policies:
- id: deny-rm
  name: Block rm
  description: Block rm for all users
  result: deny
  priority: 100
  protected: true
  match:
    tool: Bash
    program: rm

- id: ask-everything
  name: Ask for approval
  description: Everything else requires human approval
  result: pending
  priority: 1
  match: {}
```

### Step 4 — Build the Nanoclaw Docker Image

```bash
cd ~/Documents/dev/nanoclaw/container
docker build -t nanoclaw-agent .
```

### Step 5 — Configure Nanoclaw Environment

Create or edit `~/Documents/dev/nanoclaw/.env`:

```bash
# Claude authentication (one of these)
ANTHROPIC_API_KEY=sk-ant-...
# OR
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...

# Telegram bot
TELEGRAM_BOT_TOKEN=123456:ABC-...

# Policy server integration
OC_POLICY_SERVER_URL=http://host.docker.internal:8080
OC_POLICY_AGENT_TOKEN=ltdemotoken    # must match OC_POLICY_AGENT_TOKEN on the policy server

# Hook toggle — set to "false" to disable enforcement without removing the token
# OC_POLICY_ENABLED=false
```

**Important:** Do not export these variables in your shell (`~/.zshrc`). Keep them in `.env` only so that toggling `OC_POLICY_ENABLED` in `.env` is the single source of truth.

### Step 6 — Start Nanoclaw

```bash
cd ~/Documents/dev/nanoclaw && npx tsx src/index.ts
```

Nanoclaw connects to Telegram and begins listening for messages. When a message arrives, it spawns a Docker container that runs the agent with the policy hook active.

To kill a running nanoclaw instance:

```bash
~/Documents/dev/nanoclaw/kill_nanoclaw.sh
```

### Step 7 — Verify End-to-End

Send a message to the Telegram bot. In the policy server logs you should see:

```
[DEBUG] /check body: tool='Bash' channel_id='tg:6741893378'
[ALLOW] tool='Bash'  subject=lew  params={'command': 'ls'}  rule='allow-admin-ls'
```

Check the Web UI — the Dashboard activity feed should show the request.

---

## Updating the Policy Hook

When you modify `container/agent-runner/src/index.ts`:

```bash
# 1. Delete the per-group cache for all groups
rm -rf ~/Documents/dev/nanoclaw/data/sessions/*/agent-runner-src/

# 2. Rebuild the Docker image
cd ~/Documents/dev/nanoclaw/container && docker build -t nanoclaw-agent .

# 3. Restart nanoclaw
~/Documents/dev/nanoclaw/kill_nanoclaw.sh
cd ~/Documents/dev/nanoclaw && npx tsx src/index.ts
```

**Why all three steps?** The cache contains a stale copy of the source. The Docker image contains a stale compiled copy. Both must be refreshed, and nanoclaw must restart to spawn containers with the new image.

### Disabling the hook without a code change

To turn off policy enforcement temporarily, set `OC_POLICY_ENABLED=false` in `nanoclaw/.env` and restart nanoclaw. No Docker rebuild needed — this is an env var check, not a code path change.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| All tool calls blocked, logs show "server unreachable" | Policy server not running, or container can't reach `host.docker.internal:8080` | Start policy server; verify `curl http://host.docker.internal:8080/health` from inside a container |
| Tool calls blocked with 401 | Agent token mismatch between nanoclaw `.env` and policy server | Ensure `OC_POLICY_AGENT_TOKEN` in `nanoclaw/.env` matches the token the policy server was started with (`ltdemotoken` by default). Do not export OC tokens in shell — keep them in `.env` only. |
| Hook changes have no effect | Stale per-group cache | Delete `data/sessions/*/agent-runner-src/` and rebuild Docker image |
| Identity not resolved (subject=None in logs) | `telegram_id` in `identities.yaml` doesn't match `chatJid` | Check that the `tg:` prefix and numeric ID match exactly |
| NL chat panel says "disabled" | `ANTHROPIC_API_KEY` not set when starting the policy server | Restart with `ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY ./start.sh` |
| Approval times out after 2 minutes | Nobody approved in the Web UI within the polling window | Approve faster, or increase the timeout in the hook (`120_000` ms) |
| Pending approvals lost on server restart | Approval queue is in-memory | Pending approvals do not survive restarts; this is a known limitation |

---

## Port Summary

| Port | Process | Purpose |
| --- | --- | --- |
| 8080 | Policy server (host) | Policy API + Web UI |
| 3001 | Credential proxy (host) | Injects Anthropic API keys into container requests |

From inside Docker containers, the host is reachable at `host.docker.internal`.
