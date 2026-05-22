"""
OC Policy Server — Phase 2.5
Rules from policies.yaml; approvals queue; audit log.
"""
import os
import json
import asyncio
import secrets
import hashlib
import httpx
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from policy_engine import PolicyEngine
from approvals import ApprovalStore
from audit import AuditLog
from identity import IdentityStore
from nl_policy import create_chat_handler
from policy_analyzer import analyze, summarize

_telegram_poll_task: asyncio.Task | None = None

@asynccontextmanager
async def lifespan(app):
    """Start the Telegram polling loop on server startup."""
    global _telegram_poll_task
    _telegram_poll_task = asyncio.create_task(_telegram_poll_loop())
    print("[TELEGRAM] polling loop started")
    yield
    _telegram_poll_task.cancel()
    try:
        await _telegram_poll_task
    except asyncio.CancelledError:
        pass
    print("[TELEGRAM] polling loop stopped")

# ── UI login credentials (optional — if not set, splash page is disabled) ────
UI_PASSWORD    = os.environ.get("OC_POLICY_UI_PASSWORD", "")
SESSION_SECRET = os.environ.get("OC_POLICY_SESSION_SECRET") or secrets.token_hex(32)
UI_AUTH_ENABLED = bool(UI_PASSWORD)

LEGACY_AGENT_TOKEN = os.environ.get("OC_POLICY_AGENT_TOKEN")  # fallback if agent not in identities.yaml
ADMIN_TOKEN    = os.environ.get("OC_POLICY_ADMIN_TOKEN", "")   # UI, CLI, humans managing policies
_server_dir = Path(__file__).parent
# On Vercel the filesystem is read-only; redirect writable files to /tmp
_writable_dir = Path("/tmp") if os.environ.get("VERCEL") else _server_dir
POLICY_FILE    = Path(os.environ.get("OC_POLICY_FILE",   _server_dir   / "policies.yaml"))
AUDIT_FILE     = Path(os.environ.get("OC_AUDIT_FILE",    _writable_dir / "audit.jsonl"))
IDENTITY_FILE  = Path(os.environ.get("OC_IDENTITY_FILE", _server_dir   / "identities.yaml"))
SETTINGS_FILE  = Path(os.environ.get("OC_SETTINGS_FILE", _writable_dir / "settings.json"))

# Telegram bot token: prefer dedicated OC_POLICY_TELEGRAM_TOKEN, fall back to shared TELEGRAM_BOT_TOKEN
TELEGRAM_TOKEN = os.environ.get("OC_POLICY_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")


# ── Server settings (persisted to settings.json) ────────────────────────────

def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2) + "\n")

def get_telegram_token() -> str | None:
    """Return the active Telegram bot token — settings.json overrides env var."""
    settings = _load_settings()
    return settings.get("telegram_bot_token") or TELEGRAM_TOKEN

app = FastAPI(title="OC Policy Server", version="0.5.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="oc_session", max_age=86400)

engine     = PolicyEngine(POLICY_FILE)
approvals  = ApprovalStore()
audit      = AuditLog(log_file=AUDIT_FILE)
identities = IdentityStore(IDENTITY_FILE)

# ── Static UI ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

def _ui_authenticated(request: Request) -> bool:
    if not UI_AUTH_ENABLED:
        return True
    return request.session.get("ui_authenticated") is True

@app.get("/", include_in_schema=False)
async def serve_ui(request: Request):
    if not _ui_authenticated(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/login", include_in_schema=False)
async def login_page(request: Request, error: str = ""):
    if _ui_authenticated(request):
        return RedirectResponse("/", status_code=302)
    html = (STATIC_DIR / "login.html").read_text()
    if error:
        html = html.replace("<!--ERROR-->", '<p class="login-error">Incorrect username or password.</p>')
    return HTMLResponse(html)

@app.post("/login", include_in_schema=False)
async def login_submit(request: Request, password: str = Form(...)):
    if not secrets.compare_digest(password, UI_PASSWORD):
        return RedirectResponse("/login?error=1", status_code=302)
    request.session["ui_authenticated"] = True
    return RedirectResponse("/", status_code=302)

@app.get("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


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

def require_agent_token(authorization: str) -> "Agent | None":
    """Enforcement endpoints only. Returns the resolved Agent, or None for legacy token."""
    from identity import Agent as _Agent
    token = authorization.removeprefix("Bearer ")

    # Try identities.yaml agents first
    agent = identities.resolve_agent(token)
    if agent:
        return agent

    # Fall back to legacy env var token
    if LEGACY_AGENT_TOKEN and token == LEGACY_AGENT_TOKEN:
        return None

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
    findings = analyze(engine.rules, people, groups, audit_entries=audit.recent(10000))
    return findings


# ── NL Policy Chat ────────────────────────────────────────────────────────────
nl_router = create_chat_handler(engine, identities, require_admin_token, run_analysis, audit)
app.include_router(nl_router)


# ── Telegram notification ─────────────────────────────────────────────────────

async def notify_pending(channel_id: str, tool: str, params: dict, approval_id: str) -> None:
    """Send a Telegram message with inline Approve/Deny buttons."""
    token = get_telegram_token()
    if not token:
        return
    # channel_id is stored as "tg:123456789" — strip the prefix for the Bot API
    numeric_id = channel_id.removeprefix("tg:")
    summary = params.get("command") or params.get("query") or params.get("url") or ""
    text = (
        f"⏳ *Approval required*\n\n"
        f"Tool: `{tool}`"
        + (f"\n`{summary[:120]}`" if summary else "")
        + f"\n\nTap a button below, or use the dashboard."
    )
    # Inline keyboard with Approve / Deny buttons
    inline_keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
            {"text": "❌ Deny",    "callback_data": f"deny:{approval_id}"},
        ]]
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": numeric_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": inline_keyboard,
                },
            )
    except Exception as e:
        print(f"[NOTIFY] failed to send Telegram message: {e}")


