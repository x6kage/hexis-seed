import { createIdentityRoute } from "../src/route.js";

const handler = createIdentityRoute({ key: "PEER", label: "Peer", writeTeams: ["PEER"] });

export { handler as GET, handler as POST, handler as DELETE };
