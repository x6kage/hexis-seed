/**
 * One identity per route. Everything secret comes from the environment; nothing is read from disk,
 * so no credential ever lives in this repository.
 */

import type { LinearConfig } from "./linear.js";

export type Env = Record<string, string | undefined>;

export interface Identity {
  /** Env suffix and route name, e.g. "CLAUDE" -> /claude. */
  key: string;
  /** How the app is referred to in the server's instructions and refusals. */
  label: string;
  /** Team keys this identity may write to. */
  writeTeams: string[];
}

export interface IdentityEnv {
  config?: LinearConfig;
  callerKey?: string;
  missing: string[];
}

function value(env: Env, name: string): string {
  return (env[name] ?? "").trim();
}

export function envNames(identity: string): { clientId: string; clientSecret: string; callerKey: string } {
  return {
    clientId: `LINEAR_${identity}_CLIENT_ID`,
    clientSecret: `LINEAR_${identity}_CLIENT_SECRET`,
    callerKey: `MCP_KEY_${identity}`,
  };
}

export function readIdentityEnv(identity: Identity, env: Env): IdentityEnv {
  const names = envNames(identity.key);
  const clientId = value(env, names.clientId);
  const clientSecret = value(env, names.clientSecret);
  const callerKey = value(env, names.callerKey);

  const missing: string[] = [];
  if (!clientId) missing.push(names.clientId);
  if (!clientSecret) missing.push(names.clientSecret);
  if (!callerKey) missing.push(names.callerKey);
  if (missing.length) return { missing };

  const config: LinearConfig = { clientId, clientSecret, label: identity.label, writeTeams: identity.writeTeams };
  const handoffUser = value(env, "LINEAR_HANDOFF_USER");
  if (handoffUser) config.handoffUser = handoffUser;
  return { missing, callerKey, config };
}