# ── /check — called by the plugin ────────────────────────────────────────────

@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest, authorization: str = Header(...)):
    agent = require_agent_token(authorization)
    agent_id = agent.id if agent else None

    print(f"[DEBUG] /check body: tool={req.tool!r} channel_id={req.channel_id!r} agent={agent_id!r}")
    subject = None
    if req.channel_id:
        subject = identities.resolve_by_telegram(req.channel_id)

    effect, reason, rule_id = engine.evaluate(req.tool, req.params, subject, agent_id=agent_id)

    subject_id = subject.id if subject else None
    approval_id = None
    if effect == "pending" and rule_id:
        record = approvals.create(req.tool, req.params, rule_id, subject_id=subject_id, agent_id=agent_id)
        approval_id = record.id
        print(f"[PENDING] tool={req.tool!r}  agent={agent_id}  subject={subject_id}  approval_id={approval_id}  rule={rule_id!r}")
        if req.channel_id:
            await notify_pending(req.channel_id, req.tool, req.params, approval_id)
    else:
        print(f"[{effect.upper()}] tool={req.tool!r}  agent={agent_id}  subject={subject_id}  params={req.params}  rule={rule_id!r}")

    audit.append(req.tool, req.params, effect, rule_id, reason, approval_id, subject_id, agent_id=agent_id)

    return CheckResponse(verdict=effect, reason=reason, approval_id=approval_id)


# ── /approvals — human approval flow ─────────────────────────────────────────

@app.get("/approvals")
async def list_approvals(authorization: str = Header(...), pending_only: bool = False):
    require_admin_token(authorization)
    records = approvals.list_pending() if pending_only else approvals.list_all()
    return {"approvals": [r.to_dict() for r in records]}


@app.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, authorization: str = Header(...)):
    # Agent tokens allowed: agents poll this to check if their pending action was resolved
    token = authorization.removeprefix("Bearer ")
    is_agent = identities.is_valid_agent_token(token) or (LEGACY_AGENT_TOKEN and token == LEGACY_AGENT_TOKEN)
    is_admin = token == ADMIN_TOKEN
    if not is_agent and not is_admin:
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

@app.delete("/audit")
async def clear_audit(authorization: str = Header(...)):
    require_admin_token(authorization)
    audit.clear()
    return {"ok": True}


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
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
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
    try:
        if not engine.remove(rule_id):
            raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
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


@app.get("/agents")
async def list_agents(authorization: str = Header(...)):
    require_admin_token(authorization)
    return {"agents": [a.to_dict() for a in identities.list_agents()]}


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


# ── /settings — server configuration ─────────────────────────────────────────

class SettingsUpdate(BaseModel):
    telegram_bot_token: str | None = None
    telegram_poll_interval: int | None = None

