---
name: add-policy
description: Create or explain OC Policy rules using natural language — "block curl", "let admins read files", "why was that blocked?"
user-invokable: true
---

# Natural Language Policy Authoring

Help the user create, modify, or understand OC Policy rules using plain English.

## Usage

```
/add-policy <description in plain English>
/add-policy explain <what happened>
```

Examples:
```
/add-policy block the agent from running rm
/add-policy let Lew run npm without asking
/add-policy require approval for all web searches
/add-policy explain why curl was blocked
/add-policy what rules apply to Bash for Lew
```

If no description is provided, ask the user what they'd like to allow, deny, or require approval for.

## Step 1 — Fetch Live Context

Before interpreting anything, read the current state from the running policy server. Use Bash with curl:

```bash
curl -s http://localhost:8080/policies -H "Authorization: Bearer $OC_POLICY_ADMIN_TOKEN"
curl -s http://localhost:8080/identities -H "Authorization: Bearer $OC_POLICY_ADMIN_TOKEN"
```

If the server is unreachable or the token is missing, tell the user:
- Server down → "The policy server isn't running. Start it with `cd src/server && ./start.sh`"
- Token missing → "Set OC_POLICY_AGENT_TOKEN in your environment"

From the response, note:
- **Existing rule IDs** (to avoid duplicates)
- **Existing rules** (to detect conflicts and suggest appropriate priorities)
- **Known people** (id and name) and **known groups** — use these to validate person/group references

## Step 2 — Interpret Intent

Parse the user's natural language into the rule schema.

### Result mapping

| User says | result |
|-----------|--------|
| "block", "stop", "prevent", "deny", "don't let", "never allow" | `deny` |
| "allow", "let", "permit", "can", "enable" | `allow` |
| "ask", "approve", "require approval", "check with me", "hold for" | `pending` |
| "without asking", "automatically", "freely" (modifies an allow) | `allow` |

If ambiguous between deny and pending (e.g. "block" could mean either), ask:
> "Do you want to block this outright (deny), or hold it for your approval first (pending)?"

### Tool inference

| User says | tool | program |
|-----------|------|---------|
| "run X", "execute X", "shell command X" | `Bash` | X |
| Specific programs: git, curl, wget, npm, pip, rm, mv, cp, ssh, docker, python | `Bash` | the program name |
| "search the web", "web search", "google" | `WebSearch` | — |
| "fetch a URL", "download", "HTTP request" | `WebFetch` | — |
| "read files", "read", "view files" | `Read` | — |
| "write files", "create files", "save" | `Write` | — |
| "edit files", "modify files" | `Edit` | — |
| "access the internet", "go online", "network access" | **ambiguous** — could be WebSearch + WebFetch + Bash(curl/wget). Ask. |

When the user mentions a program name (like "npm", "curl", "git"), always set `tool: Bash` AND `program: <name>`. Programs run inside Bash.

### Subject inference

| User says | match condition |
|-----------|----------------|
| A person's name or ID ("Lew", "alice", "bob") | `person: <id>` — look up in identities |
| A group name ("admins", "engineering", "team") | `group: <name>` — validate against known groups |
| "the agent", "it", no subject mentioned | No person/group condition (applies to everyone) |
| An unknown name/group | Ask: "I don't see X in identities. Known people: [list]. Known groups: [list]. Did you mean one of these?" |

When matching person names, be flexible: "Lew" matches person id "lew", "Alice" matches "alice". Use case-insensitive matching on the `name` and `id` fields from identities.

### Path inference

If the user mentions a file path, directory, or pattern:
- Specific file: `path: /workspace/secrets.env`
- Directory (all files): `path: /workspace/data/*`
- Recursive: `path: /workspace/data/**`
- "employee files", "employee database" → `path: /workspace/employees/*` (based on existing rules)

### Priority assignment

Assign priority based on specificity. More specific rules should have higher priority to be evaluated first:

| Specificity | Priority range | Example |
|-------------|---------------|---------|
| Person + tool + program | 65–75 | "let Lew run git" |
| Person + tool | 55–65 | "ask Lew before any Bash" |
| Group + path | 55–65 | "admins can read employee files" |
| Group + tool | 45–55 | "deny engineering web searches" |
| Tool + program | 30–40 | "block curl" |
| Tool only | 15–25 | "require approval for all Bash" |
| Catch-all | 0–5 | "deny everything else" |

