# OC Policy Management App — Architecture & Design

**Version**: v01
**Date**: 2026-03-19
**Status**: Draft

---

## Table of Contents

1. [What We Learned About OpenClaw](#1-what-we-learned-about-openclaw)
2. [System Components](#2-system-components)
3. [Three-Layer Architecture](#3-three-layer-architecture)
4. [ZPL-Inspired Identity Model](#4-zpl-inspired-identity-model)
5. [The Policy Language](#5-the-policy-language)
6. [Trusted Sources — Identity Resolution](#6-trusted-sources--identity-resolution)
7. [Old vs. ZPL-Style Policy Comparison](#7-old-vs-zpl-style-policy-comparison)
8. [Securing the Policy System Against OpenClaw](#8-securing-the-policy-system-against-openclaw)
9. [Plugin Capability Declarations and Credential Injection](#9-plugin-capability-declarations-and-credential-injection)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Build Phases](#11-build-phases)
12. [Open Questions](#12-open-questions)
13. [OpenClaw Plugin System Reference](#13-openclaw-plugin-system-reference)

---

## 1. What We Learned About OpenClaw

The critical finding: OpenClaw's plugin system exposes a `beforeToolCall` hook that can **block execution** before a tool runs. This is our enforcement point.

```typescript
// Plugin can return { blocked: true } to stop any tool call
interface PluginHookBeforeToolCallResult {
  params?: Record<string, unknown>; // modified params
  blocked?: boolean;                // STOP execution
}
```

Every risky action — `exec` (shell), `message`, `browser`, `cron` — flows through this hook. This means we don't need OS-level sandboxing; we can intercept at the application layer.

---

## 2. System Components

```text
┌─────────────────────────────────────────────────────┐
│                  OpenClaw Runtime                   │
│  ┌──────────┐   ┌─────────────────────────────────┐ │
│  │ Pi Agent │──▶│ beforeToolCall Plugin Hook      │ │
│  │  (LLM)   │   │  (TypeScript — lives in OC)     │ │
│  └──────────┘   └────────────┬────────────────────┘ │
└───────────────────────────────┼─────────────────────┘
                                │ HTTP (policy check / approval request)
                                ▼
┌─────────────────────────────────────────────────────┐
│           Policy Server (Python / FastAPI)          │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │  Policy    │  │  Approval  │  │   Audit Log   │  │
│  │  Engine    │  │   Queue    │  │               │  │
│  └────────────┘  └────────────┘  └───────────────┘  │
│                                                     │
│           Policy Store (YAML / SQLite)              │
└─────────────────────────┬───────────────────────────┘
                          │ WebSocket / SSE
                          ▼
┌─────────────────────────────────────────────────────┐
│              Policy UI (Web Browser)                │
│  • View allowed/denied actions                      │
│  • Add/delete/edit policies                         │
│  • Real-time approval queue                         │
│  • Audit log browser                                │
└─────────────────────────────────────────────────────┘
```

---

## 3. Three-Layer Architecture

### Layer 1: The Enforcement Plugin (TypeScript, lives inside OpenClaw)

A small OpenClaw plugin that:

1. On every `beforeToolCall`, POSTs to the Policy Server with `{ tool, action, params, sessionKey }`
2. The Policy Server responds synchronously: `{ verdict: "allow" | "deny" | "pending" }`
3. If `"deny"` → returns `{ blocked: true }` to OpenClaw
4. If `"pending"` → **polls** until approved/denied (blocking the agent mid-execution)
5. If `"allow"` → lets it through, logs to audit

This plugin is the **only thing that touches OpenClaw's internals**.

### Layer 2: Policy Server (Python + FastAPI)

The brains. Responsibilities:

**Policy Engine**

- Loads policies from a YAML file (or SQLite for persistence)
- Evaluates `allow/deny/require-approval` rules against incoming tool calls
- Returns verdict in ~5ms (in-process evaluation, no round trips)

**Approval Queue**

- Holds `pending` decisions with a UUID
- Plugin polls `GET /approvals/{id}` until resolved
- Security guard approves/denies via UI
- Timeout → auto-deny (configurable per policy)

**REST API endpoints**

```text
POST /check              # Plugin calls this to evaluate a tool call
GET  /approvals          # List pending approvals (UI polls this)
POST /approvals/{id}     # Approve or deny
GET  /policies           # List all policies
POST /policies           # Create new policy
PUT  /policies/{id}      # Update policy
DELETE /policies/{id}    # Delete policy
GET  /audit              # Audit log with filters
```

### Layer 3: Policy UI (simple web frontend)

Served by FastAPI, probably just HTMX or a simple React/Vite page. Three screens:

1. **Dashboard** — "What is OC allowed to do right now?" — a clear summary of effective policies
2. **Approvals** — real-time queue of pending actions needing approval (uses SSE/WebSocket for push)
3. **Policy Editor** — add/edit/delete policies, with a preview of what they'd allow/deny

---

## 4. ZPL-Inspired Identity Model

After reviewing [ZPL (Zero-trust Policy Language)](https://github.com/org-zpr/zpr-rfcs/blob/main/src/15-ZPL-Overview/body.md), the policy model has been significantly upgraded. ZPL's core insight: **policies should be written in terms of attributes, not identities**. "Allow sales employees to access CRM" stays stable even as people join and leave teams. Only the identity file changes.

### Entity Mapping

| ZPL Concept | OpenClaw Equivalent |
| --- | --- |
| **User** | The human chatting with OpenClaw (Slack ID, WhatsApp number, Telegram ID, CLI user) |
| **Endpoint** | The device/host OpenClaw runs on, or a connected node |
| **Service** | A tool call target — the `exec` binary, a URL domain, a message channel, an API |
| **Attribute** | `department: sales`, `roles: {admin, developer}`, `risk-level: high` |
| **Trusted Source** | A YAML identity file, LDAP, or OAuth provider that maps channel identity → attributes |
| **Permission** | `Allow sales employees to use network-tools.` |
| **Denial** | `Never allow intern users to execute file-operations.` |
| **Circumstance** | Time-of-day, rate limits (`limited to 10 exec calls/hour`) |

### Evaluation Flow

When `beforeToolCall` fires, the policy engine performs three steps before consulting any rule:

```text
1. Resolve session → channel identity
   sessionKey → OpenClaw gateway → Slack "U123ABC" / WhatsApp "+1555..."

2. Attribute resolution (Trusted Source)
   "U123ABC" → { department: engineering, roles: [employee, admin] }

3. Service classification
   exec("curl https://api.stripe.com") →
   { family: network-tool, program: curl, domain: api.stripe.com, risk: high }

4. Policy evaluation
   Does any Allow rule match (user attrs) × (service attrs)?
   Does any Never rule match? → overrides Allow, reports conflict.
   Result: allow | deny | require_approval
```

### Updated Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                      OpenClaw Plugin                        │
│   beforeToolCall fires with { tool, params, sessionKey }    │
│                                                             │
│   Resolves session → channel identity                       │
│   POSTs /check: { tool, params, user_channel_identity }     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Policy Server                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Attribute Resolution (Trusted Sources)             │   │
│  │  "U123ABC" → { department: sales, roles: [employee] }│   │
│  └───────────────────────┬─────────────────────────────┘   │
│                          │                                  │
│  ┌───────────────────────▼─────────────────────────────┐   │
│  │  Service Classification                             │   │
│  │  exec("curl https://api.stripe.com") →              │   │
│  │  { family: network-tool, domain: api.stripe.com }   │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                          │                                  │
│  ┌───────────────────────▼─────────────────────────────┐   │
│  │  Policy Evaluation Engine                           │   │
│  │  Allow rules matched against user + service attrs   │   │
│  │  Never rules checked — override any Allow           │   │
│  │  Result: allow | deny | require_approval            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. The Policy Language

ZPL-inspired, attribute-based. Policies never name specific people — only attribute combinations.

### Class Definitions

```yaml
# ~/.openclaw/policies.yaml

classes:
  users:
    employee:
      attributes: [department, roles]
    admin:
      parent: employee
      requires: { roles: admin }
    intern:
      parent: employee
      requires: { roles: intern }

  services:
    shell-command:
      attributes: [program, risk-level]
    network-tool:
      parent: shell-command
      match: { program: [curl, wget, nc, ssh] }
    file-operation:
      parent: shell-command
      match: { program: [rm, mv, cp, chmod, chown] }
    package-manager:
      parent: shell-command
      match: { program: [npm, pip, brew, apt] }
    browser-navigation:
      attributes: [domain, protocol]
```

### Policies (ZPL-style statements)

```yaml
policies:
  # Permissions (Allow)
  - Allow admin employees to use shell-commands.

  - Allow department:engineering employees to use network-tools.

  - Allow department:engineering employees to use package-managers,
    and require approval.

  - Allow sales employees to use browser-navigation.

  # Denials (Never — override any Allow)
  - Never allow intern employees to use file-operations.

  - Never allow users to use network-tools before 07:00 or after 22:00.
```

**Evaluation order**: Never rules take priority over Allow rules. Among Allow rules, more specific matches win (class hierarchy). Default if no match: deny.

---

## 6. Trusted Sources — Identity Resolution

OpenClaw already knows a user's **channel identity** (Slack ID, phone number, Telegram ID). The Trusted Source maps that to **attributes**, which is what policies actually evaluate against.

### Simple case: Local YAML file

```yaml
# ~/.openclaw/policy-identities.yaml

users:
  - identity:
      slack: "U123ABC"
      whatsapp: "+15551234567"
    attributes:
      name: "John Smith"
      department: engineering
      roles: [employee, admin]

  - identity:
      telegram: "98765432"
    attributes:
      name: "Jane Doe"
      department: sales
      roles: [employee, intern]

  - identity:
      cli: "lewtucker"          # local shell user invoking OpenClaw
    attributes:
      name: "Lew Tucker"
      department: engineering
      roles: [employee, admin]
```

### 1Password as a Trusted Source

1Password is a natural fit for storing user identities and attributes — it already has vaults (namespaces), items (identities with immutable UUIDs), and custom fields (attributes). Changes made in 1Password are automatically reflected in the policy engine.

```text
1Password vault: "OC Policy Identities"
├── Item: "John Smith"          ← immutable UUID is the identity token
│   ├── Field: slack_id        = "U123ABC"
│   ├── Field: whatsapp        = "+15551234567"
│   ├── Field: department      = "engineering"
│   └── Field: roles           = "employee,admin"
├── Item: "Jane Doe"
│   ├── Field: telegram        = "98765432"
│   ├── Field: department      = "sales"
│   └── Field: roles           = "employee,intern"
```

The Policy Server queries 1Password via its SDK or CLI at attribute resolution time, with a configurable cache TTL. Revoking someone's access means removing them from the vault or clearing their `roles` field — zero policy file changes.

```python
# Using 1Password Connect (self-hosted) or the 1Password SDK
import onepassword

class OnePasswordTrustedSource(TrustedSource):
    def __init__(self, vault: str, connect_host: str, token: str):
        self.client = onepassword.Client(connect_host, token)
        self.vault = vault
        self._cache: dict[str, dict] = {}

    def get_attributes(self, channel: str, identity: str) -> dict[str, Any]:
        cache_key = f"{channel}:{identity}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        items = self.client.items.list(vault=self.vault)
        for item in items:
            fields = {f.label: f.value for f in item.fields}
            if fields.get(channel) == identity:
                attrs = parse_attributes(fields)
                self._cache[cache_key] = attrs
                return attrs
        return {}  # unknown identity → no attributes → deny by default
```

### Trusted Source abstraction (pluggable)

```python
class TrustedSource:
    def get_attributes(self, channel: str, identity: str) -> dict[str, Any]: ...

class YamlFileTrustedSource(TrustedSource): ...        # Phase 1 — flat file, simple
class OnePasswordTrustedSource(TrustedSource): ...     # Phase 2 — vault-backed identities
class LdapTrustedSource(TrustedSource): ...            # Phase 3 — enterprise directory
class OAuthTrustedSource(TrustedSource): ...           # Phase 3 — Google/GitHub → attributes
```

Swapping the trusted source requires zero policy changes. Only the identity layer changes.

---

## 7. Old vs. ZPL-Style Policy Comparison

| Old approach | ZPL-style approach |
| --- | --- |
| `match: { command: "curl *" }` | `Allow engineers to use network-tools.` |
| Identity named in policy: "allow John" | Identity file: John has `roles: [admin]` |
| Policies change when people change | Identity file changes; policies stay stable |
| No concept of groups/roles | First-class: `department: sales`, `roles: {admin}` |
| Flat list of rules | Class hierarchy — `network-tool` inherits from `shell-command` |
| No conflict detection | `Never` overrides `Allow`; conflicts reported explicitly |

---

## 8. Securing the Policy System Against OpenClaw

The bootstrapping problem: if OpenClaw controls the shell, it could edit the policy files, kill the Policy Server, or disable its own enforcement plugin. The system being controlled cannot be the guardian of its own controls.

### Threat Model

| Attack | What OpenClaw does | Effect |
| --- | --- | --- |
| File edit | `exec("echo '' > ~/.openclaw/policies.yaml")` | Wipes all policies |
| Plugin removal | `exec("rm -rf ~/.openclaw/plugins/oc-policy/")` | Removes enforcement |
| Config edit | `exec("vim ~/.openclaw/config.yaml")` | Disables plugin entry |
| Server kill | `exec("kill $(lsof -ti:8080)")` | Takes down Policy Server |
| Identity tamper | `exec("cat /dev/null > policy-identities.yaml")` | Erases all user attributes |
| API abuse | Call `DELETE /policies/deny-all` via the Policy Server's REST API | Removes its own deny rules through the legitimate interface |

### Layer 1 — Separate OS User (Most Important)

OpenClaw's process and the Policy Server run as **different OS users**. Policy files are owned by the policy user and not writable by the OpenClaw user.

```bash
# Policy files owned by oc-policy, not writable by lewtucker
sudo chown oc-policy ~/.openclaw/policies.yaml
sudo chown oc-policy ~/.openclaw/policy-identities.yaml
sudo chmod 640 ~/.openclaw/policies.yaml

# Policy Server runs as oc-policy
sudo -u oc-policy uvicorn policy_server:app

# OpenClaw config: readable but not writable by the OC process user
sudo chown oc-policy ~/.openclaw/config.yaml
sudo chmod 444 ~/.openclaw/config.yaml
```

### Layer 2 — Split the API: Check-Only vs. Admin

The plugin token and the human admin token are entirely separate. OpenClaw's plugin can never reach the policy CRUD endpoints.

```text
Port 8080  — Agent-facing (plugin token only)
  POST /check
  GET  /approvals/{id}?wait=true

Port 8443  — Human-facing (admin token only, separate credential)
  GET/POST/PUT/DELETE /policies
  GET/POST/DELETE /identities
  GET /audit
```

### Layer 3 — File Immutability

```bash
# macOS — system immutable: even root cannot modify without explicitly unflagging
sudo chflags schg ~/.openclaw/policies.yaml
sudo chflags schg ~/.openclaw/policy-identities.yaml

# Linux equivalent
sudo chattr +i ~/.openclaw/policies.yaml
```

### Layer 4 — Secrets and Keys in a Vault (1Password)

No credentials or signing keys should ever live on disk as plaintext or be accessible to the OpenClaw process. 1Password serves three roles here:

#### Role A — Secrets store for the Policy Server

The Policy Server is started with secrets injected by the 1Password CLI, never written to disk:

```bash
# Secrets injected at process start from 1Password; never touch disk
op run --env-file=.op.env -- uvicorn policy_server:app
```

```text
# .op.env — references, not values
POLICY_SIGNING_KEY=op://OC-Policy/policy-signing-key/credential
ADMIN_API_TOKEN=op://OC-Policy/admin-api-token/credential
OP_CONNECT_TOKEN=op://OC-Policy/1password-connect/token
```

Secrets held in the Policy Server's environment under `oc-policy` user — completely invisible to OpenClaw's process.

#### Role B — Trusted Source for user identities and attributes

Rather than a flat YAML file, user identities and their attributes live in a 1Password vault. This gives access control, audit logging, and change history for free. The Policy Server uses 1Password Connect (self-hosted) to query attributes at runtime.

```text
1Password vault: "OC Policy Identities"
  Item: "John Smith"
    slack_id:   U123ABC
    department: engineering
    roles:      employee,admin
```

Revoking access = remove item or clear `roles` field in 1Password. No policy file touched.

#### Role C — Admin API token delivery to humans

The human admin token for the Policy Server's CRUD API lives in 1Password. When the operator opens the management UI, they retrieve it via `op read` or the 1Password browser extension — never stored in a config file or shell history.

### Layer 5 — Signed Policies

Even if a file is modified (e.g., via privilege escalation), the Policy Server rejects unsigned policy files:

```python
POLICY_SIGNING_KEY = os.environ["POLICY_SIGNING_KEY"]  # from vault, never on disk

def load_policies(path: str) -> list[Policy]:
    content = Path(path).read_bytes()
    expected = hmac.new(POLICY_SIGNING_KEY.encode(), content, hashlib.sha256).hexdigest()
    actual = Path(path + ".sig").read_text().strip()
    if not hmac.compare_digest(expected, actual):
        raise SecurityError("Policy file signature invalid — possible tampering")
    return parse_yaml(content)
```

The signing key is held only in 1Password and injected into the Policy Server process. OpenClaw can corrupt the YAML bytes but cannot produce a valid signature.

### Layer 6 — Append-Only Audit Log

```bash
# Linux: append-only — process can write new entries but cannot delete or overwrite
sudo chattr +a ~/.openclaw/policy-audit.log
```

Or write audit events to a remote syslog / append-only object store that the OpenClaw process has no credentials for.

### Practical Priority Order

| Priority | Layer | Effort | Value |
| --- | --- | --- | --- |
| 1 | Separate OS user for Policy Server + files | Low | Blocks most attacks |
| 2 | Split check-only vs. admin API ports + tokens | Low | Blocks API abuse |
| 3 | File immutability flags | Very low (2 commands) | Defense-in-depth |
| 4 | 1Password for all secrets + as Trusted Source | Medium | Eliminates plaintext secrets entirely |
| 5 | Policy signing | Medium | Protects against privilege escalation |
| 6 | Append-only audit log | Low | Tamper-evident trail |

---

## 9. Plugin Capability Declarations and Credential Injection

### The Problem with Implicit Policies

Without explicit declarations, policies accumulate implicitly in JSON/YAML files with no clear provenance — it's hard to know which rules exist because a plugin needed them vs. because a human wrote them. Two principles fix this:

1. **Plugins declare what they need** — at install time, not at runtime
2. **Credentials are injected, not configured** — the Policy Server holds them, plugins never see them in config files

These together form a consent-and-delegation model: you know exactly what you granted, to whom, and you can revoke either independently.

---

### Part 1 — Capability Declarations in Plugin Manifests

Plugins extend `openclaw.plugin.json` with a `security` block that declares every tool they intend to call, split into required (plugin won't function without) and optional (degrades gracefully):

```json
{
  "name": "github-skill",
  "version": "1.0.0",

  "security": {
    "capabilities": {
      "required": [
        {
          "tool": "exec",
          "match": { "program": "git" },
          "justification": "Clone and manage git repositories"
        },
        {
          "tool": "browser",
          "match": { "domain": ["github.com", "api.github.com"] },
          "justification": "Access GitHub web interface and API"
        }
      ],
      "optional": [
        {
          "tool": "exec",
          "match": { "program": "gh" },
          "justification": "GitHub CLI for PR creation and review",
          "degraded_without": "PR management features will be unavailable"
        }
      ]
    },

    "credentials": {
      "required": [
        {
          "name": "GITHUB_TOKEN",
          "description": "GitHub personal access token",
          "scopes_needed": ["repo", "read:org"],
          "how_to_get": "github.com → Settings → Developer settings → Personal access tokens",
          "vault_hint": "op://Work/GitHub/token"
        }
      ],
      "optional": [
        {
          "name": "GITHUB_APP_PRIVATE_KEY",
          "description": "GitHub App private key for org-wide access",
          "degraded_without": "Limited to personal repos only"
        }
      ]
    }
  }
}
```

### Install-Time Consent Flow

```text
$ openclaw plugins install github-skill

Installing github-skill v1.0.0...

This plugin is requesting the following CAPABILITIES:

  Required (plugin will not function without these):
    ✓ exec: run 'git' commands
      → for cloning and managing repositories
    ✓ browser: access github.com, api.github.com
      → for GitHub web UI and API

  Optional (plugin degrades gracefully without these):
    ○ exec: run 'gh' CLI commands
      → for PR management; without this, PR features are disabled

  Grant capabilities?  [A]ll / [R]equired only / [N]one  > A

This plugin is requesting the following CREDENTIALS:

  GITHUB_TOKEN  (required)
  GitHub personal access token — scopes: repo, read:org
  Where to get: github.com → Settings → Developer settings → PATs

    [1] Fetch from 1Password  op://Work/GitHub/token
    [2] Browse 1Password vaults
    [3] Enter manually
    [4] Skip (plugin will not function)
  > 1
  ✓ Fetched GITHUB_TOKEN from 1Password
  ✓ Stored in Policy Server credential store (encrypted, scoped to github-skill)

✓ Policy entries auto-generated for granted capabilities
✓ github-skill installed

  To review or revoke: openclaw policy show github-skill
```

### Auto-Generated Policy Entries

The Policy Server writes these on consent, tagged with provenance so the UI can distinguish them from human-authored rules:

```yaml
- id: plugin-github-skill-exec-git
  result: allow
  tool: exec
  match: { program: git }
  source: plugin-install/github-skill    # provenance — where the rule came from
  granted_at: "2024-01-15T10:23:00Z"
  revocable: true                        # uninstalling the plugin removes this

- id: plugin-github-skill-browser-github
  result: allow
  tool: browser
  match: { domain: [github.com, api.github.com] }
  source: plugin-install/github-skill
  granted_at: "2024-01-15T10:23:00Z"
  revocable: true
```

Uninstalling a plugin auto-revokes all its `source: plugin-install/*` entries. The UI separates plugin-granted rules from user-authored rules visually.

---

### Part 2 — Credential Injection

Credentials never live in plugin config files. They live in the Policy Server's encrypted credential store and are injected into the plugin's process environment at runtime — invisible to other plugins and never written to disk.

#### Credential Lifecycle

```text
Install time (human-initiated, once)

  1Password / manual entry
       │
       ▼  fetched once, never stored on disk as plaintext
  Policy Server Credential Store
  (encrypted, owned by oc-policy user)
       │
       ├── credential: GITHUB_TOKEN
       │     scoped_to: github-skill
       │     source: onepassword
       │     last_used: 2h ago
       │     revoked: false
       │
       ▼  injected at runtime (env var, process-scoped)

  Plugin process (github-skill)
  GITHUB_TOKEN in env — never in config, not shared with other plugins
```

#### Credential Store Interface

```python
class CredentialStore:
    def store(self, plugin_id: str, name: str, value: str, source: str) -> str:
        """
        Encrypts and stores a credential scoped to one plugin.
        source: 'onepassword' | 'manual' | 'oauth'
        Returns an opaque reference ID for audit logs.
        """

    def inject(self, plugin_id: str) -> dict[str, str]:
        """
        Returns env vars for this plugin's process at launch time.
        Logs each injection to the audit trail.
        """

    def revoke(self, plugin_id: str, name: str) -> None:
        """
        Deletes the credential. Next inject() call omits it.
        Plugin receives null/empty and should fail gracefully at the API level.
        """

    def audit_log(self, plugin_id: str) -> list[CredentialEvent]:
        """
        Full history: when each credential was injected, by which process,
        in the context of which tool call.
        """
```

#### Two Independent Revocation Levers

Capabilities and credentials can be revoked separately — they fail at different layers:

| Revoke what | Effect | Fails at |
| --- | --- | --- |
| Capability (policy entry) | Tool call is blocked before it executes | Policy Server `beforeToolCall` check |
| Credential | Tool call proceeds but gets null/empty auth token | External API (401 Unauthorized) |

Both are immediate, logged, and visible in the dashboard.

---

### What the Dashboard Shows Per Plugin

```text
Plugin: github-skill
Status: Active | Installed: 2024-01-15

── Capabilities ─────────────────────────────────────────────────
  ALLOWED   exec: git *          plugin-granted  2024-01-15  [Revoke]
  ALLOWED   browser: github.com  plugin-granted  2024-01-15  [Revoke]
  DENIED    exec: gh *           optional, not granted         [Grant]

── Credentials ──────────────────────────────────────────────────
  GITHUB_TOKEN    source: 1Password    last used: 2h ago       [Revoke]

── Recent Activity ──────────────────────────────────────────────
  14:23  exec: git clone https://github.com/org/repo      ✓ allowed
  14:25  browser: api.github.com/repos/org/repo/pulls     ✓ allowed
  09:10  exec: gh pr create ...                           ✗ denied (capability not granted)
```

---

### How Capabilities + Credentials Fit the ZPL Model

Plugin capability declarations map directly onto the identity and policy model:

| Concept | Plugin security manifest | ZPL / Policy System |
| --- | --- | --- |
| What tools can it call | `capabilities.required/optional` | Auto-generated Allow policies with `source: plugin-install` tag |
| What external services can it reach | `credentials.required/optional` | Credential store entries scoped to plugin identity |
| Granting access | Install-time consent dialog | Human approval → policy entry + credential stored |
| Revoking access | [Revoke] in dashboard | Delete policy entry OR delete credential (or both) |
| Audit trail | Per-plugin activity log | Append-only audit log with tool call context |

The plugin's identity in the Policy System is its `plugin_id`. Policies can reference it directly: `Never allow plugin-id:untrusted-plugin to use file-operations.`

---

## 10. Key Design Decisions

| Question | Options | Recommendation |
| --- | --- | --- |
| Policy storage | YAML file vs SQLite | Start with YAML (human-editable, git-friendly), migrate to SQLite if needed |
| Plugin ↔ Server comms | HTTP REST vs Unix socket vs shared file | HTTP REST (simple, testable, network-transparent) |
| Approval blocking | Plugin polls vs WebSocket long-poll | Long-poll `GET /approvals/{id}?wait=true` — clean and compatible |
| UI framework | HTMX + Jinja2 vs React/Vite | HTMX for simplicity (no build step, Python dev-friendly) |
| Auth for UI | None vs simple password vs token | Simple token for now (single user) |

---

## 11. Build Phases

### Phase 1 — Enforcement Proof of Concept

1. Write the OpenClaw plugin (TypeScript) with `beforeToolCall` that calls a local HTTP server
2. Write a minimal Python server that returns `allow/deny` based on a hardcoded policy
3. Prove we can block an `exec` call in a real OpenClaw session

### Phase 2 — Policy Engine + Storage

1. YAML policy file format and parser
2. Rule evaluation engine (match + priority + effect)
3. REST CRUD API for policies
4. Parse `security.capabilities` from plugin manifests; auto-generate tagged policy entries at install

### Phase 2.5 — Credential Store

1. Encrypted credential store in Policy Server (scoped per plugin)
2. Install-time consent CLI: capability approval + credential fetch (1Password or manual)
3. Runtime credential injection into plugin processes
4. Revocation: single call deletes credential, next injection omits it

### Phase 3 — Approval Workflow

1. `require_approval` verdict type
2. Pending queue with long-poll endpoint
3. Simple approval UI (even just a CLI first)

### Phase 4 — Full UI

1. Dashboard showing effective policy state
2. Audit log
3. Rich policy editor

---

## 12. Open Questions

1. **Can the plugin tolerate latency?** The `beforeToolCall` hook is synchronous from the agent's POV — if the Policy Server is slow or down, does OpenClaw timeout/error? Need to check timeout behavior and add a fallback (fail-open vs fail-closed).

2. **Session → identity mapping**: Does OpenClaw's `sessionKey` carry enough information to resolve back to a channel identity (Slack ID, phone number)? We need to examine how sessions are created in the gateway (`src/gateway/`).

3. **The "no user" case**: OpenClaw can run autonomous tasks (cron jobs, background agents) with no human initiator. These need a special `agent` principal with its own attribute set and policies.

4. **Multiple agents/sessions?** OpenClaw supports multiple agents. Should policies be per-agent or global?

5. **Who is the "security guard"?** Is this a human at a UI, or could it be an automated policy (e.g., "auto-approve if command is in safelist")?

6. **What happens to blocked commands?** Does the agent retry, fail gracefully, or get notified with a reason? ZPL provides a `and signal` clause for logging — we should surface the block reason back to the agent so it can explain to the user.

7. **Policy conflicts**: ZPL requires that `Never` vs `Allow` conflicts be detected and reported. The UI should surface these — not just silently pick a winner.

8. **Circumstances (time, rate limits)**: ZPL supports `before 18:00` and `limited to 10Gb/day` style circumstances. Worth reserving a `when:` slot in the policy schema from day one even if only time-of-day is implemented initially.

9. **Trusted source refresh**: For the YAML file case, watch for file changes (inotify/fsevents). For LDAP, implement a configurable refresh interval and cache invalidation.

---

## 13. OpenClaw Plugin System Reference

Key files in the OpenClaw repo relevant to this project:

- `src/plugins/types.ts` — Plugin hook type definitions (`beforeToolCall`, `afterToolCall`, etc.)
- `src/agents/bash-tools.exec.ts` — How `exec` tool works (the highest-risk tool)
- `src/gateway/tools-invoke-http.ts` — HTTP tool invocation endpoint in the Gateway
- `src/config/config.ts` — Config schema (`~/.openclaw/config.yaml`)
- `src/security/` — Existing security policy infrastructure
- `extensions/` — Examples of real plugin implementations to reference