@app.get("/settings")
async def get_settings(authorization: str = Header(...)):
    require_admin_token(authorization)
    settings = _load_settings()
    token = settings.get("telegram_bot_token") or ""
    masked = ""
    if token:
        masked = token[:10] + "••••" + token[-4:] if len(token) > 14 else "••••"
    env_token = TELEGRAM_TOKEN or ""
    env_masked = ""
    if env_token:
        env_masked = env_token[:10] + "••••" + env_token[-4:] if len(env_token) > 14 else "••••"
    return {
        "telegram_bot_token_masked": masked,
        "telegram_bot_token_set": bool(token),
        "telegram_bot_token_source": "settings" if settings.get("telegram_bot_token") else ("env" if TELEGRAM_TOKEN else "none"),
        "telegram_env_token_masked": env_masked,
        "telegram_poll_interval": settings.get("telegram_poll_interval", 5),
        "telegram_polling_active": _telegram_poll_task is not None and not _telegram_poll_task.done(),
    }

@app.put("/settings")
async def update_settings(body: SettingsUpdate, authorization: str = Header(...)):
    require_admin_token(authorization)
    settings = _load_settings()
    if body.telegram_bot_token is not None:
        if body.telegram_bot_token == "":
            settings.pop("telegram_bot_token", None)
        else:
            settings["telegram_bot_token"] = body.telegram_bot_token
    if body.telegram_poll_interval is not None:
        settings["telegram_poll_interval"] = max(1, min(60, body.telegram_poll_interval))
    _save_settings(settings)
    print(f"[SETTINGS] updated by admin")
    return {"ok": True}


# ── Telegram polling loop — pulls getUpdates for inline button callbacks ─────

_telegram_update_offset = 0  # tracks the last processed update ID

async def _telegram_poll_loop():
    """Background task: poll Telegram getUpdates for callback_query (button presses)."""
    global _telegram_update_offset
    # Remove any stale webhook so polling works
    token = get_telegram_token()
    if token:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except Exception:
            pass

    while True:
        settings = _load_settings()
        interval = settings.get("telegram_poll_interval", 5)
        token = get_telegram_token()

        if not token:
            await asyncio.sleep(interval)
            continue

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={
                        "offset": _telegram_update_offset,
                        "timeout": 5,
                        "allowed_updates": '["callback_query"]',
                    },
                    timeout=15,
                )
                data = resp.json()

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    _telegram_update_offset = update["update_id"] + 1
                    callback = update.get("callback_query")
                    if callback:
                        await _handle_telegram_callback(callback, token)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[TELEGRAM] poll error: {e}")

        await asyncio.sleep(interval)


async def _handle_telegram_callback(callback: dict, token: str) -> None:
    """Process a single callback_query from an inline keyboard button press."""
    data = callback.get("data", "")
    callback_id = callback.get("id")
    user = callback.get("from", {})
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    message_id = callback.get("message", {}).get("message_id")

    if ":" not in data:
        return
    action, approval_id = data.split(":", 1)

    verdict = "allow" if action == "approve" else "deny" if action == "deny" else None
    if not verdict:
        return

    # Check if caller is an admin
    caller_tg_id = f"tg:{user.get('id', '')}"
    caller = identities.resolve_by_telegram(caller_tg_id)
    if not caller or not caller.is_admin():
        if callback_id:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": callback_id, "text": "⛔ Only admins can approve/deny.", "show_alert": True},
                )
        return

    record = approvals.resolve(approval_id, verdict, reason=f"Via Telegram by {caller.name}")

    if record is None:
        if callback_id:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": callback_id, "text": "Already resolved.", "show_alert": False},
                )
        return

    print(f"[RESOLVED] approval_id={approval_id}  verdict={verdict!r}  via=telegram  user={caller.name}")

    emoji = "✅" if verdict == "allow" else "❌"
    async with httpx.AsyncClient(timeout=5) as client:
        # Dismiss the button spinner
        if callback_id:
            await client.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": f"{emoji} {verdict.title()}d!", "show_alert": False},
            )
        # Replace the message with the decision (removes buttons)
        if chat_id and message_id:
            tool_info = f"Tool: `{record.tool}`"
            summary = record.params.get("command") or record.params.get("query") or record.params.get("url") or ""
            new_text = (
                f"{emoji} *{'Approved' if verdict == 'allow' else 'Denied'}* by {caller.name}\n\n"
                f"{tool_info}"
                + (f"\n`{summary[:120]}`" if summary else "")
            )
            await client.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": new_text,
                    "parse_mode": "Markdown",
                },
            )


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
