// Cloudflare Workers entry: the same two identity routes Vercel serves from api/, with secrets from the Workers `env`.
import type { Env } from "./identity.js";
import { createIdentityRoute } from "./route.js";

type Handler = (request: Request) => Promise<Response>;

export function createWorkerRoutes(env: Env): Record<string, Handler> {
  return {
    "/claude": createIdentityRoute({ key: "CLAUDE", label: "Claude", writeTeams: ["ERG"] }, env),
    "/peer": createIdentityRoute({ key: "PEER", label: "Peer", writeTeams: ["PEER"] }, env),
  };
}

let routes: Record<string, Handler> | undefined;

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    if (!routes) routes = createWorkerRoutes(env);
    const handler = routes[new URL(request.url).pathname];
    return handler ? handler(request) : Promise.resolve(new Response("Not Found", { status: 404 }));
  },
};
