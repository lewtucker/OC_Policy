# Controlling Open Claw Agents Prototype

**Date**: 2026-03-21
**Status**: Discussion draft — not yet implemented
**Context**: Written after Phase 1 (hook integration with Nanoclaw) is working end-to-end.

---

## Objective

Autonomous AI agents like OpenClaw can take consequential actions — modifying files, running commands, making network calls — without necessarily checking whether those actions are safe or intended. The goal of this project is to build a practical control layer that sits between the agent and the resources it can affect, enforcing a set of human-authored policies before any action is permitted to execute.

A working prototype demonstrates the core enforcement loop: every tool call the agent attempts is intercepted by a policy hook, evaluated against a set of rules, and either allowed, blocked outright, or held for explicit human approval. This document examines the next layer of that problem — *who* is acting — and proposes how identity, actor types, and plugin trust should be modeled as the system matures beyond the prototype stage.

---

## What's Working Today

The enforcement chain is real and running:

1. Nanoclaw receives a message via Telegram
2. It spawns a container running the Claude Agent SDK
3. Before every tool call, a `PreToolUse` hook fires
4. The hook POSTs `{ tool, params }` to the OC Policy Server
5. The server evaluates the request against `policies.yaml`
6. If `pending`, an approval card appears in the UI
7. The hook polls until resolved, then allows or blocks

The current policy language matches on `tool` and `params` fields (program name, file path). There is no concept of *who* is making the request. Every tool call looks identical to the policy server regardless of whether a human asked for it or an autonomous subagent decided to do it on its own.

That is the central gap this document addresses.

---

## Two Dimensions of Identity

Expanding the policy system requires understanding that "who is acting" has two completely different meanings depending on how you use Nanoclaw:

### Dimension 1 — Autonomous vs. Human-Initiated Actions (Single User)

For a single user running Nanoclaw as a personal assistant, the meaningful identities are not people — they are **actors within the system**:

| Subject | What it is | Example |
| --- | --- | --- |
| `session:main` | You, talking directly to Nanoclaw | "Search for the weather" |
| `agent:subagent` | A subagent Nanoclaw spawned to do work | Nanoclaw delegates research to a sub-agent |
| `task:scheduled` | An automated task, no human present | A nightly report that runs at 2am |
| `plugin:<source>:<name>` | A plugin acting on its own | A research plugin fetching URLs |

The security concern here is not "the wrong human is asking" — it's **"the agent is doing something you didn't intend when you weren't watching."** A scheduled task that spontaneously starts browsing the web, or a subagent that deletes files while solving a problem, are realistic failure modes even without any adversarial intent.

Example policies for this model:

```yaml
# Scheduled tasks: hard limits, no approval path
- id: scheduled-no-web
  result: deny
  priority: 50
  match:
    tool: WebSearch
    subject: task:scheduled

- id: scheduled-no-delete
  result: deny
  priority: 50
  match:
    tool: Bash
    program: rm
    subject: task:scheduled

# Subagents: approval required for internet and writes
- id: subagent-ask-web
  result: pending
  priority: 40
  match:
    tool: WebSearch
    subject: agent:subagent

- id: subagent-no-delete
  result: deny
  priority: 40
  match:
    tool: Bash
    program: rm
    subject: agent:subagent

# Human session: soft speed bump on destructive ops
- id: session-ask-delete
  result: pending
  priority: 30
  match:
    tool: Bash
    program: rm
    subject: session:main

- id: allow-all
  result: allow
  priority: 0
  match: {}
```

**Critical observation**: The difference between `deny` and `pending` matters significantly here. Scheduled tasks get hard denials because there is no one present to approve. Subagents get `pending` because you may want to allow a specific search in the moment. Your own session gets `pending` on destructive operations as a speed bump, not a wall.

---

### Dimension 2 — Multi-User Team Identity

When a team shares a single Nanoclaw instance, the Telegram `chatJid` already uniquely identifies each team member. The identity mapping would live in a registry:

