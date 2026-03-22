# Plan: Natural Language Policy Authoring

**Version**: v01
**Date**: 2026-03-21
**Status**: Design — not yet implemented

---

## Problem

Writing policy rules today requires knowing the schema: `tool`, `program`, `path`, `person`, `group`, `result`, `priority`. Most people think in English, not YAML. "Don't let the agent run curl" is obvious in intent but requires knowing to set `tool: Bash`, `program: curl`, `result: deny`.

The gap between what a user wants to say and what they need to type is a barrier to using the system correctly.

---

## Goal

Let the user say what they want in plain English. The system figures out the rule — or asks the minimum set of questions needed to do so.

**Examples:**

| What the user says | What the system generates |
| --- | --- |
| "Block curl" | `result: deny, match: { tool: Bash, program: curl }` |
| "Ask me before any web search" | `result: pending, match: { tool: WebSearch }` |
| "Let admins read files in /workspace" | `result: allow, match: { group: admin, path: /workspace/** }` |
| "Lew can run git without asking" | `result: allow, match: { person: lew, program: git }` |
| "Don't let the agent access the internet" | *Ambiguous — clarify: block WebSearch + WebFetch + Bash curl/wget separately?* |
| "Engineers can do their work" | *Too vague — what tools? what paths?* |

---

## Rule Schema (what the system knows)

```yaml
id: string                     # unique identifier
name: string                   # human-friendly label
description: string            # what the rule does
result: allow | deny | pending # verdict
priority: int                  # higher = evaluated first
match:
  tool: string                 # Bash, WebSearch, WebFetch, Read, Write, Edit, Glob, Grep, …
  program: string              # first word of shell command; * glob ok (Bash only)
  path: string                 # file path; * and ** glob ok (Read/Write/Edit/Glob/Grep)
  person: string               # person ID from identities.yaml
  group: string                # group name from identities.yaml
```

All match conditions are optional and ANDed together. An empty `match: {}` matches everything. A rule with a `person` or `group` condition only fires when the subject is known.

**Known tools**: Bash, WebSearch, WebFetch, Read, Write, Edit, Glob, Grep, Task, TodoWrite

---

## Interaction Design

### Happy path — intent is clear

```
User:  "Block the agent from running rm"

System: Got it. Here's the rule:

  id: deny-rm
  name: Block rm
  description: Deny all shell commands starting with rm
  result: deny
  priority: 50
  match:
    tool: Bash
    program: rm

  Shall I add this rule? [yes / edit / cancel]

User:  yes

System: ✅ Rule added.
```

### Ambiguous path — need to narrow down

```
User:  "Don't let it access the internet"

System: "Access the internet" could mean several things. Which do you want to block?

  a) Web searches (WebSearch tool)
  b) Fetching URLs (WebFetch tool)
  c) Network commands in the shell (curl, wget, nc, ssh…)
  d) All of the above

User:  d

System: That's three separate rules — the tools are different. I'll create:

  1. deny-websearch   result: deny  match: { tool: WebSearch }
  2. deny-webfetch    result: deny  match: { tool: WebFetch }
  3. deny-net-cmds    result: deny  match: { tool: Bash, program: curl }
     (and similar for wget, nc, ssh — want me to add those too?)

  Add all? [yes / edit / cancel]
```

### Too vague — ask open questions

```
User:  "Engineers should be able to do their work"

System: That's too broad for me to turn into a specific rule.
  A few questions to narrow it down:

  1. What actions are you thinking of — running shell commands, reading files,
     making web requests, something else?
  2. Should this apply to everyone in the engineering group, or specific people?
  3. Is the goal to allow something that's currently blocked, or to stop
     requiring approval for it?
```

### Needs a person or group the system doesn't know

```
User:  "Let contractors read project files"

System: I don't see a "contractors" group in identities.yaml (known groups: admin, engineering, team).

  Options:
  a) Create a "contractors" group (you'd need to add people to identities.yaml)
  b) Apply the rule to a specific person instead — who?
  c) Make the rule for everyone (no person/group condition)
```

---

## Clarifying Questions the System Asks

The system needs to ask when:

