"""
OC Policy Server — Phase 2.5
Rules from policies.yaml; approvals queue; audit log.
"""
import os
import httpx
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from policy_engine import PolicyEngine
from approvals import ApprovalStore
from audit import AuditLog
from identity import IdentityStore
from nl_policy import create_chat_handler
from policy_analyzer import analyze, summarize

app = FastAPI(title="OC Policy Server", version="0.4.0")

AGENT_TOKEN    = os.environ["OC_POLICY_AGENT_TOKEN"]   # enforcement plugin only (nanoclaw)
ADMIN_TOKEN    = os.environ["OC_POLICY_ADMIN_TOKEN"]   # UI, CLI, humans managing policies
POLICY_FILE    = Path(os.environ.get("OC_POLICY_FILE",   Path(__file__).parent / "policies.yaml"))
AUDIT_FILE     = Path(os.environ.get("OC_AUDIT_FILE",    Path(__file__).parent / "audit.jsonl"))
IDENTITY_FILE  = Path(os.environ.get("OC_IDENTITY_FILE", Path(__file__).parent / "identities.yaml"))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")   # optional — enables approval notifications

engine     = PolicyEngine(POLICY_FILE)
approvals  = ApprovalStore()
audit      = AuditLog(log_file=AUDIT_FILE)
identities = IdentityStore(IDENTITY_FILE)

# ── Static UI ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse(STATIC_DIR / "index.html")


# ── Request / response models ─────────────────────────────────────────────────

class CheckRequest(BaseModel):
    tool: str
    params: dict
    channel_id: str | None = None  # Telegram chat JID for identity resolution


class CheckResponse(BaseModel):
    verdict: str
    reason: str | None = None
    approval_id: str | None = None


class RuleIn(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    result: str
    priority: int = 0
    match: dict = {}


class ResolveRequest(BaseModel):
    verdict: str          # "allow" | "deny"
    reason: str | None = None


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_agent_token(authorization: str) -> None:
    """Enforcement endpoints only — nanoclaw plugin. No policy management access."""
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


def require_admin_token(authorization: str) -> "Person":
    """
    Policy management endpoints — resolves token to a Person and checks admin group.
    Falls back to OC_POLICY_ADMIN_TOKEN as a bootstrap superuser (returns synthetic identity).
    """
    from identity import Person as _Person
    token = authorization.removeprefix("Bearer ")

    # Try per-person token first
    person = identities.resolve_by_token(token)
    if person:
        if not person.is_admin():
            raise HTTPException(status_code=403, detail=f"'{person.name}' is not an admin")
        return person

    # Fall back to shared bootstrap admin token
    if token == ADMIN_TOKEN:
        return _Person(id="admin", name="Admin", telegram_id="", groups=["admin"])

    raise HTTPException(status_code=401, detail="Invalid token")


# ── Policy Analysis helper ────────────────────────────────────────────────────

def run_analysis():
    people = [p.id for p in identities.list_all()]
    groups = list({g for p in identities.list_all() for g in p.groups})
    findings = analyze(engine.rules, people, groups)
    return findings


# ── NL Policy Chat ────────────────────────────────────────────────────────────
nl_router = create_chat_handler(engine, identities, require_admin_token, run_analysis, audit)
app.include_router(nl_router)


# ── Telegram notification ─────────────────────────────────────────────────────

async def notify_pending(channel_id: str, tool: str, params: dict, approval_id: str) -> None:
    """Send a Telegram message to the requesting user when their action needs approval."""
    if not TELEGRAM_TOKEN:
        return
    # channel_id is stored as "tg:123456789" — strip the prefix for the Bot API
    numeric_id = channel_id.removeprefix("tg:")
    summary = params.get("command") or params.get("query") or params.get("url") or ""
    text = (
        f"⏳ *Approval required*\n\n"
        f"Tool: `{tool}`"
        + (f"\n`{summary[:120]}`" if summary else "")
        + f"\n\nOpen the policy dashboard to approve or deny."
    )
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": numeric_id, "text": text, "parse_mode": "Markdown"},
            )
    except Exception as e:
        print(f"[NOTIFY] failed to send Telegram message: {e}")


# ── /check — called by the plugin ────────────────────────────────────────────