```yaml
# identities.yaml
identities:
  - name: alice
    telegram_id: "tg:111222333"
    roles: [admin, developer]
  - name: bob
    telegram_id: "tg:444555666"
    roles: [developer]
  - name: jane
    telegram_id: "tg:777888999"
    roles: [readonly]
```

Policies match on role, not individual name, so adding a new team member is just adding them to the registry:

```yaml
- id: only-admins-push
  description: Only admins can push code
  result: deny
  priority: 50
  match:
    tool: Bash
    program: git
    role: developer       # developers blocked; admins fall through to allow-all

- id: readonly-no-writes
  description: Readonly users cannot write files
  result: deny
  priority: 50
  match:
    tool: Write
    role: readonly
```

---

## Plugin Trust

This is the harder problem and deserves careful treatment.

### What "plugin" means in Nanoclaw

In Nanoclaw, a "plugin" is not a formally defined unit. It can be any of:

- An npm package installed into the container
- A skill file placed in `.claude/skills/`
- An MCP server added to the agent configuration
- A CLAUDE.md instruction that changes agent behavior
- A shell script that the agent is told to run

These are structurally different and require different control points. There is no unified "plugin install" action to intercept — it is a collection of file writes, npm installs, and config edits.

### Two separate control points

**Installation time** — who can add a plugin to the system:

```yaml
- id: only-admins-install-npm
  description: Only admins can install npm packages
  result: deny
  priority: 80
  match:
    tool: Bash
    program: npm
    role: developer

- id: only-admins-write-skills
  description: Only admins can add skill files
  result: deny
  priority: 80
  match:
    tool: Write
    path: /home/node/.claude/skills/*
    role: developer
```

**Runtime** — what a plugin is allowed to do once installed:

A plugin that is running acts as its own subject. If a plugin has a declared identity, policies can scope what it is allowed to do:

```yaml
- id: deny-all-plugin-actors
  description: Block all plugin-originated actions by default
  result: deny
  priority: 70
  match:
    subject: plugin:*

- id: allow-trusted-plugin-web
  description: Trusted company plugins can search the web
  result: allow
  priority: 80
  match:
    tool: WebSearch
    subject: plugin:company_xyz:*
```

### The hard problem: identity cannot be self-declared

This is where the design gets genuinely difficult. If a plugin is allowed to declare its own identity (`plugin:company_xyz:research-bot`), then any plugin can claim to be from `company_xyz`. The policy is only meaningful if the identity claim is verified by a party the policy server trusts — not by the plugin itself.

This is a trust chain problem similar to code signing. Possible approaches, from weakest to strongest:

1. **Admin allowlist**: An admin explicitly adds a plugin to an approved list by name before it runs. The policy server checks the list. The plugin cannot self-register. This is weak (name collisions, no content verification) but practical.

2. **Content hash**: The plugin's source is hashed at install time. The policy server holds a registry of `hash → trusted identity`. A plugin's identity is the hash of its content, not its claimed name. Stronger but operationally harder.

