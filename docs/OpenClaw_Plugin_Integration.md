# OC Policy — OpenClaw Plugin Integration

**Date**: 2026-03-22
**Author(s)**: Lew Tucker

---

## Overview

The OC Policy enforcement plugin intercepts every tool call that OpenClaw makes and checks it against the OC Policy Server before execution. It uses OpenClaw's `before_tool_call` plugin hook to return allow/deny/pending verdicts, with optional polling for human approval.

This document covers:
- How the OpenClaw plugin system works
- What we built and where it lives
- How the kyle-mac deployment is wired together
- How to update, troubleshoot, and extend the integration

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  kyle-mac (OpenClaw host)                                                  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Docker: openclaw-gateway                                            │  │
│  │                                                                      │  │
│  │  /app/                   OpenClaw application (built into image)     │  │
│  │  /home/node/.openclaw/   ← bind-mount from ~/OC2/workspace/data/    │  │
│  │    ├── openclaw.json     Config (plugins, channels, models)         │  │
│  │    ├── extensions/                                                   │  │
│  │    │   └── oc-policy/    ← OC Policy enforcement plugin             │  │
│  │    │       ├── openclaw.plugin.json                                  │  │
│  │    │       ├── package.json                                          │  │
│  │    │       └── src/index.ts                                          │  │
│  │    ├── skills/           agentmail, agent-browser                    │  │
│  │    └── workspace/        ← bind-mount from ~/OC2/workspace/workspace│  │
│  │                                                                      │  │
│  │  Agent loop:                                                         │  │
│  │    message in → context assembly → model inference → tool call       │  │
│  │                                                         │            │  │
│  │                                          before_tool_call hook       │  │
│  │                                                         │            │  │
│  │                                                    POST /check       │  │
│  └─────────────────────────────────────────────────────┬────────────────┘  │
│                                                        │                   │
│                                            Tailscale network               │
└────────────────────────────────────────────────────────┼───────────────────┘
                                                         │
┌────────────────────────────────────────────────────────┼───────────────────┐
│  lew-mac-2023 (Policy Server host)                     │                   │
│                                                        ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Tailscale Serve                                                     │  │
│  │  https://lew-mac-2023.tail9284d9.ts.net → localhost:8080             │  │
│  └──────────────────────────────────────┬───────────────────────────────┘  │
│                                         │                                  │
│  ┌──────────────────────────────────────▼───────────────────────────────┐  │
│  │  OC Policy Server (Python/FastAPI, port 8080)                        │  │
│  │  ├── policies.yaml       Policy rules                                │  │
│  │  ├── identities.yaml     People, groups, tokens                      │  │
│  │  ├── audit.jsonl         Audit log                                   │  │
│  │  └── Web UI              http://localhost:8080                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## The OpenClaw Plugin System

OpenClaw has two extension mechanisms — **skills** and **plugins**. They serve different purposes:

| | Skills | Plugins |
| --- | --- | --- |
| **What they are** | Markdown + scripts | TypeScript modules |
| **Where they live** | `~/.openclaw/skills/` | `~/.openclaw/extensions/` |
| **How they run** | As subprocesses | In-process with the gateway |
| **Can block tool calls** | No | Yes (via `before_tool_call` hook) |
| **Discovery** | Scanned from skills directory | Scanned from extensions + `plugins.load.paths` |
| **Need a manifest** | `SKILL.md` with frontmatter | `openclaw.plugin.json` with JSON Schema |
| **Examples on kyle-mac** | agentmail, agent-browser | device-pair (built-in), oc-policy (ours) |

We need a **plugin** because only plugins can register `before_tool_call` hooks that intercept and block tool execution.

### Plugin discovery order

1. `plugins.load.paths` in `openclaw.json`
2. `<workspace>/.openclaw/extensions/*.ts` or `*/index.ts`
3. `~/.openclaw/extensions/*.ts` or `*/index.ts`
4. Bundled extensions (shipped with the OpenClaw image)

### Plugin lifecycle

1. OpenClaw discovers candidate plugin roots and reads `openclaw.plugin.json`
2. Config is validated against the manifest's JSON Schema (without executing code)
3. Enabled plugins are loaded via **jiti** (runtime TypeScript transpiler — no build step)
4. Each plugin's `register(api)` function is called
5. Plugins register hooks, tools, commands, etc. into a central registry

### Key API: `before_tool_call` hook

```typescript
api.on("before_tool_call", async (event, ctx) => {
  // event.toolName — "exec", "browser", "write_file", etc.
  // event.params   — tool parameters

  // Return nothing to allow:
  return;

  // Return block to deny:
  return { block: true, blockReason: "Reason shown to agent" };

  // Return modified params to allow with changes:
  return { params: { ...event.params, modified: true } };
}, { priority: 100 });
```

