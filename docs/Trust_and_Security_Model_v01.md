# OC Policy — Trust & Security Model

**Date**: 2026-03-21
**Status**: Design proposal — not yet implemented
**Supersedes**: `Identity_and_Plugin_Trust_v01.md` (which identified the problems; this document proposes solutions)

---

## 1. Starting From Natural Language

The best way to design a policy language is to start with things people actually want to say and work backwards to the abstractions needed to express them. Here are ten concrete examples, ranging from simple to complex:

1. *"Never remove any file without getting approval from the file's owner."*
2. *"No one may export more than one file per day."*
3. *"Subagents must obey the same policies as the session that spawned them — and cannot be granted more."*
4. *"Alice can search the web freely. Bob needs approval for every search."*
5. *"Scheduled tasks may not make any network calls."*
6. *"Only admins can push to the main branch. Developers can push to dev branches."*
7. *"Plugins from company_xyz may read files but not write them."*
8. *"Any action touching the /secrets/ directory requires two-person approval."*
9. *"The research plugin may only fetch URLs in the approved-news domain list."*
10. *"Deny all plugins that have not been reviewed in the last 90 days."*

These ten examples collectively surface every abstraction the model needs. The following sections derive those abstractions systematically.

---

## 2. Principles

Before specifying abstractions or language, establish the governing principles. These constrain every design choice that follows.

### P1 — Default Deny
Nothing is permitted unless a rule explicitly allows it. An absence of policy is not permission; it is a block. This is the opposite of the current `allow-all` catch-all and represents the correct posture for any system beyond a personal prototype.

### P2 — Least Privilege
Every actor — human, subagent, scheduled task, or plugin — receives the minimum permissions needed to accomplish its stated purpose. Permissions are not granted speculatively.

### P3 — No Upward Inheritance
A child actor (subagent, plugin) may never hold more permissions than the session that created it. Permissions flow down and can only be further restricted, never expanded. A subagent in alice's session operates under alice's policies plus any additional restrictions the system places on subagents. It cannot exceed alice's ceiling.

### P4 — Identity Must Be Externally Verified
An actor cannot declare its own identity. The system that spawns an actor — not the actor itself — asserts the actor's identity, and that assertion must be integrity-protected (at minimum a host-signed token) so the actor cannot forge it.

### P5 — Approval Is Not Blanket Permission
Approving a pending action grants permission for that specific action in that moment. It does not create a precedent, does not add a rule, and does not affect future identical requests. Each request is evaluated independently.

### P6 — Sensitive Actions Require Human Presence
Some actions must require a human approver regardless of any other policy. The `pending` verdict exists for this purpose. There is no automated bypass path for pending verdicts; resolution requires a human decision.

### P7 — Every Decision Is Auditable
Every `allow`, `deny`, and `pending` verdict is recorded permanently with enough context to reconstruct: who asked, what they asked for, which rule matched, who approved or denied, and when. Audit records are append-only.

### P8 — Policies Are Legible to Non-Engineers
The policy language must be readable by the people who own the security decisions — which are often not the people who built the system. A policy administrator should not need to understand code to read, audit, or write rules.

---

## 3. Abstractions

The ten examples require six categories of abstraction.

### 3.1 Subjects — Who Is Acting

A subject is the actor making a request. Subjects have a type and an identity within that type.

**People**
Human users identified by their communication channel ID (Telegram, Slack, etc.). People have roles. Roles aggregate permissions.

```
person: alice     roles: [admin, developer]
person: bob       roles: [developer]
person: jane      roles: [readonly]
```

**System Actors**
Non-human actors the system creates. Their type is their identity.

```
session:main           # human talking directly to the agent
agent:subagent         # agent spawned autonomously by the main agent
task:scheduled         # automated task with no human present
plugin:<source>:<name> # a plugin acting under its own identity
```

**Session Context**
Every actor carries the session that created it. A subagent spawned in alice's session has subject:

```
agent:subagent / session-owner:alice
```

This allows policies to say "approve by session owner" — meaning alice gets the approval request, not a global admin.

**Wildcards and Groups**
```
plugin:*               # any plugin actor
role:developer         # any person with the developer role
agent:*                # any system-spawned agent
```

### 3.2 Actions — What They Are Doing

