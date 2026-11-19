// `bun dev`: the handlers Vercel serves from api/, on one local Bun.serve that `bun --hot` reloads in place.

import { GET as claude } from "./api/claude.ts";
import { GET as peer } from "./api/peer.ts";

const server = Bun.serve({
  port: Number(process.env.PORT ?? 3000),
  routes: { "/claude": claude, "/peer": peer, "/api/claude": claude, "/api/peer": peer },
});

console.log(`linear-mcp dev server: ${server.url}claude and ${server.url}peer`);
