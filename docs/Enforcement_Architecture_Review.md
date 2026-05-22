# OC Policy Enforcement Architecture Review

**Date:** 2024-03-24
**Purpose:** Assess the current plugin-based enforcement model, identify gaps, and evaluate whether skills could serve as an alternative or complement.

-

## 1. How It Works Today

Your understanding is correct. The system has three components:

1. **Policy Server** (Python/FastAPI) — runs as a standalone process, manages rules in `policies.yaml`, resolves identities, evaluates policy, manages an approval queue, and exposes a REST API.

2. **Enforcement Plugin** (`src/plugin/`) — a TypeScript module that OpenClaw loads. It registers a `before_tool_call` hook so that every time the agent tries to use a tool (Bash, Read, Write, Edit, etc.), the plugin fires a `POST /check` to the policy server with the tool name, parameters, and channel ID.

3. **Nanoclaw Hook** (`~/Documents/dev/nanoclaw/container/agent-runner/src/index.ts`) — a `PreToolUse` hook hardcoded into the nanoclaw container runner. Same logic as the plugin: calls `/check`, polls `/approvals/{id}` if pending, blocks on deny or timeout.

The flow is:

```
Agent wants to use a tool
  → PreToolUse hook fires
    → POST /check (tool, params, channel_id)
      → Policy server authenticates agent token
      → Resolves subject from channel_id (e.g., Telegram user)
      → Evaluates rules by priority (first match wins)
      → Returns verdict: allow | deny | pending
    → Plugin acts on verdict:
        allow  → tool executes
        deny   → tool blocked, reason returned to agent
        pending → poll /approvals/{id} until resolved or timeout (120s)
```

**Key design properties:**
- **Fail-closed** — network errors or unexpected responses block the action
- **Default-deny** — if no rule matches, the action is denied
- **Separation of concerns** — the policy server is external to the agent, so the agent cannot modify its own policy

---

## 2. What Gets Intercepted (And What Doesn't)

### What the current system catches

Every **tool call** the agent makes: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, etc. The policy engine can match on:
- Tool name
- Program name (first word of a Bash command)
- File path (with glob patterns)
- Agent identity
- Person identity and group membership

### What the current system does NOT catch

#### a) Subagent spawning

When Claude Code spawns a subagent (the `Agent` tool), a new agent subprocess is created. **There is no `PreSubagentStart` hook in Claude Code.** The hooks that exist are:

- `SubagentStart` — fires **after** the subagent is created (can inject context, cannot block)
- `SubagentStop` — fires when the subagent finishes (can force it to continue, but the work is already done)

**This is a gap.** A subagent inherits the same hook configuration as its parent, so its individual tool calls will still be checked by the policy server. But you cannot prevent a subagent from being spawned in the first place. An agent could spawn dozens of subagents as a resource-exhaustion vector, or spawn them to explore approaches before making tool calls you do control.

**Mitigation:** The `PreToolUse` hook does fire for the `Agent` tool itself (the parent's tool call to spawn it), so you could add a policy rule matching `tool: Agent` to gate subagent creation. Each subagent's own tool calls would still be individually checked because the hook configuration propagates.

#### b) Slash commands / Skills

Skills are invoked via the `Skill` tool. The `PreToolUse` hook fires with `tool_name: "Skill"` and `tool_input: { skill: "name", args: "..." }`. So you **can** intercept skill invocations through the existing plugin — you'd add policy rules matching `tool: Skill` and potentially inspect the `skill` parameter.

However, what a skill *does internally* (the tool calls it makes) will also individually trigger `PreToolUse` hooks, so there's defense in depth.

#### c) Outbound messages

Claude Code has **no hook for intercepting outbound messages** from the agent to the user. The `Stop` hook fires when Claude finishes a response turn, but it cannot modify the content — it can only force the agent to continue working.

This means the policy system cannot prevent the agent from *saying* something to the user, only from *doing* something via tools. If an agent leaks sensitive information in its response text (not via a tool call), there is no interception point.

#### d) ACP (Agent Communication Protocol) messages

There are **no hooks for ACP-level communication**. If an agent sends a task to another agent via ACP, no hook fires on the task text. You cannot inspect or block inter-agent messages at the protocol level.

#### e) Model calls themselves

The policy system intercepts tool use, not the LLM inference itself. The agent can reason, plan, and generate text without any policy check. Policy only engages when the agent tries to *act* on its reasoning via a tool.

---

## 3. Corrected Hook Trigger Table

Your table was close. Here's the corrected version based on Claude Code's actual hook system:

| Path | Hook available | Can block/mutate? |
|------|---------------|-------------------|
| **User -> agent (inbound)** | `UserPromptSubmit` | Can block the prompt (exit 2) or inject `additionalContext`. **Cannot modify the prompt text itself.** |
| **Agent -> subagent (spawn)** | `PreToolUse` (on `Agent` tool) + `SubagentStart` (after spawn) | `PreToolUse` **can block** the spawn (deny the `Agent` tool call). `SubagentStart` fires after spawn — can inject context but **cannot block**. Cannot edit the task text in either case. |
| **Agent -> ACP agent (spawn)** | None | **Correct — no hook fires.** |
| **Agent -> channel (outbound reply)** | `Stop` (turn completion) | `Stop` can force continuation (`continue: false` stops the agent entirely, `decision: "block"` forces it to keep working). **Cannot modify or cancel the content of the message.** There is no `message_sending` hook. |

**Key corrections from your table:**
1. Inbound: the hook is `UserPromptSubmit`, not `message_received`/`message:preprocessed`. It *can* block (not fire-and-forget).
2. Subagent spawn: `PreToolUse` on the `Agent` tool *can* block the spawn entirely. Your table said it can block but cannot edit the task text — that's correct.
3. ACP: Correct, no hook fires.
4. Outbound: There is **no `message_sending` hook**. The `Stop` hook cannot modify content or set `cancel: true`. It can only force the agent to keep going or stop entirely.

---

## 4. Problems With the Current Approach

### 4.1 Outbound message blindspot

The agent can say anything in its response text. If the agent has read sensitive data (which would have been policy-checked), it could include that data in its natural language response. No hook exists to redact or block this.

### 4.2 Approval queue is in-memory

Pending approvals are stored in a Python dict. If the policy server restarts, all pending approvals are lost, and the polling agents will time out and deny. This needs persistence (Redis, SQLite, or the YAML file itself).

### 4.3 Polling latency and resource use

The plugin polls every 500ms for up to 120 seconds. During this time, the agent is blocked — it cannot do anything else. For interactive workflows this is fine, but for batch operations it's wasteful. A webhook-based callback would be more efficient but would require the agent container to expose an endpoint.

### 4.4 Channel ID dependency for identity

The policy server resolves the *person* from a `channel_id` (Telegram chat JID). If the agent doesn't pass a channel ID (e.g., running in a non-Telegram context, or a subagent that doesn't inherit the channel), the subject is `None` and person/group-based rules won't match. The system falls through to agent-level and wildcard rules only.

