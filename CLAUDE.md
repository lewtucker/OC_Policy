# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**OpenClaw Policy Management App** — A Python web application for reading and writing policy rules that govern OpenClaw (OC), an autonomous agent system. The goal is to let users protect their resources from unintended actions OpenClaw might take.

The reference OpenClaw repository is at `~/Documents/dev/OpenClaw Clone` — consult it to understand how OpenClaw works before designing enforcement mechanisms.

## Core Concepts

**Security model**: Any action OpenClaw takes via shell scripts or network connections must be approved by a security guard before execution. The app enforces this through a policy language that serves as the source of truth for what is allowed or denied.

**Control mechanisms**:

- API key provisioning/revocation
- File system permission changes
- Network connection controls
- System resource access limits
- Shell and Python script execution controls

**Identity model**: Resources, services, and users all have human-readable names and immutable identities.

**Policy operations**: Users can add and delete policies. The policy language defines allow/deny rules scoped to identities and resource types.

## Open Design Questions

- How to intercept and block OpenClaw or its sub-agents from performing specific acts (requires research into OpenClaw's architecture)
- Policy language syntax and schema
- Security guard approval workflow (synchronous blocking vs. async queue)
- UI technology choice (web framework, frontend approach)

## Repository Structure

```text
docs/        Design documents and specs (markdown)
pdf/         Generated PDFs — gitignored, recreate from docs/ as needed
ui/          UI mockup source files (versioned HTML)
src/plugin/  OpenClaw TypeScript enforcement plugin (Phase 1)
src/server/  Python FastAPI policy server (Phase 1)
public/      Vercel static output — copy of latest ui/ file as index.html
```

## Nanoclaw Deployment Notes

### Updating the policy hook in nanoclaw

The policy hook lives in `~/Documents/dev/nanoclaw/container/agent-runner/src/index.ts`.

**Critical gotcha**: nanoclaw copies `container/agent-runner/src/` into a per-group cache at
`data/sessions/<group>/agent-runner-src/` on first run, and **never updates it automatically**.
The Docker container mounts this cached copy (not the original source) and recompiles it at startup.

So when you change `index.ts`, the change is silently ignored unless you:

1. Delete the stale cache: `rm -rf ~/Documents/dev/nanoclaw/data/sessions/telegram_main/agent-runner-src/`
2. Rebuild the Docker image: `cd ~/Documents/dev/nanoclaw/container && docker build -t nanoclaw-agent .`
3. Restart nanoclaw — it will re-copy from source into the cache on next container spawn

Also note: nanoclaw runs as `npx tsx src/index.ts` (from source) on the host, but the **agent** (the part that runs tool calls and the policy hook) runs inside Docker. Restarting the host process is not enough — the Docker image and cache must both be updated.

### Identity resolution

- People are defined in `src/server/identities.yaml` with `telegram_id: "tg:<numeric_id>"`
- The `tg:` prefix is part of the identity — nanoclaw sends `chatJid` as `tg:<id>`
- Per-group caches under `data/sessions/` are gitignored and must be deleted manually when the hook changes

## Key Documents

- [docs/Policy_Inst.md](docs/Policy_Inst.md) — Project brief and feature intent
- [docs/Policy_Examples.md](docs/Policy_Examples.md) — Policy language examples (to be filled in)
- [docs/OC_Policy_Control_v01.md](docs/OC_Policy_Control_v01.md) — Architecture & design (current)
- [ui/UI_Mockup_v01.html](ui/UI_Mockup_v01.html) — UI mockup source
- Live mockup: [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app)