3. **Signed manifests**: Plugins ship with a manifest signed by a known key (e.g., company_xyz's private key). The policy server verifies the signature. This is how macOS app notarization works. Strong, but requires a PKI.

For a practical first implementation, option 1 (admin allowlist) is the right starting point.

---

## Critical Problems with the Current Design

### 1. The subject is set inside the container — the agent can lie

The most significant architectural issue: in the current design, the hook runs inside the container where the agent runs. The `subject` field would be read from an environment variable set by the container-runner. But the agent itself has access to that environment and, more importantly, could modify the hook code (the `agent-runner-src` directory is a writable bind mount).

A sufficiently motivated or compromised agent could modify its own hook to always report `subject: session:main` and bypass all subagent restrictions.

**The fix**: The subject must be stamped by the Nanoclaw host process and included in a signed or integrity-protected field that the container cannot forge. One approach: the host generates a short-lived signed token containing the subject, and the policy server verifies the signature. The container only sees the token, not the signing key.

This is not a theoretical concern. It is the central security assumption the entire system rests on.

### 2. Fail-closed breaks team workflows

The hook currently blocks all tool calls if the policy server is unreachable. For a single user this is acceptable — Nanoclaw just fails. For a team sharing the same instance, a policy server outage takes down everyone simultaneously.

This means the policy server needs to be treated as critical infrastructure: high availability, monitoring, restart-on-crash. The current in-process Python server is not designed for this. At team scale, the policy server should be a separate, always-on service.

### 3. Approvals don't route to the right person

Currently all pending approvals go to a single queue visible to anyone with the UI token. In a team context, Alice's request should notify Alice's manager, not Bob. The approval UI needs notification routing — at minimum, a webhook or Telegram message to the right person when their request is pending.

### 4. The policy language has no time or rate dimension

The current `match` system handles `tool`, `program`, `path`, and (planned) `subject`. It cannot express:

- "Subagents can only search during business hours"
- "Each developer can make 20 web searches per day"
- "Allow git push, but only to branches named `dev/*`"

These require `when:` clauses (time-of-day, rate limits) and richer parameter matching (regex, not just glob). Adding these is incremental but important before the system is used for real team policies.

### 5. The `allow-all` catch-all inverts the security model

The current `policies.yaml` has an `allow-all` rule at priority 0. This means the default is *allow* — anything not explicitly denied gets through. For a personal assistant this is pragmatic. For a team security policy this is wrong. Teams should default to *deny* and explicitly allow what is needed.

These are fundamentally different operational philosophies and the system should make the choice explicit, not hide it in a catch-all rule.

### 6. Policy conflicts are silent

If two rules at the same priority both match a request, the first one wins silently. In a team-managed policy file with many contributors, this is a source of bugs. The system should detect and surface conflicts — at minimum in the UI, ideally blocking a policy file that contains them.

---

## Recommended Build Order

Given the above, here is a pragmatic sequence:

**Phase 3a — Autonomous actor identities (single user, no team)**
Implement `isScheduledTask` and `isMain` → subject mapping in the container-runner. Wire the subject through the hook and policy engine. This gives the most security value for the least complexity and does not require solving the identity-verification problem (there is only one human).

**Phase 3b — Approval routing**
Add a notification mechanism (Telegram message back to the requesting group) when an approval is pending. Currently the agent just hangs silently. The user should know why Nanoclaw stopped and where to go to approve it.

**Phase 3c — Admin allowlist for plugins**
Define a plugin registry (a simple YAML list of approved plugin names/hashes). The policy server checks the registry when a plugin-originated action is evaluated. No signing infrastructure needed yet.

**Phase 4a — Multi-user team identity**
Add `identities.yaml` with Telegram ID → name/role mappings. Wire the chatJid → role resolution into the container-runner → hook → policy server chain. Tackle the subject-forgery problem with a host-signed token before deploying to real teams.

**Phase 4b — Richer policy language**
Add `when:` clauses, rate limiting, and regex parameter matching. This is the point where the policy server starts to look like a real authorization system rather than a simple rule evaluator.

---

## Open Questions

1. **Who administers policies in a team?** Is it a single admin, or do team leads manage policies for their own groups? What is the change control process for modifying `policies.yaml`?

2. **How are approval decisions audited?** Currently approvals are in-memory and lost on restart (the audit log persists, but approval resolution reasons are not yet linked to audit entries). For a team, who approved what and when needs to be permanent and attributable.

3. **What is the right granularity for plugin identity?** Is `plugin:company_xyz:*` meaningful, or does it need to be per-version (`plugin:company_xyz:research-bot:v1.2`)?

4. **How does the policy system handle the Claude Agent SDK's own tool-calling behavior?** The SDK itself may make HTTP calls or write temporary files as part of normal operation. These should be excluded from policy evaluation, but the current system has no way to distinguish SDK-internal operations from agent-directed ones.

5. **Should policy violations be visible to the agent?** Currently when a tool is blocked, the agent sees a generic error. Should it see the policy reason ("blocked: subagents cannot delete files") or a minimal error ("operation not permitted")? Seeing the reason helps debugging but could also help a compromised agent craft requests that evade the policy.
