# Plan: Phase 1 — OpenClaw Enforcement Plugin

**Version**: v01
**Date**: 2026-03-19
**Status**: Ready to build
**Reference**: [docs/OC_Policy_Control_v01.md](../docs/OC_Policy_Control_v01.md) — Section 3 (Three-Layer Architecture), Phase 1

---

## Objective

Prove that we can intercept and block an OpenClaw tool call before it executes. By the end of this phase, a `git` command should pass and an arbitrary `exec` command should be blocked — enforced by a policy check through a local HTTP server.

This is the narrowest possible slice: no YAML policy files, no identity resolution, no UI. Just the two components talking to each other with a hardcoded rule.

---

## Deliverables

```text
src/plugin/
├── package.json           # Plugin manifest + deps
├── tsconfig.json          # TypeScript config
└── src/
    └── index.ts           # Plugin entry point — registers beforeToolCall hook

src/server/
├── requirements.txt       # Python dependencies
└── server.py              # Minimal FastAPI policy server
```

---

## Prerequisites

- OpenClaw installed and running locally (`openclaw gateway` starts without error)
- Node.js ≥ 18 available (`node --version`)
- Python ≥ 3.11 available (`python3 --version`)
- `OC_POLICY_AGENT_TOKEN` chosen — any random string, e.g. `openssl rand -hex 32`
  - Set in shell: `export OC_POLICY_AGENT_TOKEN=<value>`
  - Set in OpenClaw's environment too (see Step 4)

---

## Step 1 — Set Up the Plugin Package

Create `src/plugin/package.json`:

```json
{
  "name": "@oc-policy/enforcement-plugin",
  "version": "0.1.0",
  "description": "OC Policy enforcement — intercepts tool calls via beforeToolCall hook",
  "type": "module",
  "devDependencies": {
    "openclaw": "workspace:*",
    "typescript": "^5.0.0"
  },
  "peerDependencies": {
    "openclaw": ">=2026.1.26"
  },
  "openclaw": {
    "extensions": [
      "./src/index.ts"
    ]
  }
}
```

Create `src/plugin/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "esModuleInterop": true,
    "outDir": "./dist"
  },
  "include": ["src/**/*"]
}
```

---

## Step 2 — Implement the Plugin (`src/plugin/src/index.ts`)

```typescript
import type {
  OpenClawPluginApi,
  PluginHookBeforeToolCallEvent,
  PluginHookBeforeToolCallResult,
} from "openclaw/plugin-sdk";

const POLICY_SERVER_URL = process.env.OC_POLICY_SERVER_URL ?? "http://localhost:8080";
const AGENT_TOKEN       = process.env.OC_POLICY_AGENT_TOKEN ?? "";
const APPROVAL_POLL_MS  = 2000;
const APPROVAL_TIMEOUT_MS = 120_000;

async function checkPolicy(
  event: PluginHookBeforeToolCallEvent
): Promise<PluginHookBeforeToolCallResult> {
  let response: Response;

  try {
    response = await fetch(`${POLICY_SERVER_URL}/check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${AGENT_TOKEN}`,
      },
      body: JSON.stringify({
        tool: event.toolName,
        params: event.params,
      }),
    });
  } catch (err) {
    // Policy Server unreachable — fail closed (deny)
    console.error("[oc-policy] Policy Server unreachable — blocking tool call:", err);
    return { block: true, blockReason: "OC Policy Server unreachable — failing closed" };
  }

  if (!response.ok) {
    return { block: true, blockReason: `OC Policy Server returned ${response.status}` };
  }

  const body = await response.json() as {
    verdict: "allow" | "deny" | "pending";
    reason?: string;
    approvalId?: string;
  };

  if (body.verdict === "allow") {
    return {};
  }

  if (body.verdict === "deny") {
    return { block: true, blockReason: body.reason ?? "Denied by policy" };
  }

  // verdict === "pending" — poll until resolved or timeout
  if (body.verdict === "pending" && body.approvalId) {
    return await pollForApproval(body.approvalId);
  }

  return { block: true, blockReason: "Unexpected verdict from Policy Server" };
}

async function pollForApproval(approvalId: string): Promise<PluginHookBeforeToolCallResult> {
  const deadline = Date.now() + APPROVAL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, APPROVAL_POLL_MS));

    const res = await fetch(
      `${POLICY_SERVER_URL}/approvals/${approvalId}?wait=true`,
      { headers: { "Authorization": `Bearer ${AGENT_TOKEN}` } }
    );

    if (!res.ok) continue;

    const body = await res.json() as { verdict: "allow" | "deny"; reason?: string };

    if (body.verdict === "allow") return {};
    if (body.verdict === "deny") {
      return { block: true, blockReason: body.reason ?? "Denied by approver" };
    }
  }

  return { block: true, blockReason: "Approval timed out" };
}

// ── Plugin definition ────────────────────────────────────────────────────────

const ocPolicyPlugin = {
  id: "oc-policy",
  name: "OC Policy Enforcement",
  description: "Checks every tool call against the OC Policy Server before execution",

  register(api: OpenClawPluginApi) {
    api.registerHook(
      "before_tool_call",
      async (event: PluginHookBeforeToolCallEvent): Promise<PluginHookBeforeToolCallResult> => {
        return await checkPolicy(event);
      }
    );
  },
};

export default ocPolicyPlugin;
```

