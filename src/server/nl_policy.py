"""
Natural Language Policy Authoring — Phase 2
Chat endpoint that interprets plain-English policy requests via Claude.
"""
import os
import json
import re
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import anthropic

router = APIRouter()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

SYSTEM_PROMPT_TEMPLATE = """\
You are a policy authoring assistant for OC Policy, a system that controls what actions an AI agent (OpenClaw) can perform.

## Rule schema

```yaml
id: string          # unique, kebab-case
name: string        # human-friendly label
description: string # what the rule does
result: allow | deny | pending   # verdict
priority: int       # higher = evaluated first
match:
  tool: string      # Bash, WebSearch, WebFetch, Read, Write, Edit, Glob, Grep
  program: string   # first word of shell command (Bash only)
  path: string      # file path with * and ** globs (Read/Write/Edit)
  person: string    # person ID from identities
  group: string     # group name from identities
```

All match conditions are optional and ANDed together. Empty match = matches everything.

## Current policies

{policies_json}

## Known identities

{identities_json}

## Your behavior

1. Interpret the user's plain-English request into one or more rules.
2. If the intent is clear, respond with a JSON block containing the proposed rule(s) and a short explanation.
3. If ambiguous, ask the minimum questions needed — never more than one round at a time.
4. For "block"/"stop"/"prevent" → result: deny. For "allow"/"let"/"permit" → result: allow. For "ask"/"approve"/"require approval" → result: pending.
5. When the user mentions a program (npm, curl, git, rm, etc.), set tool: Bash AND program: <name>.
6. When the user mentions a person or group, validate against the known identities. If not found, say so and list known options.
7. Generate short, descriptive kebab-case IDs. Check they don't collide with existing rule IDs.
8. Set priority based on specificity: person+tool+program (65-75), person+tool (55-65), group+path (55-65), group+tool (45-55), tool+program (30-40), tool-only (15-25), catch-all (0-5).
9. Check for conflicts with existing rules and mention them.
10. For "explain" or "why was X blocked" questions, walk through the rule evaluation logic.
11. For "delete" requests, respond with the rule ID to delete.

## Response format

When proposing a rule, include it in a fenced JSON block labeled PROPOSED_RULE:

```PROPOSED_RULE
{{"action": "add", "rule": {{"id": "deny-curl", "name": "Block curl", "description": "...", "result": "deny", "priority": 35, "match": {{"tool": "Bash", "program": "curl"}}}}}}
```

For multiple rules, use an array:
```PROPOSED_RULE
{{"action": "add_batch", "rules": [...]}}
```

For deletions:
```PROPOSED_RULE
{{"action": "delete", "rule_id": "deny-curl"}}
```

Always include a human-readable explanation outside the JSON block. Keep it concise.
"""


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []   # prior turns: [{"role": "user"|"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    reply: str
    proposed_rules: list[dict] | None = None
    proposed_action: str | None = None   # "add", "add_batch", "delete"
    proposed_rule_id: str | None = None  # for delete actions


def _extract_proposed(text: str) -> tuple[str | None, list[dict] | None, str | None]:
    """Extract PROPOSED_RULE JSON from Claude's response."""
    pattern = r"```PROPOSED_RULE\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None, None, None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None, None, None

    action = data.get("action")
    if action == "add":
        return action, [data["rule"]], None
    elif action == "add_batch":
        return action, data["rules"], None
    elif action == "delete":
        return action, None, data.get("rule_id")
    return None, None, None


def create_chat_handler(engine, identities_store, require_token_fn):
    """Factory that returns the /chat endpoint with access to shared state."""

    @router.post("/chat")
    async def chat(req: ChatRequest, authorization: str = Header(...)):
        require_token_fn(authorization)

        if not ANTHROPIC_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="ANTHROPIC_API_KEY not set — natural language policy authoring is disabled.",
            )

        # Build context from live state
        policies_json = json.dumps(
            [r.to_dict() for r in engine.rules], indent=2
        )
        identities_json = json.dumps(
            [p.to_dict() for p in identities_store.list_all()], indent=2
        )

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            policies_json=policies_json,
            identities_json=identities_json,
        )

        # Build message list from history + new message
        messages = []
        for turn in req.history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": req.message})

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        reply_text = response.content[0].text
        action, rules, rule_id = _extract_proposed(reply_text)

        return ChatResponse(
            reply=reply_text,
            proposed_rules=rules,
            proposed_action=action,
            proposed_rule_id=rule_id,
        )

    return router
