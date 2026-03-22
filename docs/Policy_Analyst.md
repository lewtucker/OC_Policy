# OC Policy — Policy Analysis and Authoring

**Date**: 2026-03-22
**Author(s)**: Lew Tucker

---

## Overview

The system has three components that help operators understand and manage policy rules. Each serves a different purpose, runs in a different context, and uses different techniques — but they share the same underlying server API.

```
/add-policy skill (CLI)          NL Chat panel (Web UI)
        │                               │
        │ POST /policies                │ POST /chat → Claude API
        ▼                               ▼
   Policy Server ◄──── Policy Analyzer (Tier 1+2)
                        │
                        ▼
                  Policy Health panel (Web UI)
```

---

## 1. Policy Analyzer (`policy_analyzer.py`)

Pure Python, no LLM. Runs deterministic and heuristic checks against the full rule set. Produces structured findings with severity levels.

### When it runs

- **Automatically** on every policy write (`POST /policies`, `PUT /policies/{id}`) — Tier 1 findings for the affected rule are returned inline in the API response as `warnings`
- **On demand** via `GET /policies/analyze` — runs both Tier 1 and Tier 2 checks and returns all findings

### Tier 1 — Deterministic checks

Run on every policy write. Fast, algorithmic, no external data needed.

| Check | Severity | Description |
| --- | --- | --- |
| Shadow | Warning | A higher-priority rule makes a lower rule unreachable. Example: `allow Bash *` at priority 50 shadows `deny Bash curl` at priority 30. |
| Conflict | Warning | Two rules at equal priority match overlapping conditions but have different results. Outcome depends on insertion order — fragile. |
| Orphan | Warning | A rule references a person or group not in `identities.yaml`. The rule will never match. |
| Gap | Warning/Info | A catch-all `match: {}` rule with `result: allow` or `result: pending` means unmatched actions are not denied. |

### Tier 2 — Heuristic checks

Run on demand. May require audit history.

| Check | Severity | Description |
| --- | --- | --- |
| Broad allow | Info | An allow rule with only 1 match condition (very permissive scope). |
| Uncovered group | Info | A group exists in identities but no rule targets it. Members only match generic rules. |
| Unused rule | Info | A rule has never matched any request in the audit log. May be redundant or misconfigured. |

### API

```
GET /policies/analyze
Authorization: Bearer <admin-token>

Response:
{
  "findings": [
    {
      "severity": "warning",
      "check": "shadow",
      "rule_id": "allow-all-bash",
      "related_id": "deny-curl",
      "message": "Rule 'allow-all-bash' (priority 50) shadows 'deny-curl' (priority 30)..."
    }
  ],
  "summary": {
    "total": 3,
    "errors": 0,
    "warnings": 2,
    "info": 1
  }
}
```

### Where results appear

- **Policy Health panel** (Policies page in Web UI) — collapsible panel above the rule table showing badges and finding details
- **Inline warnings** in `POST /policies` and `PUT /policies` responses
- **NL Chat panel system prompt** — findings are injected so Claude can reference them when answering questions

---

## 2. NL Policy Chat Panel (Web UI)

A floating, draggable chat window in the Web UI powered by the Claude API via `nl_policy.py`. Lets operators describe rules in plain English or ask questions about the policy set.

### What it can do

- **Author rules**: "block curl for everyone", "let admins read files without asking"
- **Explain events**: "why was that last action blocked?"
- **Answer analysis questions**: "what can Bob do?", "are there any gaps?"
- **Propose rules**: returns `PROPOSED_RULE` JSON blocks with Add/Cancel buttons in the chat

### How it works

1. User types a message in the chat panel
2. Browser sends `POST /chat` with the message and the user's auth token
3. Server builds a system prompt that includes:
   - All current policy rules
   - All identities (people and groups)
   - Last 20 audit log entries
   - Current Tier 1+2 analyzer findings
4. Server calls the Claude API with this context
5. Response streams back to the browser
6. If the response contains a `PROPOSED_RULE` JSON block, the UI renders Add/Cancel buttons

### Authentication

The chat endpoint requires an admin token (per-person or bootstrap). Non-admins can ask read-only questions but cannot create or modify rules.

