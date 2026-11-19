import { createIdentityRoute } from "../src/route.js";

const handler = createIdentityRoute({ key: "CLAUDE", label: "Claude", writeTeams: ["ERG"] });

export { handler as GET, handler as POST, handler as DELETE };
