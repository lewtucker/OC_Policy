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