| Ambiguity | Question |
| --- | --- |
| Intent maps to multiple tools | "Do you mean WebSearch, WebFetch, or Bash commands?" |
| "Block" could be deny or pending | "Block outright, or hold for your approval?" |
| No scope given | "Apply to everyone, or a specific person or group?" |
| Unknown person/group | "I don't see X in identities.yaml — create it, pick someone else, or apply to everyone?" |
| No priority guidance | "Should this override existing rules, or sit below them?" (high / normal / low) |
| Conflict with existing rule | "This overlaps with rule `ask-websearch` (pending, priority 20). Should the new rule take precedence?" |

---

## Phase 1 — Claude Skill

Implement as a Claude Code skill: `/add-policy` (or invokable as `Skill("add-policy")`).

**How it works:**
1. User invokes the skill with a natural language description
2. The skill reads `policies.yaml` and `identities.yaml` for context (known rules, people, groups)
3. Claude maps the intent to the rule schema, asking clarifying questions if needed
4. When the rule is clear, Claude calls `POST /policies` via the server API
5. Confirms success and shows the created rule

**Why a skill first:**
- No new UI code — uses the existing conversation interface
- Claude already understands both natural language and the rule schema
- Fast to build and test; validates the interaction model before investing in UI
- Can handle edge cases through conversation rather than a rigid form

**Skill file**: `.claude/skills/add-policy.md`

```markdown
You are a policy authoring assistant for OC Policy.

Your job is to help the user create a policy rule in plain English.

## What you know

Rules have this schema:
  id, name, description, result (allow|deny|pending), priority (int), match (tool, program, path, person, group)

Known tools: Bash, WebSearch, WebFetch, Read, Write, Edit, Glob, Grep, Task, TodoWrite

## Your process

1. Read the current policies from GET /policies (to avoid duplicate IDs and detect conflicts)
2. Read the current identities from GET /identities (to validate person/group names)
3. Interpret the user's intent
4. If clear: show the proposed rule and ask for confirmation before calling POST /policies
5. If ambiguous: ask the minimum questions needed to resolve it
6. If too vague: ask open questions to understand what they're trying to protect

## Rules for generating rules

- Generate a short, memorable ID (kebab-case, e.g. deny-curl, allow-admin-files)
- Set priority relative to existing rules — deny rules generally higher than allow
- Never add a person or group condition unless the user specified one
- For "ask me first" / "require approval" intent → result: pending
- For "block" / "stop" / "prevent" intent → result: deny
- For "let" / "allow" / "can" intent → result: allow
- If the user says "without asking" or "automatically" → result: allow (not pending)

## Conflict detection

If the new rule overlaps with an existing rule at similar priority, point it out:
"This may conflict with rule X — do you want the new rule to take precedence?"
```

---

## Phase 2 — In-App Chat Panel

Add a chat panel to the Policy UI — a floating button or sidebar that opens a conversation interface. The backend is a streaming API endpoint that:

1. Accepts a natural language message
2. Calls Claude with the current policy/identity context as system prompt
3. Streams the response (questions or proposed rule)
4. When confirmed, applies the rule via the existing `/policies` API

This reuses the skill logic but embeds it in the web UI so non-technical users never need to open a terminal.

---

## Phase 3 — Proactive Suggestions

When a tool call is denied and the user is watching the audit feed, offer:

> "The agent tried to run `curl` and was blocked. Want to create a rule to allow or approve curl calls?"

Clicking the suggestion pre-fills the natural language authoring flow with context already resolved.

---

## Open Questions

1. **How opinionated should the system be about priority?** Auto-assign based on specificity (more specific = higher priority), or always ask?

2. **Should the skill apply the rule immediately or show a dry run first?** Dry run is safer for a first version.

3. **Multi-rule intents** — "Don't let the agent touch the internet" naturally maps to 4–5 rules. Should the system always batch them, or ask?

4. **Undo** — After adding a rule via natural language, offer an undo that calls `DELETE /policies/{id}`.

5. **Explain existing rules** — The same interface could work in reverse: "Why was that blocked?" → explain which rule matched and why.

---

## Files to Create

| File | Purpose |
| --- | --- |
| `.claude/skills/add-policy.md` | Phase 1 — Claude skill |
| `src/server/static/index.html` | Phase 2 — chat panel in UI |
| `src/server/nl_policy.py` | Phase 2 — backend endpoint wrapping Claude API |
