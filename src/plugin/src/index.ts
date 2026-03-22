/**
 * OC Policy Enforcement Plugin for OpenClaw
 *
 * Registers a `before_tool_call` hook that checks every tool call against
 * the OC Policy Server before execution. Supports allow/deny/pending verdicts
 * with polling for human approval.
 *
 * Deploy:
 *   1. Copy the plugin directory into the OpenClaw extensions dir:
 *        scp -r src/plugin/ kylejones@kyle-mac:~/OC2/workspace/data/extensions/oc-policy/
 *      Inside the container this becomes /home/node/.openclaw/extensions/oc-policy/
 *
 *   2. Enable in openclaw.json → plugins.entries:
 *        "oc-policy": {
 *          "enabled": true,
 *          "config": {
 *            "policyServerUrl": "https://lew-mac-2023.tail9284d9.ts.net",
 *            "agentToken": "<OC_POLICY_AGENT_TOKEN>"
 *          }
 *        }
 *
 *   3. Restart the gateway: docker compose restart openclaw-gateway
 */

// ── Types ────────────────────────────────────────────────────────────────────
// Defined locally — no external imports needed. OpenClaw loads plugins via jiti
// and injects the api object at runtime.

interface PluginConfig {
  policyServerUrl: string;
  agentToken: string;
  approvalTimeoutMs?: number;
  channelId?: string | null;
}

interface CheckResponse {
  verdict: "allow" | "deny" | "pending";
  reason?: string;
  approval_id?: string;
}

interface ApprovalResponse {
  verdict: "allow" | "deny" | null;
  reason?: string;
}

interface BeforeToolCallResult {
  params?: Record<string, unknown>;
  block?: boolean;
  blockReason?: string;
}

// ── Policy server communication ──────────────────────────────────────────────

async function checkPolicy(
  config: PluginConfig,
  toolName: string,
  params: Record<string, unknown>,
): Promise<CheckResponse> {
  const res = await fetch(`${config.policyServerUrl}/check`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.agentToken}`,
    },
    body: JSON.stringify({
      tool: toolName,
      params,
      channel_id: config.channelId ?? null,
    }),
  });

  if (!res.ok) {
    throw new Error(`Policy server returned ${res.status}`);
  }

  return (await res.json()) as CheckResponse;
}

async function pollApproval(
  config: PluginConfig,
  approvalId: string,
  log: (msg: string) => void,
): Promise<BeforeToolCallResult> {
  const timeoutMs = config.approvalTimeoutMs ?? 120_000;
  const deadline = Date.now() + timeoutMs;

  log(`Waiting for approval ${approvalId} (timeout ${timeoutMs / 1000}s)`);

  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 500));
    try {
      const res = await fetch(
        `${config.policyServerUrl}/approvals/${approvalId}`,
        { headers: { Authorization: `Bearer ${config.agentToken}` } },
      );
      if (!res.ok) continue;

      const body = (await res.json()) as ApprovalResponse;
      if (body.verdict === "allow") {
        log(`Approval ${approvalId}: allowed`);
        return {};
      }
      if (body.verdict === "deny") {
        log(`Approval ${approvalId}: denied — ${body.reason ?? "no reason"}`);
        return {
          block: true,
          blockReason: body.reason ?? "Denied by approver",
        };
      }
      // null → still pending
    } catch {
      // network error → keep polling
    }
  }

  log(`Approval ${approvalId} timed out`);
  return {
    block: true,
    blockReason: `Approval timed out after ${timeoutMs / 1000} seconds`,
  };
}

// ── Plugin entry point ───────────────────────────────────────────────────────

export default function register(api: any) {
  const rawConfig = (api.pluginConfig ?? {}) as Partial<PluginConfig>;

  const policyServerUrl =
    rawConfig.policyServerUrl ?? process.env.OC_POLICY_SERVER_URL;
  const agentToken =
    rawConfig.agentToken ?? process.env.OC_POLICY_AGENT_TOKEN;

  if (!policyServerUrl) {
    api.logger.warn(
      "[oc-policy] Disabled: no policyServerUrl in config or OC_POLICY_SERVER_URL env",
    );
    return;
  }
  if (!agentToken) {
    api.logger.warn(
      "[oc-policy] Disabled: no agentToken in config or OC_POLICY_AGENT_TOKEN env",
    );
    return;
  }

  const config: PluginConfig = {
    policyServerUrl: policyServerUrl.replace(/\/+$/, ""),
    agentToken,
    approvalTimeoutMs: rawConfig.approvalTimeoutMs ?? 120_000,
    channelId: rawConfig.channelId ?? null,
  };

  api.logger.info(
    `[oc-policy] Enforcement active — server: ${config.policyServerUrl}`,
  );

  // Register before_tool_call at high priority so it runs before other hooks
  api.on(
    "before_tool_call",
    async (
      event: { toolName: string; params: Record<string, unknown> },
      _ctx: any,
    ): Promise<BeforeToolCallResult | void> => {
      const { toolName, params } = event;

      try {
        const result = await checkPolicy(config, toolName, params);
        api.logger.info(`[oc-policy] ${toolName} → ${result.verdict}`);

        if (result.verdict === "allow") return;

        if (result.verdict === "deny") {
          return {
            block: true,
            blockReason: result.reason ?? "Denied by policy",
          };
        }

        if (result.verdict === "pending" && result.approval_id) {
          return await pollApproval(
            config,
            result.approval_id,
            (msg) => api.logger.info(`[oc-policy] ${msg}`),
          );
        }

        return {
          block: true,
          blockReason: "Unexpected response from policy server",
        };
      } catch (err) {
        api.logger.error(`[oc-policy] Server unreachable: ${err}`);
        return {
          block: true,
          blockReason: "OC Policy Server unreachable — failing closed",
        };
      }
    },
    { priority: 100 },
  );
}