The hook runs sequentially across all registered handlers. Results are merged: `block` and `blockReason` from any handler can stop the tool call. Higher priority runs first.

---

## What We Built

### Plugin files

```
src/plugin/
├── openclaw.plugin.json    # Manifest — id, configSchema, uiHints
├── package.json            # Package metadata with openclaw.extensions entry
├── tsconfig.json           # TypeScript config (IDE/reference only — jiti handles transpilation)
└── src/
    └── index.ts            # Plugin code
```

### How the plugin works

1. On gateway startup, `register(api)` reads config from `plugins.entries.oc-policy.config` (or `OC_POLICY_SERVER_URL` / `OC_POLICY_AGENT_TOKEN` env vars)
2. Registers a `before_tool_call` hook at priority 100
3. On every tool call:
   - Sends `POST /check` to the policy server with `{ tool, params, channel_id }`
   - If verdict is `allow` → returns nothing (tool proceeds)
   - If verdict is `deny` → returns `{ block: true, blockReason }` (tool blocked)
   - If verdict is `pending` → polls `GET /approvals/{id}` every 500ms for up to 2 minutes
   - If the server is unreachable → **fails closed** (blocks the tool call)

### Configuration

The plugin accepts config either via `openclaw.json` or environment variables:

```json5
// In openclaw.json → plugins.entries:
'oc-policy': {
  enabled: true,
  config: {
    policyServerUrl: 'https://lew-mac-2023.tail9284d9.ts.net',
    agentToken: 'ltdemotoken',
    approvalTimeoutMs: 120000,   // optional, default 2 minutes
    channelId: null,             // optional, for identity resolution
  },
},
```

Or via environment variables:
- `OC_POLICY_SERVER_URL`
- `OC_POLICY_AGENT_TOKEN`

---

## The kyle-mac Deployment

### Directory structure

kyle-mac has a two-layer workspace layout:

| Path | What it is | Container path |
| --- | --- | --- |
| `~/OC2/workspace/` | Deployment repo — docker-compose.yml, .env, up.sh, scripts | N/A (host only) |
| `~/OC2/workspace/data/` | OpenClaw data — config, devices, cron, logs, extensions | `/home/node/.openclaw/` |
| `~/OC2/workspace/workspace/` | Agent workspace — SOUL.md, MEMORY.md, scripts, .openclaw/ | `/home/node/.openclaw/workspace/` |
| `~/OC2/workspace/skills/` | Custom skills — agentmail, agent-browser | `/home/node/.openclaw/skills/` |

The outer `workspace/` is the deployment directory (confusingly also named "workspace"). The inner `workspace/workspace/` is the OpenClaw agent's working directory. The container only sees the inner one.

### What we deployed

| File on host | Container path |
| --- | --- |
| `~/OC2/workspace/data/extensions/oc-policy/openclaw.plugin.json` | `/home/node/.openclaw/extensions/oc-policy/openclaw.plugin.json` |
| `~/OC2/workspace/data/extensions/oc-policy/package.json` | `/home/node/.openclaw/extensions/oc-policy/package.json` |
| `~/OC2/workspace/data/extensions/oc-policy/src/index.ts` | `/home/node/.openclaw/extensions/oc-policy/src/index.ts` |

Config entry added to `~/OC2/workspace/data/openclaw.json` under `plugins.entries`.

### Network path

```
Container (kyle-mac)
  → fetch("https://lew-mac-2023.tail9284d9.ts.net/check")
  → Tailscale network (encrypted, auto-TLS)
  → Tailscale Serve on lew-mac-2023 (port 443 → localhost:8080)
  → OC Policy Server (FastAPI on port 8080)
```

Tailscale Serve was enabled with:
```bash
tailscale serve --bg 8080
```

This exposes `localhost:8080` as `https://lew-mac-2023.tail9284d9.ts.net/` with automatic TLS.

### Docker setup

OpenClaw runs as a single Docker container (`openclaw-gateway`) managed by docker-compose. Secrets are injected via 1Password (`op run`). The startup script is `~/OC2/workspace/up.sh`.

```bash
# Start (secrets injected from 1Password)
cd ~/OC2/workspace && ./up.sh

# Restart gateway (after config or plugin changes)
cd ~/OC2/workspace && docker compose restart openclaw-gateway

# View logs
cd ~/OC2/workspace && docker compose logs -f openclaw-gateway

# Check plugin loading
docker logs openclaw-gateway --tail 50 2>&1 | grep oc-policy
```

