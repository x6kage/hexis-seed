import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { envNames, readIdentityEnv } from "../src/identity.js";
import { bearerToken, constantTimeEqual, createIdentityRoute } from "../src/route.js";
import { TOOL_NAMES } from "../src/tools.js";
import { LinearStub } from "./fixtures.js";

const realFetch = globalThis.fetch;

const CLAUDE_KEY = "a".repeat(64);
const PEER_KEY = "b".repeat(64);

const FULL_ENV = {
  LINEAR_CLAUDE_CLIENT_ID: "the-id",
  LINEAR_CLAUDE_CLIENT_SECRET: "the-secret",
  MCP_KEY_CLAUDE: CLAUDE_KEY,
  MCP_KEY_PEER: PEER_KEY,
};
const BOTH_ENV = { ...FULL_ENV, LINEAR_PEER_CLIENT_ID: "peer-id", LINEAR_PEER_CLIENT_SECRET: "peer-secret" };

const CLAUDE = { key: "CLAUDE", label: "Claude", writeTeams: ["ERG"] };
const PEER = { key: "PEER", label: "Peer", writeTeams: ["PEER"] };

function rpc(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("https://linear-mcp.vercel.app/claude", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers },
    body: JSON.stringify(body),
  });
}

/** Streamable HTTP answers either a JSON body or an SSE stream; read the JSON-RPC message out of both. */
async function message(response: Response): Promise<any> {
  const raw = await response.text();
  if ((response.headers.get("content-type") ?? "").includes("text/event-stream")) {
    const line = raw.split("\n").find((l) => l.startsWith("data:"));
    return JSON.parse(line!.slice(5).trim());
  }
  return JSON.parse(raw);
}

const INITIALIZE = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } },
};

function call(name: string, args: Record<string, unknown>, id = 3) {
  return { jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } };
}

describe("identity env", () => {
  it("names every env var it reads", () => {
    expect(envNames("PEER")).toEqual({
      clientId: "LINEAR_PEER_CLIENT_ID",
      clientSecret: "LINEAR_PEER_CLIENT_SECRET",
      callerKey: "MCP_KEY_PEER",
    });
  });

  it("builds a config carrying the identity's write teams", () => {
    const read = readIdentityEnv(CLAUDE, FULL_ENV);
    expect(read.missing).toEqual([]);
    expect(read.callerKey).toBe(CLAUDE_KEY);
    expect(read.config).toEqual({
      clientId: "the-id",
      clientSecret: "the-secret",
      label: "Claude",
      writeTeams: ["ERG"],
    });
  });

  it("lists every missing variable and yields no config", () => {
    const read = readIdentityEnv(PEER, FULL_ENV);
    expect(read.config).toBeUndefined();
    expect(read.missing).toEqual(["LINEAR_PEER_CLIENT_ID", "LINEAR_PEER_CLIENT_SECRET"]);
  });

  it("treats a whitespace-only value as unset", () => {
    const read = readIdentityEnv(CLAUDE, { ...FULL_ENV, LINEAR_CLAUDE_CLIENT_SECRET: "   " });
    expect(read.missing).toEqual(["LINEAR_CLAUDE_CLIENT_SECRET"]);
  });
});

describe("caller auth", () => {
  it("compares keys in constant time, including unequal lengths", () => {
    expect(constantTimeEqual(CLAUDE_KEY, CLAUDE_KEY)).toBe(true);
    expect(constantTimeEqual(CLAUDE_KEY, PEER_KEY)).toBe(false);
    expect(constantTimeEqual(CLAUDE_KEY, "short")).toBe(false);
  });

  it("reads the bearer token case-insensitively and not otherwise", () => {
    expect(bearerToken(new Request("https://x/", { headers: { authorization: "bearer  tok " } }))).toBe("tok");
    expect(bearerToken(new Request("https://x/", { headers: { authorization: "Basic tok" } }))).toBeNull();
    expect(bearerToken(new Request("https://x/"))).toBeNull();
  });

  it("401s a request with no Authorization header", async () => {
    const response = await createIdentityRoute(CLAUDE, FULL_ENV)(rpc(INITIALIZE));
    expect(response.status).toBe(401);
    expect(response.headers.get("WWW-Authenticate")).toContain("Bearer");
    expect(await response.json()).toEqual({ error: "Missing or invalid Authorization: Bearer <caller key>." });
  });

  it("401s the Peer key on /claude", async () => {
    const response = await createIdentityRoute(
      CLAUDE,
      BOTH_ENV,
    )(rpc(INITIALIZE, { Authorization: `Bearer ${PEER_KEY}` }));
    expect(response.status).toBe(401);
  });

  it("401s the Claude key on /peer", async () => {
    const response = await createIdentityRoute(
      PEER,
      BOTH_ENV,
    )(rpc(INITIALIZE, { Authorization: `Bearer ${CLAUDE_KEY}` }));
    expect(response.status).toBe(401);
  });

  it("401s a GET as well", async () => {
    const response = await createIdentityRoute(CLAUDE, FULL_ENV)(new Request("https://linear-mcp.vercel.app/claude"));
    expect(response.status).toBe(401);
  });
});