### 4.5 No policy for the policy server itself

The policy server's admin API is protected by a bearer token, but there's no policy-on-policy: anyone with the admin token can add an `allow-all` rule at priority 999. The NL chat endpoint could potentially be used to craft such a rule. Consider:
- Requiring approval for policy changes that broaden access
- Making critical deny rules `protected: true` (already supported)
- Auditing policy changes (already logged, but no alerting)

### 4.6 Container cache staleness (nanoclaw-specific)

As documented in CLAUDE.md, nanoclaw caches the agent-runner source on first run per group. Hook changes are silently ignored until the cache is manually cleared. This is an operational hazard — a policy update that changes the hook behavior won't take effect without manual intervention.

### 4.7 Single point of failure

If the policy server goes down, *all* agent actions are blocked (fail-closed). This is the correct security posture, but it means policy server availability is critical. Consider:
- Health check monitoring with alerting
- A local fallback cache of recently-evaluated rules (with a short TTL)
- Running the policy server with process supervision (systemd, Docker restart policy)

### 4.8 No rate limiting on the agent

An agent could flood the policy server with rapid tool calls. Even if each is individually allowed, the volume could be a problem. Consider per-agent rate limits in the policy engine.

---

## 5. Could This Be Done With Skills Instead of a Plugin?

### What skills are

In Claude Code, a **skill** is a prompt template that gets loaded when the `Skill` tool is invoked. Skills are defined as markdown files (`SKILL.md`) with frontmatter. They can:
- Provide instructions and context to the agent
- Be invoked by the user via `/skill-name` or by the agent via the `Skill` tool
- Trigger based on file patterns or bash command patterns (via `PreToolUse` hooks)

### Why skills alone are NOT sufficient for enforcement

**Skills are advisory, not enforcement.** A skill injects instructions into the agent's context, but the agent can choose to ignore them. There is no guarantee that the agent will follow skill instructions — they are prompt-level guidance, not a code-level gate.

The critical property of the current plugin/hook approach is that it operates at the **runtime level**: the `PreToolUse` hook executes *before* the tool runs, and can return `{ block: true }` to prevent execution entirely. The agent never gets the chance to run the blocked tool. This is a hard gate, not a suggestion.

A skill-based approach would look like:
1. A skill that says "before running any dangerous command, check with the policy server"
2. The agent reads this instruction and *hopefully* calls a policy-check tool first

But nothing stops the agent from skipping step 2. The agent might:
- Forget the instruction after context compaction
- Decide the command isn't "dangerous" and skip the check
- Be manipulated by prompt injection to ignore the skill

### Where skills CAN complement the plugin

Skills are useful for **policy awareness**, not enforcement:

1. **Policy explanation skill** — when the agent's tool call is blocked, a skill could provide context on *why* and suggest alternatives. (You already have the `/add-policy` skill doing something similar.)