Check existing rules and pick a priority that slots in correctly. If the new rule should override an existing one, set priority higher. If it should be a fallback, set it lower.

### ID generation

Generate a short, descriptive, kebab-case ID: `allow-lew-npm`, `deny-curl`, `ask-websearch`, `allow-admin-files`.

Check existing IDs for collisions. If the desired ID already exists, append `-2`, `-3`, etc. until unique (e.g. `deny-curl` → `deny-curl-2`). Never use numeric-only IDs like `001` or `008`.

## Step 3 — Resolve Ambiguity

If anything is unclear, ask the **minimum** questions needed. Don't ask about things you can infer. Common clarifications:

| Situation | Ask |
|-----------|-----|
| "Block" — deny or pending? | "Block outright, or hold for your approval?" |
| "Internet access" — which tools? | "Which do you want to cover: web searches, URL fetching, shell network commands (curl/wget), or all of these?" |
| Unknown person/group | "I don't see [name] in identities. Did you mean [closest match]?" |
| Too vague ("let engineers work") | "What specific actions — running commands, reading files, web access?" |
| Conflicts with existing rule | "This overlaps with rule [id] ([description], priority [N]). Should the new rule take precedence?" |

Only ask one round of questions at a time. Don't front-load all possible questions.

## Step 4 — Show the Proposed Rule (Dry Run)

Display the rule in YAML and explain what it does:

```
Here's the rule I'll create:

  id: deny-curl
  name: Block curl
  description: Deny all shell commands starting with curl
  result: deny
  priority: 35
  match:
    tool: Bash
    program: curl

This means: any Bash command starting with "curl" will be denied immediately,
regardless of who runs it.

Add this rule? [yes / edit / cancel]
```

Wait for confirmation before proceeding. If the user says "edit", ask what to change.

## Step 5 — Apply the Rule

On confirmation, POST to the policy server:

```bash
curl -s -X POST http://localhost:8080/policies \
  -H "Authorization: Bearer $OC_POLICY_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"deny-curl","name":"Block curl","description":"Deny all shell commands starting with curl","result":"deny","priority":35,"match":{"tool":"Bash","program":"curl"}}'
```

On success, confirm and offer undo:
> ✅ Rule added: `deny-curl` (deny Bash curl, priority 35)
>
> To undo: `/add-policy delete deny-curl`

On failure (409 = duplicate ID, etc.), explain the error and suggest a fix.

## Explain Mode

When the user asks "why was X blocked?" or "what rules apply to Y?":

1. Fetch the audit log: `GET /audit?limit=20`
2. Fetch current policies: `GET /policies`
3. Fetch identities: `GET /identities`
4. Find the relevant audit entry or walk through the rule evaluation logic
5. Explain which rule matched and why, in plain English

Example output:
> The last `curl` command was blocked by rule `008` ("Curl Request", priority 30).
> This rule requires approval for any Bash command starting with `curl`.
> It fired because: tool=Bash matched, program=curl matched.
> Higher-priority rules (lew-can-git at 70) didn't match because the program wasn't git.

## Delete Mode

When the user asks to delete or remove a rule:

```bash
curl -s -X DELETE http://localhost:8080/policies/<rule-id> \
  -H "Authorization: Bearer $OC_POLICY_ADMIN_TOKEN"
```

Confirm before deleting: "Delete rule `<id>` (<description>)? This cannot be undone."

## Multi-Rule Intents

Some requests naturally map to multiple rules (e.g. "block all internet access" = WebSearch + WebFetch + Bash network commands). In these cases:

1. Show all proposed rules together
2. Ask for confirmation as a batch
3. Apply them one at a time, reporting each

## Important Guidelines

- **Never apply a rule without showing it first and getting confirmation.**
- **Always check for conflicts** with existing rules before proposing.
- **Prefer specificity** — a rule for "curl" is better than one for "all Bash commands" unless the user truly wants the broad rule.
- **Default to pending over deny** when the user seems uncertain — it's less disruptive (they can still approve).
- **Use the real data** — always base person/group suggestions on what's actually in identities.yaml, not guesses.