@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str = Header(...)):
    require_agent_token(authorization)

    print(f"[DEBUG] /check body: tool={req.tool!r} channel_id={req.channel_id!r}")
    subject = None
    if req.channel_id:
        subject = identities.resolve_by_telegram(req.channel_id)

    effect, reason, rule_id = engine.evaluate(req.tool, req.params, subject)

    subject_id = subject.id if subject else None
    approval_id = None
    if effect == "pending" and rule_id:
        record = approvals.create(req.tool, req.params, rule_id)
        approval_id = record.id
        print(f"[PENDING] tool={req.tool!r}  subject={subject_id}  approval_id={approval_id}  rule={rule_id!r}")
        if req.channel_id:
            await notify_pending(req.channel_id, req.tool, req.params, approval_id)
    else:
        print(f"[{effect.upper()}] tool={req.tool!r}  subject={subject_id}  params={req.params}  rule={rule_id!r}")

    audit.append(req.tool, req.params, effect, rule_id, reason, approval_id, subject_id)

    return CheckResponse(verdict=effect, reason=reason, approval_id=approval_id)


# ── /approvals — human approval flow ─────────────────────────────────────────

@app.get("/approvals")
async def list_approvals(authorization: str = Header(...), pending_only: bool = False):
    require_admin_token(authorization)
    records = approvals.list_pending() if pending_only else approvals.list_all()
    return {"approvals": [r.to_dict() for r in records]}


@app.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, authorization: str = Header(...)):
    # Agent token allowed: nanoclaw polls this to check if its pending action was resolved
    if authorization not in (f"Bearer {AGENT_TOKEN}", f"Bearer {ADMIN_TOKEN}"):
        raise HTTPException(status_code=401, detail="Invalid token")
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
    require_admin_token(authorization)

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
    require_admin_token(authorization)
    return {"entries": [e.to_dict() for e in audit.recent(limit)]}


# ── /policies CRUD ────────────────────────────────────────────────────────────

@app.get("/policies")
async def list_policies(authorization: str = Header(...)):
    require_admin_token(authorization)
    return {"policies": [r.to_dict() for r in engine.rules]}


@app.post("/policies", status_code=201)
async def add_policy(rule: RuleIn, authorization: str = Header(...)):
    caller = require_admin_token(authorization)
    try:
        new_rule = engine.add(rule.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    findings = run_analysis()
    warnings = [f.to_dict() for f in findings if f.rule_id == new_rule.id or f.related_id == new_rule.id]
    print(f"[POLICY] added rule '{new_rule.id}' by {caller.id}" + (f" — {len(warnings)} warning(s)" if warnings else ""))
    result = new_rule.to_dict()
    if warnings:
        result["warnings"] = warnings
    return result


@app.put("/policies/{rule_id}")
async def update_policy(rule_id: str, rule: RuleIn, authorization: str = Header(...)):
    caller = require_admin_token(authorization)
    try:
        updated = engine.update(rule_id, rule.model_dump())
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    findings = run_analysis()
    warnings = [f.to_dict() for f in findings if f.rule_id == rule_id or f.related_id == rule_id]
    print(f"[POLICY] updated rule '{rule_id}' by {caller.id}" + (f" — {len(warnings)} warning(s)" if warnings else ""))
    result = updated.to_dict()
    if warnings:
        result["warnings"] = warnings
    return result


@app.delete("/policies/{rule_id}", status_code=204)
async def delete_policy(rule_id: str, authorization: str = Header(...)):
    caller = require_admin_token(authorization)
    if not engine.remove(rule_id):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    print(f"[POLICY] removed rule '{rule_id}' by {caller.id}")


@app.get("/policies/analyze")
async def analyze_policies(authorization: str = Header(...)):
    require_admin_token(authorization)
    findings = run_analysis()
    return {"findings": [f.to_dict() for f in findings], "summary": summarize(findings)}


@app.post("/policies/reload")
async def reload_policies(authorization: str = Header(...)):
    require_admin_token(authorization)
    engine.reload()
    print(f"[POLICY] reloaded {len(engine.rules)} rule(s) from disk")
    return {"reloaded": len(engine.rules)}


# ── /identities ───────────────────────────────────────────────────────────────

@app.get("/identities")
async def list_identities(authorization: str = Header(...)):
    require_admin_token(authorization)
    return {"people": [p.to_dict() for p in identities.list_all()]}


@app.post("/identities/reload")
async def reload_identities(authorization: str = Header(...)):
    require_admin_token(authorization)
    identities.reload()
    print(f"[IDENTITY] reloaded {len(identities.list_all())} person(s) from disk")
    return {"reloaded": len(identities.list_all())}


# ── /me ───────────────────────────────────────────────────────────────────────

@app.get("/me")
async def me(authorization: str = Header(...)):
    caller = require_admin_token(authorization)
    return {"id": caller.id, "name": caller.name, "groups": caller.groups}


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "phase": "3b",
        "rules": len(engine.rules),
        "identities": len(identities.list_all()),
        "pending_approvals": len(approvals.list_pending()),
        "audit_entries": len(audit.recent(10000)),
    }
