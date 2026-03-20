"""
OC Policy Server — Phase 2
Rules loaded from policies.yaml; evaluated by the policy engine.
"""
import os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from policy_engine import PolicyEngine

app = FastAPI(title="OC Policy Server", version="0.2.0")

AGENT_TOKEN = os.environ["OC_POLICY_AGENT_TOKEN"]
POLICY_FILE = Path(os.environ.get("OC_POLICY_FILE", Path(__file__).parent / "policies.yaml"))

engine = PolicyEngine(POLICY_FILE)


# ── Request / response models ─────────────────────────────────────────────────

class CheckRequest(BaseModel):
    tool: str
    params: dict


class CheckResponse(BaseModel):
    verdict: str          # "allow" | "deny" | "pending"
    reason: str | None = None
    approval_id: str | None = None


class RuleIn(BaseModel):
    id: str
    description: str = ""
    effect: str           # "allow" | "deny" | "pending"
    priority: int = 0
    match: dict = {}


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_agent_token(authorization: str) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


# ── Core endpoint (called by the plugin) ─────────────────────────────────────

@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str = Header(...)):
    require_agent_token(authorization)

    effect, reason, rule_id = engine.evaluate(req.tool, req.params)

    label = effect.upper()
    print(f"[{label}] tool={req.tool!r}  params={req.params}  rule={rule_id!r}  reason={reason!r}")

    return CheckResponse(verdict=effect, reason=reason)


# ── Policy CRUD (called by the web UI / admin) ────────────────────────────────

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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "phase": 2, "rules": len(engine.rules)}