**Key decisions baked in:**

| Decision | Choice | Reason |
| --- | --- | --- |
| Server unreachable | Fail closed (`block: true`) | Safety over availability |
| Approval polling interval | 2 seconds | Low overhead, responsive enough |
| Approval timeout | 120 seconds | Matches default in policy spec |
| Agent token | Bearer header | Simple, easy to rotate |

---

## Step 3 — Install the Plugin into OpenClaw

Option A — workspace install (if running OpenClaw from source):

```bash
# From the OpenClaw Clone root
pnpm add --workspace @oc-policy/enforcement-plugin@file:../OC_Policy/src/plugin
```

Option B — direct path reference in OpenClaw config (`~/.openclaw/config.yaml`):

```yaml
plugins:
  entries:
    oc-policy:
      path: /Users/lewtucker/Documents/dev/OC_Policy/src/plugin
      enabled: true
```

Verify the plugin is loaded:

```bash
openclaw plugins list
# Should show: oc-policy — OC Policy Enforcement
```

---

## Step 4 — Minimal Python Policy Server (`src/server/server.py`)

Phase 1 uses hardcoded rules — no YAML files, no database.

```python
"""
OC Policy Server — Phase 1
Hardcoded policy: allow 'git' exec commands, deny everything else.
"""
import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="OC Policy Server", version="0.1.0")

AGENT_TOKEN = os.environ["OC_POLICY_AGENT_TOKEN"]

# ── Hardcoded Phase 1 policy ─────────────────────────────────────────────────
ALLOWED_PROGRAMS = {"git"}


def extract_program(command: str) -> str:
    """Return the first word (binary name) of a shell command."""
    return command.strip().split()[0] if command.strip() else ""


# ── Request / response models ─────────────────────────────────────────────────
class CheckRequest(BaseModel):
    tool: str
    params: dict


class CheckResponse(BaseModel):
    verdict: str          # "allow" | "deny" | "pending"
    reason: str | None = None
    approval_id: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────
def require_agent_token(authorization: str = Header(...)) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str = Header(...)):
    require_agent_token(authorization)

    if req.tool == "exec":
        command = str(req.params.get("command", ""))
        program = extract_program(command)

        if program in ALLOWED_PROGRAMS:
            print(f"[ALLOW] exec: {command}")
            return CheckResponse(verdict="allow")

        print(f"[DENY]  exec: {command}  (program '{program}' not in allowlist)")
        return CheckResponse(
            verdict="deny",
            reason=f"No policy allows exec of '{program}'"
        )

    # All other tools denied by default in Phase 1
    print(f"[DENY]  {req.tool}: {req.params}")
    return CheckResponse(verdict="deny", reason=f"Tool '{req.tool}' not permitted by Phase 1 policy")


@app.get("/health")
async def health():
    return {"status": "ok", "phase": 1}
```

Create `src/server/requirements.txt`:

```text
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
```

---

## Step 5 — Run and Test

### Start the Policy Server

```bash
cd src/server
pip install -r requirements.txt
OC_POLICY_AGENT_TOKEN=<your-token> uvicorn server:app --port 8080 --reload
```

Verify it's up:

```bash
curl http://localhost:8080/health
# → {"status":"ok","phase":1}
```

### Start OpenClaw with the plugin active

```bash
OC_POLICY_AGENT_TOKEN=<your-token> openclaw gateway
```

### Run acceptance tests

**Test 1 — git command should be ALLOWED**

Send OpenClaw a message that causes it to run git:

```
"Run git status in ~/Documents/dev/OC_Policy"
```

Expected:
- Policy Server logs: `[ALLOW] exec: git status`
- OpenClaw executes the command and returns output

**Test 2 — arbitrary exec should be DENIED**

```
"Run ls -la in /tmp"
```

Expected:
- Policy Server logs: `[DENY]  exec: ls -la  (program 'ls' not in allowlist)`
- OpenClaw receives `block: true` and tells the user the action was blocked
- The `ls` command never runs

**Test 3 — Policy Server offline → fail closed**

Stop the server, then ask OpenClaw to run git:

Expected:
- Plugin logs: `[oc-policy] Policy Server unreachable — blocking tool call`
- OpenClaw blocks the command
- No tool executes while the Policy Server is down

---

## Step 6 — Commit

Once all three tests pass:

```bash
git add src/plugin/ src/server/
git commit -m "feat: Phase 1 enforcement plugin and minimal policy server

TypeScript plugin registers before_tool_call hook, POSTs to local
Python server, and returns block:true on deny or server failure.
Python server hardcodes git as allowed, denies all other exec calls.
Fails closed if server is unreachable.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
```

---

## Acceptance Criteria

- [ ] Plugin appears in `openclaw plugins list`
- [ ] `git *` commands execute normally
- [ ] Non-allowlisted `exec` commands are blocked with a clear reason
- [ ] OpenClaw is blocked (not errored) when Policy Server is offline
- [ ] No credentials or tokens appear in any committed file

---

## What Phase 2 Builds On Top Of This

Phase 2 replaces the hardcoded `ALLOWED_PROGRAMS` set in `server.py` with:
- A YAML policy file parser
- The full rule evaluation engine (match + priority + effect)
- REST CRUD endpoints for policies
- Plugin manifest parsing (`security.capabilities`) at install time
