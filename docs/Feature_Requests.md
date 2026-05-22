# Feature Requests

Tracked feature requests for OC Policy. Each has a unique ID for reference.

---

## REQ-1: Telegram-Based Approvals

**Status:** Proposed
**Priority:** High

When a policy rule returns `pending`, the OC Policy server should send a Telegram message to the designated approver (not just the requestor) with details of the action. The approver replies directly in Telegram with yes/no to approve or deny. The server receives the reply via Telegram bot webhook and resolves the approval record, unblocking the polling agent.

**Current state:** The server already sends a Telegram notification when an action is pending, but approval/denial must be done through the web dashboard. This request adds the ability to resolve approvals directly from Telegram.

**Sub-tasks:**
- Dedicated `OC_POLICY_TELEGRAM_TOKEN` env var (separate from nanoclaw's `TELEGRAM_BOT_TOKEN`) so the policy server has its own bot identity
- Settings page in the dashboard UI where the bot token can be viewed/set (stored server-side, not in browser localStorage)
- Telegram webhook listener on the policy server to receive reply messages
- Reply parsing: approver sends "yes"/"no" (or inline keyboard buttons) to resolve the pending approval
- Route approval to the correct `ApprovalRecord` (include approval ID in the notification message)

---

## REQ-2: Network Access Control Proxy

**Status:** Proposed
**Priority:** High

Develop a network proxy that sits in front of OpenClaw/Nanoclaw containers. The proxy inspects outgoing network requests, recognizes patterns (domains, URL paths, HTTP methods), and triggers a policy check with the OC Policy server before allowing the request through. Bake the proxy into the container build so it is always present and cannot be bypassed by the agent.

**Scope:**
- HTTP/HTTPS request interception (forward proxy or iptables + transparent proxy)
- Pattern matching on destination host, path, method, headers
- Integration with `POST /check` on the policy server
- Support for allow/deny/pending verdicts (pending blocks the request until resolved)
- Built into the Docker container image so it's always active

---

## REQ-3: Identity and Secrets Management Integration

**Status:** Proposed
**Priority:** Medium

Replace the current YAML-based identity and token management with integration into a real identity/secrets platform such as 1Password. Tokens, API keys, and identity records would be managed in 1Password and pulled by the policy server at runtime. Benefits: proper secret rotation, audit trail, access controls, and no plaintext tokens in YAML files.

**Scope:**
- 1Password Connect or CLI integration for secret retrieval
- Agent tokens, admin tokens, and person API tokens stored in 1Password
- Identity attributes (groups, Telegram IDs) could remain in YAML or move to 1Password
- Startup flow: policy server fetches secrets from 1Password on boot