2. **Pre-flight check skill** — a skill could teach the agent to check policy *before* attempting an action, reducing the number of blocked-then-retried tool calls. This improves UX but doesn't replace enforcement.

3. **Policy authoring skill** — the existing NL policy chat (`/add-policy`) is a good example. Skills that help humans write and understand policy rules.

**Bottom line:** Skills are a UX layer. The plugin/hook is the enforcement layer. You need both, but skills cannot replace the plugin.

---

## 6. Container Read-Only Requirement

You stated: *"any of these controls may be read from within OpenClaw running in a container, but not be able to be modified by OpenClaw."*

The current architecture satisfies this:

| Component | Agent can read? | Agent can modify? |
|-----------|----------------|-------------------|
| Policy rules | Yes — `GET /policies` (agent token has read access) | No — `POST/PUT/DELETE /policies` requires admin token |
| Identities | Yes — `GET /identities` | No — YAML file on server host, not in container |
| Audit log | Yes — `GET /audit` | No — append-only, no delete endpoint |
| Approvals | Yes — `GET /approvals/{id}` (own pending) | No — `POST /approvals/{id}` requires admin token |
| Policy server config | No | No — env vars on server host |

**The separation is architectural:** The policy server runs outside the container. The agent container only has a bearer token with read + `/check` access. It cannot call admin endpoints.

**Risks to this model:**
- If the agent can write to the filesystem *outside* the container (e.g., the policy server's `policies.yaml`), it could modify policy directly. Ensure file permissions prevent this.
- If the agent can make network calls to the policy server's admin port with a guessed/leaked admin token, it could modify policy. Ensure admin tokens are not in the container's environment.
- If the agent can modify its own hook configuration (e.g., edit `.claude/settings.json`), it could disable the `PreToolUse` hook. The `ConfigChange` hook can block this, but only if it's configured at the **policy** level (not project level — agents can't block `policy_settings` changes, but they also can't make them).

---

## 7. Architectural Alternatives

### 7.1 Proxy-based enforcement (instead of plugin)

Instead of a plugin inside the agent, run a **network proxy** between the agent container and the outside world. The proxy inspects all outgoing requests and applies policy. This would catch:
- Tool calls (indirectly, by inspecting the MCP/API traffic)
- Network access (HTTP requests, DNS)
- File system access (if using a FUSE-based filesystem)

**Pros:** Agent cannot bypass it (it's infrastructure-level). Catches network calls that aren't tool calls.
**Cons:** Much harder to implement. Doesn't understand tool semantics (tool name, parameters) without protocol-aware parsing. Latency overhead.

### 7.2 Sandboxed execution with capability tokens

Instead of checking policy per-call, issue **capability tokens** at session start. The agent receives tokens granting specific capabilities (e.g., "can read files in /workspace", "can run npm commands"). Each tool call must present a valid capability token. The policy server issues tokens based on the session's identity and rules.

**Pros:** Fewer round-trips to the policy server. Capabilities can be scoped and time-limited.
**Cons:** Harder to revoke mid-session. Coarser-grained than per-call evaluation. Requires tool-level support for capability checking.

### 7.3 Hybrid: hooks + skills + policy server (recommended)

The current approach, extended:

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **Enforcement** | `PreToolUse` hook -> policy server `/check` | Hard gate on every tool call |
| **Awareness** | Skills injected via `PreToolUse` pattern matching | Teach agent about policy before it acts |
| **Subagent control** | `PreToolUse` hook on `Agent` tool | Gate subagent creation |
| **Audit** | `PostToolUse` hook -> policy server `/audit` | Record what actually executed |
| **Config protection** | `ConfigChange` hook | Prevent agent from disabling its own hooks |

This is essentially what you have, with the addition of:
- Explicitly intercepting the `Agent` tool for subagent control
- Adding a `ConfigChange` hook to prevent hook self-modification
- Using skills for policy awareness (already partially in place)

---

## 8. Recommendations

1. **Add `Agent` tool to policy rules** — create rules that gate subagent spawning, potentially requiring approval for new subagents.

2. **Add `Skill` tool to policy rules** — if certain skills shouldn't be available to certain agents or users, gate them.

3. **Persist the approval queue** — move from in-memory dict to SQLite or Redis. Pending approvals surviving a restart is important for the approval workflow.

4. **Add a `ConfigChange` hook** — prevent agents from disabling their own `PreToolUse` hooks by blocking changes to hook configuration.

5. **Consider the outbound message gap** — if sensitive data leakage via response text is a concern, this is currently unaddressable via hooks. A `PostToolUse` hook on `Read` could flag when sensitive files are read, and a skill could instruct the agent not to include their contents in responses, but neither is a hard gate.

6. **Document the ACP blindspot** — if agents will communicate via ACP, the policy system has no visibility. This needs to be a known risk or addressed at the ACP protocol level.

7. **Add per-agent rate limiting** — protect the policy server from rapid-fire tool calls.

8. **Automate the nanoclaw cache invalidation** — a deployment script that clears caches and rebuilds the Docker image when the hook changes.
