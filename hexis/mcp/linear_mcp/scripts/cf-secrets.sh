#!/usr/bin/env bash
# Builds the identity secrets for the Worker from the local copies and never prints a value. Vercel cannot be the
# source: `vercel env pull` returns one placeholder for every `Secret`-type variable.
#   scripts/cf-secrets.sh deploy   `wrangler deploy --secrets-file`, then delete the file
#   scripts/cf-secrets.sh dev      write .dev.vars for `wrangler dev` (remove it with `clean`)
#   scripts/cf-secrets.sh clean    delete .dev.vars and the secrets file
# Sources: ~/.claude/secrets/linear_claude_oauth.txt and linear_peer_oauth.txt (client id, then secret),
# ~/.claude/secrets/linear_mcp_peer_key.txt, and the linear-mcp Authorization header in ~/.claude.json.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

SECRETS="$HOME/.claude/secrets"
FILE=.env.workers.secrets

clean() { rm -f "$FILE"; }

oauth() {
  local id secret
  read -r id secret <<<"$(tr -s '[:space:]' ' ' <"$SECRETS/linear_$2_oauth.txt")"
  printf '%s="%s"\n%s="%s"\n' "LINEAR_$1_CLIENT_ID" "$id" "LINEAR_$1_CLIENT_SECRET" "$secret"
}

build() {
  trap clean EXIT
  {
    oauth CLAUDE claude
    printf 'MCP_KEY_CLAUDE="%s"\n' "$(bun -e 'const c = JSON.parse(await Bun.file(process.argv[1]).text()); console.log(c.mcpServers["linear-mcp"].headers.Authorization.replace(/^Bearer\s+/i, "").trim())' "$HOME/.claude.json")"
    printf 'MCP_KEY_PEER="%s"\n' "$(tr -d '[:space:]' <"$SECRETS/linear_mcp_peer_key.txt")"
    if [ -f "$SECRETS/linear_peer_oauth.txt" ]; then oauth PEER peer; fi
  } >"$FILE"
  if grep -q '=""' "$FILE"; then
    echo "an identity secret came out empty; nothing was uploaded" >&2
    exit 1
  fi
  echo "secrets: $(cut -d= -f1 "$FILE" | tr '\n' ' ')(values not shown)"
  if [ ! -f "$SECRETS/linear_peer_oauth.txt" ]; then
    echo "LINEAR_PEER_CLIENT_ID/SECRET not included: /peer answers 503 until 'bunx wrangler secret put' sets both" >&2
  fi
}

case "${1:-}" in
  deploy)
    build
    bunx wrangler deploy --secrets-file "$FILE"
    ;;
  dev)
    build
    cp "$FILE" .dev.vars
    echo "wrote .dev.vars; run 'scripts/cf-secrets.sh clean' when done"
    ;;
  clean)
    clean
    rm -f .dev.vars
    ;;
  *)
    echo "usage: scripts/cf-secrets.sh deploy|dev|clean" >&2
    exit 2
    ;;
esac
