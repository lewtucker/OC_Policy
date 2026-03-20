"""
OC Policy Server — Phase 2.5
Rules from policies.yaml; approvals queue; audit log.
"""
import os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from policy_engine import PolicyEngine
from approvals import ApprovalStore
from audit import AuditLog

app = FastAPI(title="OC Policy Server", version="0.4.0")

AGENT_TOKEN = os.environ["OC_POLICY_AGENT_TOKEN"]
POLICY_FILE = Path(os.environ.get("OC_POLICY_FILE", Path(__file__).parent / "policies.yaml"))

engine    = PolicyEngine(POLICY_FILE)
approvals = ApprovalStore()
audit     = AuditLog()

# ── Static UI ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse(STATIC_DIR / "index.html")


# ── Request / response models ─────────────────────────────────────────────────

class CheckRequest(BaseModel):
    tool: str
    params: dict


class CheckResponse(BaseModel):
    verdict: str
    reason: str | None = None
    approval_id: str | None = None


class RuleIn(BaseModel):
    id: str
    description: str = ""
    effect: str
    priority: int = 0
    match: dict = {}


class ResolveRequest(BaseModel):
    verdict: str          # "allow" | "deny"
    reason: str | None = None


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_agent_token(authorization: str) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


# ── /check — called by the plugin ────────────────────────────────────────────

@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str = Header(...)):
    require_agent_token(authorization)

    effect, reason, rule_id = engine.evaluate(req.tool, req.params)

    approval_id = None
    if effect == "pending" and rule_id:
        record = approvals.create(req.tool, req.params, rule_id)
        approval_id = record.id
        print(f"[PENDING] tool={req.tool!r}  approval_id={approval_id}  rule={rule_id!r}")
    else:
        print(f"[{effect.upper()}] tool={req.tool!r}  params={req.params}  rule={rule_id!r}")

    audit.append(req.tool, req.params, effect, rule_id, reason, approval_id)

    return CheckResponse(verdict=effect, reason=reason, approval_id=approval_id)


# ── /approvals — human approval flow ─────────────────────────────────────────

@app.get("/approvals")
async def list_approvals(authorization: str = Header(...), pending_only: bool = False):
    require_agent_token(authorization)
    records = approvals.list_pending() if pending_only else approvals.list_all()
    return {"approvals": [r.to_dict() for r in records]}


@app.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, authorization: str = Header(...)):
    require_agent_token(authorization)
    record = approvals.get(approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return record.to_dict()


@app.post("/approvals/{approval_id}")
async def resolve_approval(
    approval_id: str,
    body: ResolveRequest,
    authorization: str = Header(...),
):
    require_agent_token(authorization)

    if body.verdict not in ("allow", "deny"):
        raise HTTPException(status_code=400, detail="verdict must be 'allow' or 'deny'")

    record = approvals.resolve(approval_id, body.verdict, body.reason)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    print(f"[RESOLVED] approval_id={approval_id}  verdict={body.verdict!r}  reason={body.reason!r}")
    return record.to_dict()


# ── /audit ────────────────────────────────────────────────────────────────────

@app.get("/audit")
async def get_audit(authorization: str = Header(...), limit: int = 100):
    require_agent_token(authorization)
    return {"entries": [e.to_dict() for e in audit.recent(limit)]}


# ── /policies CRUD ────────────────────────────────────────────────────────────

@app.get("/policies")
async def list_policies(authorization: str = Header(...)):
    require_agent_token(authorization)
    return {"policies": [r.to_dict() for r in engine.rules]}


@app.post("/policies", status_code=201)
async def add_policy(rule: RuleIn, authorization: str = Header(...)):
    require_agent_token(authorization)
    try:
        new_rule = engine.add(rule.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    print(f"[POLICY] added rule '{new_rule.id}'")
    return new_rule.to_dict()


@app.delete("/policies/{rule_id}", status_code=204)
async def delete_policy(rule_id: str, authorization: str = Header(...)):
    require_agent_token(authorization)
    if not engine.remove(rule_id):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    print(f"[POLICY] removed rule '{rule_id}'")


@app.post("/policies/reload")
async def reload_policies(authorization: str = Header(...)):
    require_agent_token(authorization)
    engine.reload()
    print(f"[POLICY] reloaded {len(engine.rules)} rule(s) from disk")
    return {"reloaded": len(engine.rules)}


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "phase": "2.5",
        "rules": len(engine.rules),
        "pending_approvals": len(approvals.list_pending()),
        "audit_entries": len(audit.recent(10000)),
    }
