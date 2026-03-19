# OC Policy

A policy management system for [OpenClaw](https://openclaw.dev) — an autonomous AI agent. OC Policy lets you define rules that govern what actions OpenClaw is allowed to take, enforced before execution rather than after the fact.

## What it does

OpenClaw can read files, run shell commands, make network requests, and call external APIs on your behalf. OC Policy intercepts every tool call and checks it against a set of rules before it executes. If no rule permits the action, it is blocked.

Rules are written in a human-readable policy language and managed through a web UI. Policies are attribute-based (e.g. "allow git commands in project directories") rather than tied to specific users or sessions, so they remain stable as your team and environment change.

## Architecture

```
OpenClaw
  └── TypeScript enforcement plugin
        └── before_tool_call hook → POST /check
              └── Python policy server (FastAPI)
                    └── Policy rules (YAML) + Web UI
```

Three layers:

1. **Enforcement plugin** — TypeScript plugin inside OpenClaw that intercepts every tool call and asks the Policy Server for a verdict. Fails closed: if the server is unreachable, the call is blocked.
2. **Policy server** — Python/FastAPI service that evaluates incoming tool calls against stored rules and returns `allow`, `deny`, or `pending` (awaiting human approval).
3. **Web UI** — Dashboard for managing policies, reviewing pending approvals, auditing activity, and controlling plugin permissions.

See [docs/OC_Policy_Control_v01.md](docs/OC_Policy_Control_v01.md) for the full architecture and design.

## Status

Work in progress. Phase 1 (enforcement plugin + minimal policy server) is being built now.

- Live UI mockup: [oc-policy-ui.vercel.app](https://oc-policy-ui.vercel.app)
- Phase 1 plan: [plans/Plan_Phase1_EnforcementPlugin_v01.md](plans/Plan_Phase1_EnforcementPlugin_v01.md)

## Repository layout

```
docs/        Design documents and specs
plans/       Implementation plans by phase
ui/          UI mockup source files
src/plugin/  OpenClaw TypeScript enforcement plugin
src/server/  Python FastAPI policy server
public/      Vercel static site output
```
