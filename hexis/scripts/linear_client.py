"""Linear GraphQL transport under the dedicated "Claude" OAuth app, shared by linear_ops.py and the MCP server.

Authentication, in order of preference:

1. OAuth2 client credentials of the Linear app "Claude" - LINEAR_CLAUDE_CLIENT_ID /
   LINEAR_CLAUDE_CLIENT_SECRET, else the two lines of ~/.claude/secrets/linear_claude_oauth.txt.
   The token this grant returns is an app actor token, so every issue, update and comment is
   attributed to the app itself.
2. A Personal API key - LINEAR_CLAUDE_API_KEY, else ~/.claude/secrets/linear_claude_api_key.txt.
   Writes are then attributed to the user that issued the key.

The access token is held in memory for the life of the process only and is never written to disk.
`SCOPES` must stay identical everywhere the app's client_credentials grant is requested: a grant with
a different scope revokes the app's existing tokens.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

API_URL = "https://api.linear.app/graphql"
TOKEN_URL = "https://api.linear.app/oauth/token"
SCOPES = "read,write,app:assignable,app:mentionable"
USER_AGENT = "linear-claude/2.0"

SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"
# Another app identity points this at its own two-line client id / secret file.
OAUTH_FILE = (
    Path(os.environ["LINEAR_OAUTH_FILE"])
    if os.environ.get("LINEAR_OAUTH_FILE")
    else SECRETS_DIR / "linear_claude_oauth.txt"
)
KEY_FILE = SECRETS_DIR / "linear_claude_api_key.txt"
CLIENT_ID_ENV = "LINEAR_CLAUDE_CLIENT_ID"
CLIENT_SECRET_ENV = "LINEAR_CLAUDE_CLIENT_SECRET"
KEY_ENV = "LINEAR_CLAUDE_API_KEY"
PAGE_SIZE = 100


class LinearError(Exception):
    """Anything Linear or the local name resolution refuses to do."""


# --------------------------------------------------------------------------- credentials


def oauth_credentials() -> tuple[str, str] | None:
    client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    if OAUTH_FILE.is_file():
        tokens = OAUTH_FILE.read_text(encoding="utf-8").split()
        if len(tokens) >= 2:
            return tokens[0], tokens[1]
        if tokens:
            raise LinearError(
                f"{OAUTH_FILE} holds only one value. Put the OAuth Client ID on line 1 and the Client Secret on line 2."
            )
    return None


def personal_api_key() -> str | None:
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    if KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    return None


def auth_mode() -> str:
    if oauth_credentials():
        return "oauth"
    if personal_api_key():
        return "api_key"
    raise LinearError(
        "No Linear credentials. Either put the OAuth app's Client ID on line 1 and Client Secret on line 2 of "
        f"{OAUTH_FILE} (or set {CLIENT_ID_ENV} / {CLIENT_SECRET_ENV}), or put a Personal API key in "
        f"{KEY_FILE} (or set {KEY_ENV}). The OAuth app needs 'client credentials tokens' switched on in Linear."
    )


def credential_source() -> str:
    if os.environ.get(CLIENT_ID_ENV, "").strip() and os.environ.get(CLIENT_SECRET_ENV, "").strip():
        return f"env {CLIENT_ID_ENV}/{CLIENT_SECRET_ENV}"
    if oauth_credentials():
        return str(OAUTH_FILE)
    if os.environ.get(KEY_ENV, "").strip():
        return f"env {KEY_ENV}"
    return str(KEY_FILE)


_token: dict[str, Any] = {"value": None, "expires_at": 0.0}


def reset_token() -> None:
    _token.update({"value": None, "expires_at": 0.0})


def fetch_token(client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": SCOPES,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise LinearError(
            f"Linear refused the client_credentials grant (HTTP {exc.code}): {detail} "
            "- check the Client ID/Secret and that 'client credentials tokens' is enabled for the app."
        ) from None
    except urllib.error.URLError as exc:
        raise LinearError(f"Cannot reach {TOKEN_URL}: {exc.reason}") from None
    token = payload.get("access_token")
    if not token:
        raise LinearError(f"No access_token in the Linear token response: {json.dumps(payload, ensure_ascii=False)}")
    _token["value"] = token
    _token["expires_in"] = payload.get("expires_in")
    _token["scope"] = payload.get("scope")
    _token["expires_at"] = time.monotonic() + float(payload.get("expires_in", 3600)) - 60
    return token


def access_token() -> str:
    credentials = oauth_credentials()
    if not credentials:
        raise LinearError("OAuth credentials disappeared between checks.")
    if _token["value"] and time.monotonic() < _token["expires_at"]:
        return _token["value"]
    return fetch_token(*credentials)


def auth_header() -> str:
    if auth_mode() == "oauth":
        return f"Bearer {access_token()}"
    return cast(str, personal_api_key())  # auth_mode() returning "api_key" means this just succeeded


# --------------------------------------------------------------------------- transport


def graphql(query: str, variables: dict[str, Any] | None = None, _retried: bool = False) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Authorization": auth_header(), "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 401 and not _retried and auth_mode() == "oauth":
            reset_token()
            return graphql(query, variables, _retried=True)
        raise LinearError(f"Linear returned HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise LinearError(f"Cannot reach {API_URL}: {exc.reason}") from None
    if body.get("errors"):
        raise LinearError(json.dumps(body["errors"], ensure_ascii=False))
    return body["data"]


def try_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        return graphql(query, variables)
    except LinearError:
        return None


def collect(query: str, variables: dict[str, Any] | None, key: str, send: Any = None) -> list[dict[str, Any]]:
    """Read every page of a connection. `query` takes `$first: Int!` and `$after: String` and selects
    `<key>(first: $first, after: $after, ...) { nodes { ... } pageInfo { hasNextPage endCursor } }`."""
    send = send or graphql
    out: list[dict[str, Any]] = []
    after = None
    while True:
        page = send(query, dict(variables or {}, first=PAGE_SIZE, after=after))[key]
        out.extend(page.get("nodes") or [])
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            return out
        after = info["endCursor"]