describe("unconfigured identity", () => {
  it("503s with a one-line reason naming the unset variables", async () => {
    const response = await createIdentityRoute(
      PEER,
      FULL_ENV,
    )(rpc(INITIALIZE, { Authorization: `Bearer ${PEER_KEY}` }));
    expect(response.status).toBe(503);
    const body = (await response.json()) as any;
    expect(body.error).toBe(
      "linear-mcp identity 'peer' is not configured: LINEAR_PEER_CLIENT_ID, LINEAR_PEER_CLIENT_SECRET unset.",
    );
  });

  it("503s before the caller key is checked, so the reason is always visible", async () => {
    expect((await createIdentityRoute(PEER, FULL_ENV)(rpc(INITIALIZE))).status).toBe(503);
  });

  it("503s when only the caller key is missing", async () => {
    const env = { ...FULL_ENV, MCP_KEY_CLAUDE: undefined };
    const response = await createIdentityRoute(CLAUDE, env)(rpc(INITIALIZE, { Authorization: `Bearer ${CLAUDE_KEY}` }));
    expect(response.status).toBe(503);
    expect(((await response.json()) as any).error).toContain("MCP_KEY_CLAUDE");
  });
});

describe("mcp handler", () => {
  let stub: LinearStub;

  beforeEach(() => {
    stub = new LinearStub();
    globalThis.fetch = stub.fetch as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("initializes with the identity's server info and instructions, without calling Linear", async () => {
    const response = await createIdentityRoute(
      CLAUDE,
      FULL_ENV,
    )(rpc(INITIALIZE, { Authorization: `Bearer ${CLAUDE_KEY}` }));
    expect(response.status).toBe(200);
    const body = await message(response);
    expect(body.result.serverInfo.name).toBe("linear-mcp-claude");
    expect(body.result.instructions).toContain("dedicated 'Claude' identity");
    expect(body.result.instructions).toContain("Writes are limited to team ERG");
    expect(stub.calls).toEqual([]);
  });

  it("lists the thirty tools of the Python spec on both routes", async () => {
    expect(TOOL_NAMES.length).toBe(30);
    for (const [identity, key] of [
      [CLAUDE, CLAUDE_KEY],
      [PEER, PEER_KEY],
    ] as const) {
      const route = createIdentityRoute(identity, BOTH_ENV);
      const response = await route(
        rpc({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }, { Authorization: `Bearer ${key}` }),
      );
      const body = await message(response);
      expect(body.result.tools.map((t: any) => t.name).sort()).toEqual([...TOOL_NAMES].sort());
    }
  });

  it("runs a tool under the route's own credentials", async () => {
    const route = createIdentityRoute(PEER, BOTH_ENV);
    const response = await route(rpc(call("list_teams", {}), { Authorization: `Bearer ${PEER_KEY}` }));
    const body = await message(response);
    expect(body.result.isError).toBeFalsy();
    expect(JSON.parse(body.result.content[0].text).map((t: any) => t.key)).toEqual(["APP", "XX", "PEER"]);
    expect(stub.calls[0]).toBeDefined();
    expect(stub.calls[0]!.form!.get("client_id")).toBe("peer-id");
  });

  it("keeps one token per identity across warm invocations", async () => {
    const route = createIdentityRoute(CLAUDE, FULL_ENV);
    const auth = { Authorization: `Bearer ${CLAUDE_KEY}` };
    await route(rpc(call("list_teams", {}), auth));
    await route(rpc(call("list_users", {}), auth));
    expect(stub.tokenCalls).toBe(1);
  });

  it("returns the write-team refusal as a tool error, not an HTTP failure", async () => {
    const route = createIdentityRoute(CLAUDE, FULL_ENV);
    const response = await route(
      rpc(call("add_comment", { id: "PEER-5", body: "hi" }), { Authorization: `Bearer ${CLAUDE_KEY}` }),
    );
    expect(response.status).toBe(200);
    const body = await message(response);
    expect(body.result.isError).toBe(true);
    expect(body.result.content[0].text).toContain("Claude writes only to team ERG; issue PEER-5 belongs to PEER.");
    expect(stub.matching("commentCreate")).toEqual([]);
  });
});

const MODERN_META = {
  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
  "io.modelcontextprotocol/clientInfo": { name: "test", version: "0" },
  "io.modelcontextprotocol/clientCapabilities": {},
};

function modern(id: number, method: string): Request {
  return rpc(
    { jsonrpc: "2.0", id, method, params: { _meta: MODERN_META } },
    { Authorization: `Bearer ${CLAUDE_KEY}`, "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method },
  );
}

async function readWithin(response: Response, ms: number): Promise<string> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`response body still open after ${ms} ms`)), ms);
  });
  try {
    return await Promise.race([response.text(), late]);
  } finally {
    clearTimeout(timer);
  }
}

describe("every response ends once its reply is written", () => {
  const auth = { Authorization: `Bearer ${CLAUDE_KEY}` };
  const cases: [string, () => Request, number][] = [
    ["2025 initialize", () => rpc(INITIALIZE, auth), 200],
    ["2025 notifications/initialized", () => rpc({ jsonrpc: "2.0", method: "notifications/initialized" }, auth), 202],
    ["2025 tools/list", () => rpc({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }, auth), 200],
    ["2025 ping", () => rpc({ jsonrpc: "2.0", id: 3, method: "ping" }, auth), 200],
    ["2026-07-28 server/discover", () => modern(1, "server/discover"), 200],
    ["2026-07-28 tools/list", () => modern(2, "tools/list"), 200],
  ];

  for (const [name, request, status] of cases) {
    it(`closes ${name} within 2 s with ${status}`, async () => {
      const response = await createIdentityRoute(CLAUDE, FULL_ENV)(request());
      expect(response.status).toBe(status);
      const raw = await readWithin(response, 2000);
      if (status === 202) expect(raw).toBe("");
      else expect(raw).toContain('"result"');
    });
  }

  it("advertises no tool-list changes, so a 2026-07-28 client opens no subscriptions/listen stream", async () => {
    const response = await createIdentityRoute(CLAUDE, FULL_ENV)(modern(1, "server/discover"));
    const body = JSON.parse(await readWithin(response, 2000));
    expect(body.result.capabilities.tools).toEqual({ listChanged: false });
  });
});