Actions are semantic categories, not raw tool names. The mapping from tool name to action category is defined once and used everywhere.

| Action category | Maps to tools / operations |
|---|---|
| `read` | Read, Glob, Grep |
| `write` | Write, Edit |
| `delete` | Bash where program ∈ {rm, rmdir} |
| `execute` | Bash (general) |
| `search` | WebSearch |
| `fetch` | WebFetch, Bash where program ∈ {curl, wget} |
| `network` | search + fetch |
| `git-push` | Bash where program = git and args contain push |
| `git-commit` | Bash where program = git and args contain commit |
| `install` | Bash where program ∈ {npm, pip, brew, apt} |
| `export` | Write where path matches export pattern |
| `communicate` | MCP tools that send messages |
| `configure` | Write where path matches config pattern |

Actions can be combined: `network` is shorthand for `search | fetch`. The policy language allows both specific and categorical action references.

### 3.3 Resources — What Is Being Acted On

Resources are the targets of actions. They have a type, an identifier, and metadata.

**Files**
```
file: /workspace/group/reports/q1.md
  owner: alice          # who created it
  type: document
  sensitivity: internal
```

**Network targets**
```
url: https://bbc.com/news/article
  domain: bbc.com
  list: approved-news
```

**Code**
```
repo: my-project
  branch: main
  branch: dev/feature-x
```

**The agent system itself**
```
system: plugin-registry
system: policy-file
system: agent-config
```

Resource ownership is the key enabler for example #1 ("approval from the file's owner"). Ownership is not inferred from filesystem metadata — it is recorded by the policy system at creation time. When an actor creates a file, the system records: `file → owned-by: session-owner`. This survives the container lifecycle.

### 3.4 Conditions — When and How Much

Conditions qualify rules. Without conditions, rules are absolute. With conditions, rules apply only when the condition holds.

**Time**
```
during: business-hours        # 09:00–17:00 Mon–Fri, in configured timezone
during: 09:00-17:00 weekdays
not-during: 22:00-06:00
```

**Rate limits**
```
rate: max 1 per day per subject        # example #2
rate: max 10 per hour per session
rate: max 100 per day per role:developer
```

Rate state is tracked by the policy server. The counter key is `(subject, action, resource-type, window)`.

**Quorum**
```
approval: 1 from role:admin
approval: 2 from role:admin            # two-person rule (example #8)
approval: 1 from resource.owner        # owner specifically (example #1)
```

**Plugin freshness**
```
plugin-reviewed-within: 90 days        # example #10
```

### 3.5 Named Entities — Reusable Sets

Named entities prevent repetition and allow policy administrators to manage lists in one place.

```
list approved-news {
  bbc.com
  reuters.com
  apnews.com
  wsj.com
}

list export-paths {
  /workspace/group/exports/**
  /workspace/group/reports/**
}

list sensitive-paths {
  /workspace/group/secrets/**
  /workspace/project/.env
  /home/node/.claude/
}
```

A rule references `list:approved-news` and the actual domains are managed separately. Adding a new approved domain does not require touching the rule.

### 3.6 Trust Levels — Plugin and Source Trust

Not all actors are equally trusted. Trust levels form an ordered scale:

```
verified    # cryptographically signed, reviewed, explicitly approved
approved    # explicitly allowlisted by an admin, not signed
unknown     # not in any registry
blocked     # explicitly denied
```

Plugins carry a trust level based on their source. The trust level feeds into rule matching:

```
plugin:company_xyz:research-bot    trust: verified
plugin:github.com/user/tool        trust: unknown
plugin:local/my-script             trust: approved
```

---

## 4. The Policy Language — OCPL

**OC Policy Language** (OCPL) is a declarative rule language. It is intentionally not a programming language — there are no loops, variables, or functions. Rules are evaluated independently and the highest-priority matching rule wins.

### 4.1 File Structure

An OCPL file has four optional sections:

```
entities { ... }    # named people, roles, lists
rules { ... }       # the actual policy rules
defaults { ... }    # system-wide defaults
```

### 4.2 Entity Declarations

