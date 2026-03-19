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
def require_agent_token(authorization: str) -> None:
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
