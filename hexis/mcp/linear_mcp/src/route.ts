/**
 * One streamable-HTTP MCP route per identity.
 *
 * `mcp-handler` 2.x serves the MCP spec statelessly, so there is no session state and no Redis.
 *
 * The Linear client lives in this module's scope: a warm Vercel invocation reuses its app token and
 * its lookup caches, a cold start refetches both (one client_credentials grant per cold start).
 */

import { createHash, timingSafeEqual } from "node:crypto";
import { createMcpHandler } from "mcp-handler";
import { type Env, type Identity, readIdentityEnv } from "./identity.js";
import { LinearClient } from "./linear.js";
import { instructionsFor, registerTools } from "./tools.js";

export function constantTimeEqual(a: string, b: string): boolean {
  const left = createHash("sha256").update(a, "utf-8").digest();
  const right = createHash("sha256").update(b, "utf-8").digest();
  return timingSafeEqual(left, right);
}

export function bearerToken(request: Request): string | null {
  const header = (request.headers.get("authorization") ?? "").trim();
  const match = /^Bearer[ \t]+(.+)$/i.exec(header);
  return match ? match[1]!.trim() : null; // the group is mandatory, so a match always has it
}

function problem(status: number, reason: string, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify({ error: reason }), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function createIdentityRoute(
  identity: Identity,
  env: Env = process.env,
): (request: Request) => Promise<Response> {
  let client: LinearClient | undefined;

  const mcp = createMcpHandler(
    (server) => {
      registerTools(server, () => client!);
    },
    {
      serverInfo: { name: `linear-mcp-${identity.key.toLowerCase()}`, version: "1.0.0" },
      instructions: instructionsFor(identity.label, identity.writeTeams),
      capabilities: { tools: { listChanged: false } },
    },
  );

  return async function handler(request: Request): Promise<Response> {
    const settings = readIdentityEnv(identity, env);
    if (!settings.config || !settings.callerKey) {
      return problem(
        503,
        `linear-mcp identity '${identity.key.toLowerCase()}' is not configured: ${settings.missing.join(", ")} unset.`,
      );
    }
    const presented = bearerToken(request);
    if (!presented || !constantTimeEqual(presented, settings.callerKey)) {
      return problem(401, "Missing or invalid Authorization: Bearer <caller key>.", {
        "WWW-Authenticate": 'Bearer realm="linear-mcp"',
      });
    }
    if (!client) client = new LinearClient(settings.config);
    return mcp(request);
  };
}