---

## Updating the Plugin

### Change plugin code

```bash
# 1. Edit src/plugin/src/index.ts locally

# 2. Copy to kyle-mac
scp -r -i ~/.ssh/id_ed255519 src/plugin/* kylejones@kyle-mac:~/OC2/workspace/data/extensions/oc-policy/

# 3. Restart the gateway
ssh -i ~/.ssh/id_ed255519 kylejones@kyle-mac \
  "cd ~/OC2/workspace && PATH=/opt/homebrew/bin:\$PATH docker compose restart openclaw-gateway"
```

No build step needed — jiti re-transpiles TypeScript on every gateway start.

### Change plugin config

Edit `~/OC2/workspace/data/openclaw.json` on kyle-mac, then restart the gateway. Config changes require a restart.

### Change policy rules

Policy rules can be changed without restarting anything — edit via the Web UI at `http://localhost:8080` or the API. The plugin calls `/check` on every tool call, so rule changes take effect immediately.

---

## SSH Access to kyle-mac

```bash
ssh -i ~/.ssh/id_ed255519 kylejones@kyle-mac
```

Docker commands need the full PATH:
```bash
export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH
docker ps
docker logs openclaw-gateway --tail 50
```

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| All tool calls blocked, logs show "unreachable" | Policy server not running, or Tailscale Serve stopped | Start policy server (`cd src/server && ./start.sh`), restart Tailscale Serve (`tailscale serve --bg 8080`) |
| Plugin not loaded (no `[oc-policy]` in logs) | Plugin not in extensions dir, or not enabled in config | Check `~/OC2/workspace/data/extensions/oc-policy/` exists and `openclaw.json` has `enabled: true` |
| "plugin id mismatch" warning | `package.json` name doesn't match `openclaw.plugin.json` id | Set `"name": "oc-policy"` in both |
| 401 from policy server | Agent token mismatch | Ensure `agentToken` in openclaw.json matches `OC_POLICY_AGENT_TOKEN` on the policy server |
| Identity not resolved (subject=None in audit) | No `channel_id` in plugin config, and agent token is generic | Set `channelId` in config or use per-person tokens in `identities.yaml` |
| Tool calls not showing in policy server audit | Plugin loaded but hook not firing | Check gateway logs for errors; verify with `docker exec openclaw-gateway curl -sk https://lew-mac-2023.tail9284d9.ts.net/health` |
| Gateway won't start after config change | Syntax error in openclaw.json | Restore from backup (`~/OC2/workspace/data/openclaw.json.bak`) |

---

## Comparison: Nanoclaw vs OpenClaw Integration

The policy server now integrates with two different agent runtimes:

| | Nanoclaw (earlier integration) | OpenClaw (this integration) |
| --- | --- | --- |
| **Hook mechanism** | Claude Agent SDK `PreToolUse` hook | OpenClaw `before_tool_call` plugin hook |
| **Hook location** | `container/agent-runner/src/index.ts` | `data/extensions/oc-policy/src/index.ts` |
| **Runtime** | Compiled TypeScript in Docker | jiti-transpiled TypeScript in Docker |
| **Identity resolution** | `chatJid` from Telegram (`tg:<id>`) | Plugin config `channelId` or agent token |
| **Policy server URL** | `host.docker.internal:8080` | Tailscale FQDN (cross-machine) |
| **Update process** | Delete cache + rebuild image + restart | Copy files + restart gateway |
| **Container lifecycle** | Ephemeral (one per message) | Persistent (long-running gateway) |
| **Caching gotcha** | Per-group agent-runner-src cache | None (jiti re-transpiles on start) |

---

## Identity Mapping (TODO)

The current deployment uses the generic agent token (`ltdemotoken`) which identifies all requests as coming from the agent, not from a specific person. To enable per-person policy rules:

1. Map OpenClaw's Telegram sender IDs to `channel_id` values in `/check` requests
2. Add those IDs to `identities.yaml` on the policy server
3. Configure the plugin with the appropriate `channelId` or implement dynamic identity resolution from the hook context

The `before_tool_call` context object includes `agentId` and `sessionKey` which could be used for richer identity mapping.

---

## Files

| File | Purpose |
| --- | --- |
| `src/plugin/src/index.ts` | Plugin source — `before_tool_call` hook implementation |
| `src/plugin/openclaw.plugin.json` | Plugin manifest — id, config schema, UI hints |
| `src/plugin/package.json` | Package metadata with `openclaw.extensions` entry point |
| `src/plugin/tsconfig.json` | TypeScript config (reference only) |
| `docs/Deployment.md` | Nanoclaw deployment guide (the other integration) |