### Relationship to the analyzer

The chat panel does not run its own analysis. It receives the analyzer's findings in its system prompt and uses them as context. For example, if the analyzer detected a shadow, Claude can mention it when the user asks "are there any problems with my rules?"

---

## 3. `/add-policy` Skill (Claude Code CLI)

A Claude Code slash command defined in `.claude/skills/add-policy/SKILL.md`. Runs in the terminal — no browser needed. Translates natural language into policy API calls.

### Usage

```
/add-policy block the agent from running rm
/add-policy let Lew run npm without asking
/add-policy require approval for all web searches
/add-policy explain why curl was blocked
/add-policy delete deny-curl
```

### How it works

1. Fetches live context from the running policy server via curl:
   - `GET /policies` — current rules
   - `GET /identities` — known people and groups
   - `GET /audit?limit=20` (explain mode only)
2. Interprets the natural language intent:
   - Maps verbs to results (block → deny, let → allow, require approval → pending)
   - Maps nouns to tools and programs (curl → Bash + program: curl)
   - Maps names to people/groups from identities
   - Assigns priority based on specificity
   - Generates a kebab-case rule ID
3. Shows the proposed rule in YAML and asks for confirmation
4. On confirmation, POSTs to the policy server
5. Reports success and offers undo

### Modes

| Mode | Trigger | What it does |
| --- | --- | --- |
| Create | Default — any rule description | Proposes a new rule, confirms, applies |
| Explain | "explain", "why was X blocked?" | Fetches audit + policies, walks through rule evaluation |
| Delete | "delete", "remove" | Confirms, then DELETEs the rule |
| Multi-rule | "block all internet access" | Proposes multiple rules as a batch |

### Relationship to the analyzer

The `/add-policy` skill does **not** call the analyzer today. It reads rules and identities to check for conflicts manually (e.g., duplicate IDs, priority collisions), but it does not run shadow/orphan/gap detection. This is a potential improvement — it could call `GET /policies/analyze` after creating a rule and surface any new warnings.

---

## Comparison

| | Policy Analyzer | NL Chat Panel | `/add-policy` Skill |
| --- | --- | --- | --- |
| **Runs in** | Policy server (Python) | Web UI + server | Claude Code terminal |
| **Uses LLM** | No | Yes (Claude API) | Yes (Claude Code) |
| **Primary purpose** | Detect rule problems | Author rules + answer questions | Author rules from CLI |
| **Reads rules** | Yes | Yes (via system prompt) | Yes (via API) |
| **Reads audit** | Yes (Tier 2) | Yes (via system prompt) | Yes (explain mode) |
| **Reads identities** | Yes | Yes (via system prompt) | Yes (via API) |
| **Modifies rules** | No | Yes (proposes + applies) | Yes (proposes + applies) |
| **Requires browser** | No (API) / Yes (Health panel) | Yes | No |
| **Requires server** | Runs inside it | Yes | Yes |
| **Requires Claude API key** | No | Yes | No (uses Claude Code) |

---

## Tier 3 — LLM-Assisted Analysis (planned)

The next phase extends the NL chat panel with richer policy reasoning:

- "Summarize what each group can and cannot do"
- "What would happen if Bob tried to run `curl https://internal-api/secrets`? Walk through every rule."
- "Are there any ways engineering could access financial data?"
- "Suggest a minimal rule set that achieves the same effective policy"
- "Compare today's rules to last week's — what changed?"

This does not require a new component — it extends the chat panel's system prompt with expanded reasoning instructions and potentially deeper audit history. The analyzer's Tier 1+2 findings are already in the prompt; Tier 3 adds richer questions that Claude reasons about using that context.

---

## Files

| File | Component |
| --- | --- |
| `src/server/policy_analyzer.py` | Policy Analyzer — Tier 1+2 checks |
| `src/server/nl_policy.py` | NL Chat Panel — Claude API endpoint |
| `src/server/server.py` | `GET /policies/analyze`, inline warnings on CRUD |
| `src/server/static/index.html` | Policy Health panel UI, Chat panel UI |
| `.claude/skills/add-policy/SKILL.md` | `/add-policy` Claude Code skill |
