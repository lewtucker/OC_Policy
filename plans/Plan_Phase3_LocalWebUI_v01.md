# Plan: Phase 3 — Local Web UI

**Version**: v01
**Date**: 2026-03-19
**Status**: Ready to build
**Reference**: [docs/OC_Policy_Control_v01.md](../docs/OC_Policy_Control_v01.md) — Phase 3

---

## Objective

Replace the static Vercel mockup with a real local web app served directly by FastAPI.
The UI runs on the same host as the policy server (e.g. `http://localhost:8080/`),
making fetch calls to the same origin — no CORS, no external deployment.

---

## Approach

- FastAPI mounts `src/server/static/` at `/` via `StaticFiles`
- Single `index.html` with inline CSS and vanilla JS — no build step, no framework
- On first load, user is prompted for their `OC_POLICY_AGENT_TOKEN` — stored in `localStorage`
- All five screens from the mockup are retained; four are wired to live data

---

## Screen → API Mapping

| Screen | Live data | Endpoints |
| --- | --- | --- |
| Dashboard | Stat cards, policy summary, activity feed | `GET /health`, `GET /policies`, `GET /audit?limit=20` |
| Approvals | Pending cards, approve/deny actions | `GET /approvals?pending_only=true`, `POST /approvals/{id}` |
| Policies | Rule table, add rule, delete rule | `GET /policies`, `POST /policies`, `DELETE /policies/{id}` |
| Plugins | Static placeholder | — |
| Identities | Static placeholder | — |

---

## Key Behaviours

- **Token prompt** — modal on first visit; stored in `localStorage`; settings icon to change
- **Auto-refresh** — Approvals polls every 5s; Dashboard activity feed polls every 10s
- **Approval badge** — sidebar badge updates to reflect pending count
- **Optimistic UI** — approve/deny cards animate out immediately; errors restore them
- **Error states** — server unreachable or bad token shows inline banner

---

## Files

| File | Change |
| --- | --- |
| `src/server/static/index.html` | New — full web app (HTML + CSS + JS) |
| `src/server/server.py` | Mount `StaticFiles("/", static_dir)` |