```ocpl
entities {

  person alice {
    roles: [admin, developer]
    telegram: "tg:111222333"
  }

  person bob {
    roles: [developer]
    telegram: "tg:444555666"
  }

  person jane {
    roles: [readonly]
    telegram: "tg:777888999"
  }

  list approved-news {
    bbc.com, reuters.com, apnews.com, wsj.com
  }

  list sensitive-paths {
    /workspace/group/secrets/**
    /workspace/project/.env
  }

}
```

### 4.3 Rule Structure

```ocpl
rule <name> {
  effect:    allow | deny | pending
  subject:   <subject-pattern>
  action:    <action-pattern>
  resource:  <resource-pattern>       # optional
  when:      <condition>              # optional
  approval:  <quorum-spec>            # only for effect: pending
  message:   "<human-readable reason>"
  priority:  <integer>               # higher wins; default 0
}
```

All fields except `effect`, `subject`, `action`, and `priority` are optional. A rule with only `effect`, `subject`, and `action` matches any resource at any time.

### 4.4 The Ten Examples in OCPL

**Example 1** — Never remove a file without approval from its owner:

```ocpl
rule require-owner-approval-for-delete {
  effect:   pending
  subject:  *
  action:   delete
  resource: file:*
  approval: 1 from resource.owner
  message:  "Deleting a file requires approval from the file's owner"
  priority: 100
}
```

**Example 2** — No more than one file export per day:

```ocpl
rule limit-daily-exports {
  effect:   deny
  subject:  *
  action:   export
  when:     rate(subject, export, 1 day) >= 1
  message:  "Export limit of 1 per day reached"
  priority: 90
}
```

**Example 3** — Subagents obey parent session policies and cannot exceed them:

This is a system-level principle, not a single rule. It is declared in the `defaults` section:

```ocpl
defaults {
  subagent-inherits: session-owner-policies
  subagent-ceiling:  session-owner          # cannot exceed parent
}
```

**Example 4** — Alice searches freely; Bob needs approval:

```ocpl
rule alice-search-free {
  effect:   allow
  subject:  person:alice
  action:   search
  priority: 50
}

rule bob-search-pending {
  effect:   pending
  subject:  person:bob
  action:   search
  approval: 1 from role:admin
  message:  "Bob's web searches require admin approval"
  priority: 40
}
```

**Example 5** — Scheduled tasks may not make network calls:

```ocpl
rule no-network-scheduled {
  effect:   deny
  subject:  task:scheduled
  action:   network
  message:  "Scheduled tasks cannot access the network"
  priority: 80
}
```

**Example 6** — Only admins push to main; developers push to dev branches:

```ocpl
rule deny-developer-push-main {
  effect:   deny
  subject:  role:developer
  action:   git-push
  resource: repo:branch(main)
  message:  "Developers cannot push to main"
  priority: 70
}

rule allow-developer-push-dev {
  effect:   allow
  subject:  role:developer
  action:   git-push
  resource: repo:branch(dev/*)
  priority: 60
}
```

**Example 7** — Plugins from company_xyz may read but not write:

```ocpl
rule company-xyz-read-only {
  effect:   allow
  subject:  plugin:company_xyz:*
  action:   read
  priority: 50
}

rule company-xyz-no-write {
  effect:   deny
  subject:  plugin:company_xyz:*
  action:   write
  message:  "company_xyz plugins have read-only access"
  priority: 60
}
```

**Example 8** — Two-person approval for sensitive paths:

```ocpl
rule two-person-secrets {
  effect:    pending
  subject:   *
  action:    write | delete | execute
  resource:  file:list(sensitive-paths)
  approval:  2 from role:admin
  message:   "Actions in sensitive directories require two admin approvals"
  priority:  100
}
```

**Example 9** — Research plugin may only fetch approved domains:

```ocpl
rule research-plugin-approved-domains {
  effect:   allow
  subject:  plugin:company_xyz:research-bot
  action:   fetch
  resource: url:domain(list:approved-news)
  priority: 60
}

rule research-plugin-deny-other-fetch {
  effect:   deny
  subject:  plugin:company_xyz:research-bot
  action:   fetch
  message:  "research-bot may only fetch from the approved-news domain list"
  priority: 50
}
```

**Example 10** — Deny plugins not reviewed in 90 days:

```ocpl
rule deny-stale-plugins {
  effect:   deny
  subject:  plugin:*
  action:   *
  when:     plugin-reviewed-within(subject, 90 days) = false
  message:  "Plugin has not been reviewed in 90 days and is blocked"
  priority: 95
}
```

