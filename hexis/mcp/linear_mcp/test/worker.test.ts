import { describe, expect, it } from "bun:test";
import worker, { createWorkerRoutes } from "../src/worker.js";

const CLAUDE_KEY = "a".repeat(64);
const PEER_KEY = "b".repeat(64);

const ENV = {
  LINEAR_CLAUDE_CLIENT_ID: "the-id",
  LINEAR_CLAUDE_CLIENT_SECRET: "the-secret",
  MCP_KEY_CLAUDE: CLAUDE_KEY,
  MCP_KEY_PEER: PEER_KEY,
  LINEAR_PEER_CLIENT_ID: "peer-id",
  LINEAR_PEER_CLIENT_SECRET: "peer-secret",
};

const INITIALIZE = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } },
};

function rpc(path: string, key?: string): Request {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (key) headers.Authorization = `Bearer ${key}`;
  return new Request(`https://linear-mcp.example.workers.dev${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(INITIALIZE),
  });
}

async function serverName(response: Response): Promise<string> {
  const raw = await response.text();
  const line = raw.split("\n").find((l) => l.startsWith("data:"));
  return JSON.parse(line ? line.slice(5).trim() : raw).result.serverInfo.name;
}

describe("workers entry", () => {
  it("builds exactly the two identity routes", () => {
    expect(Object.keys(createWorkerRoutes(ENV)).sort()).toEqual(["/claude", "/peer"]);
  });

  it("serves each route under its own identity and caller key", async () => {
    const routes = createWorkerRoutes(ENV);
    expect(await serverName(await routes["/claude"]!(rpc("/claude", CLAUDE_KEY)))).toBe("linear-mcp-claude");
    expect(await serverName(await routes["/peer"]!(rpc("/peer", PEER_KEY)))).toBe("linear-mcp-peer");
    expect((await routes["/claude"]!(rpc("/claude", PEER_KEY))).status).toBe(401);
    expect((await routes["/peer"]!(rpc("/peer", CLAUDE_KEY))).status).toBe(401);
  });

  it("routes by path with the env Workers passes to fetch, and 404s everything else", async () => {
    expect(await serverName(await worker.fetch(rpc("/claude", CLAUDE_KEY), ENV))).toBe("linear-mcp-claude");
    expect(await serverName(await worker.fetch(rpc("/peer", PEER_KEY), ENV))).toBe("linear-mcp-peer");
    expect((await worker.fetch(rpc("/claude"), ENV)).status).toBe(401);
    for (const path of ["/", "/x", "/api/claude", "/api/peer", "/claude/x"]) {
      expect((await worker.fetch(rpc(path, CLAUDE_KEY), ENV)).status).toBe(404);
    }
  });
});