### 4.5 The Defaults Block

The `defaults` block sets system-wide behavior that applies when no rule matches:

```ocpl
defaults {
  fallback:              deny              # P1 — default deny
  subagent-inherits:     session-owner-policies
  subagent-ceiling:      session-owner     # P3 — no upward inheritance
  audit:                 all               # P7 — log everything
  approval-timeout:      30 minutes        # pending requests expire
  approval-reminder:     5 minutes         # re-notify approver
}
```

---

## 5. Evaluation Model

When the policy server receives a `check` request it:

1. Resolves the subject to a full identity record (person + roles + session context + trust level)
2. Maps the raw tool name and params to a semantic action category
3. Identifies the resource (file with owner, URL with domain, etc.)
4. Collects all rules that match `(subject, action, resource)`
5. Sorts by priority descending; takes the highest match
6. If `effect: deny` — returns deny immediately
7. If `effect: allow` — evaluates any `when:` conditions; if all pass, returns allow
8. If `effect: pending` — creates an approval record, routes notification per the `approval:` spec, and waits
9. If no rule matches — returns deny (default deny, P1)

**Rate condition evaluation** is stateful. The server maintains a counter store keyed by `(subject-id, action-category, resource-type, time-window)` and increments on every `allow`. Counters are checked before the verdict is returned and are persisted to survive restarts.

**Conflict detection**: rules at the same priority that produce different verdicts for the same `(subject, action, resource)` triple are flagged as conflicts on load. The server refuses to start with a conflicted policy file. This is enforced at write time in the UI as well.

---

## 6. What This Requires to Build

The above model is significantly more capable than what exists today. This section maps each feature to its implementation cost.

| Feature | Complexity | Notes |
|---|---|---|
| Subject types (session/subagent/scheduled) | Low | `isMain` + `isScheduledTask` already in container input |
| Person identities + roles | Low | Simple YAML registry + chatJid lookup |
| Role-based rules | Low | Add `role` field to match evaluation |
| Semantic action categories | Medium | Mapping table from tool+params → category |
| Resource file ownership | Medium | Ownership registry; written at file-creation time |
| Named lists (domains, paths) | Low | Extend the YAML schema |
| Rate limiting | Medium | Requires persistent counter store |
| Two-person approval | Medium | Approval records need multi-approver state |
| Approval routing (notify owner / role) | Medium | Notification channel needed (Telegram, webhook) |
| Subagent ceiling / no-upward-inheritance | Medium | Subject resolution at check time |
| Plugin trust levels + freshness | High | Plugin registry + review workflow |
| Signed subject tokens (P4) | High | Cryptographic signing in container-runner |
| Conflict detection on load | Low | Rule analysis at parse time |
| `when:` time conditions | Low | Time check at evaluation |
| `when:` plugin-reviewed-within | High | Requires plugin metadata store |

**Practical build order:**

Phase 3a builds subject types — the single highest-value, lowest-cost item.
Phase 3b adds person identities, roles, and approval routing.
Phase 3c adds semantic action categories and named lists.
Phase 4 addresses rate limiting, resource ownership, and multi-person approval.
Phase 5 addresses plugin trust and signed tokens.

---

## 7. What This Model Does Not Solve

**The identity root problem.** Even with signed tokens, something has to be trusted unconditionally — the host that signs the tokens. If the host machine is compromised, all bets are off. This model buys defense-in-depth within a trusted host, not protection against a compromised infrastructure.

**Emergent behavior.** A policy can say "subagents cannot delete files." It cannot say "the combination of actions the agent takes must not collectively exfiltrate your SSH keys." Intent-level analysis is outside the scope of a rule-based system.

**Policy correctness.** A policy that perfectly expresses the administrator's intent is still only as good as the administrator's understanding of what the agent will do. Policies operate on actions, not goals. An agent can achieve a harmful goal entirely through individually-permitted actions.

**Approval fatigue.** If too many actions require approval, humans will approve reflexively without reading. The model provides the mechanism; the judgment of which actions actually need human review is a human problem.

These are not defects to fix — they are the inherent limits of application-layer policy enforcement. They should be understood and documented for anyone deploying this system in a real environment.
