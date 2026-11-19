# linear-claude MCP server

A local stdio MCP server that talks to the Linear GraphQL API as a dedicated **"Claude"** identity,
so issues, updates and comments are attributed to it instead of to the signed-in user. The official
Linear connector (`https://mcp.linear.app/mcp`, OAuth) is left registered and unchanged; use that one
when you want to write under your own name.

Credentials, the token and the GraphQL transport live in `~/.claude/scripts/linear_client.py`, which
`scripts/linear_ops.py` shares. Claude takes work as an issue's **delegate**, never its assignee (an
app user given as `assigneeId` is accepted by Linear and stays null); the human is the assignee only
when the next step is theirs (`handoff`). Nothing here deletes an issue: `cancel_issue` closes it as
Canceled with a reason.

## First thing to run after putting the credentials in place

```
python ~/.claude/mcp/linear_claude/server.py --check
```

It prints the auth mode, where the credentials came from, the token's scope and lifetime, and the
Linear identity that writes. A healthy run ends with `OK  writes as: Claude <...@oauthapp.linear.app>`.
Then restart Claude Code and ask for `linear_whoami`.

## Credentials

Nothing here is in git: `~/.claude/.gitignore` ignores `secrets/`.

1. **OAuth2 client credentials (preferred).** `~/.claude/secrets/linear_claude_oauth.txt`, Client ID
   on the first line, Client Secret on the second (any whitespace separates them; a trailing newline
   is optional). `LINEAR_CLAUDE_CLIENT_ID` / `LINEAR_CLAUDE_CLIENT_SECRET` override the file.
   The app must have **client credentials tokens** switched on in its Linear app settings.
2. **Personal API key (fallback, used only if there are no OAuth credentials).**
   `~/.claude/secrets/linear_claude_api_key.txt`, or `LINEAR_CLAUDE_API_KEY`. Writes are then
   attributed to whichever user issued the key.

With neither, the server exits with status 2 and a message naming both routes.

### What the OAuth path does

`POST https://api.linear.app/oauth/token` as `application/x-www-form-urlencoded` with
`grant_type=client_credentials`, `scope=read,write,app:assignable,app:mentionable`, `client_id`,
`client_secret`. Linear returns an **app actor token** — verified (then with `read,write`)
as `expires_in=2591999` (30 days) —
and GraphQL is then called with `Authorization: Bearer <token>`.

Verified behaviour worth knowing:

- No `actor=app` parameter is sent. `actor` belongs to the `/oauth/authorize` URL of the
  authorization-code flow; a client-credentials token is an app actor token by definition.
- `viewer` **does** work on an app actor token. It returns the app's own Linear user — for this
  workspace `name: "Claude"`, `email: <application-id>@oauthapp.linear.app` — so `linear_whoami`
  reports a real name. `applicationInfo(clientId:)` and `organization` are also queried as a
  cross-check, and any of the three may be absent without failing the call.
- The token is kept in memory for the life of the process only, never written to disk (Linear asks
  callers not to persist it). It is refetched 60 s before expiry and once more on any HTTP 401.
- Requesting a *different* scope revokes the app's existing client-credentials tokens, so `SCOPES`
  in `linear_client.py` must match every other place that requests this app's token
  (`scripts/plane_to_linear.py` uses the same string).

## Tools

| tool | arguments |
| --- | --- |
| `linear_whoami` | — |
| `list_teams` | — |
| `list_projects` | `team?` |
| `list_issue_statuses` | `team` |
| `list_issues` | `project?`, `team?`, `state?`, `assignee?`, `query?`, `limit=50` |
| `search_issues` | `query`, `team?`, `limit=50` |
| `get_issue` | `id` |
| `save_issue` | `id?`, `team?`, `project?`, `title?`, `description?`, `state?`, `priority?`, `assignee?`, `delegate?`, `milestone?`, `parentId?`, `labels?`, `addLabels?`, `blockedBy?`, `blocks?`, `relatedTo?`, `dueDate?`, `estimate?`, `cycle?` |
| `archive_issue` | `id` |
| `cancel_issue` | `id`, `reason` (state Canceled + a comment; never deletes) |
| `handoff` | `id`, `text`, `user` (default: env `LINEAR_HANDOFF_USER`, else `owner`), `mention=true` |
| `inbox` | `markRead=true`, `allTypes=false` |
| `add_comment` | `id`, `body` |
| `list_comments` | `issue` |
| `save_project` | `id?`, `name?`, `description?`, `summary?`, `state?`, `priority?`, `lead?`, `addTeams?`, `setTeams?`, `startDate?`, `targetDate?` |
| `get_project` | `id` |
| `archive_project` | `id` |
| `list_issue_labels` | `team?` |
| `save_issue_label` | `id?`, `name?`, `color?`, `team?`, `parentId?` |
| `list_cycles` | `team` |
| `list_milestones` | `project` |
| `save_milestone` | `id?`, `project?`, `name?`, `targetDate?`, `description?` |
| `list_users` | `query?` |
| `get_user` | `id` (`"me"` = this server's own identity) |
| `list_documents` | `project?` |
| `get_document` | `id` (UUID, slug id or exact title) |
| `save_document` | `id?`, `title?`, `content?`, `project?` |
| `list_release_pipelines` | — |
| `list_releases` | `pipeline` |
| `save_release` | `pipeline`, `version`, `commitSha?`, `notes?`, `issues?`, `stage="completed"` |

- `team`, `project`, `state` and `assignee` accept a name, a key or a UUID; matching is
  case-insensitive, exact before substring, and an ambiguous or unknown reference raises an error
  listing the candidates.
- `id` accepts a human identifier such as `ERG-17` or an issue UUID. Identifiers are resolved with
  `issues(filter: { team: { key: { eq } }, number: { eq } })`.
- `save_issue` updates when `id` is given and creates otherwise (then `team` and `title` are
  required). Only the arguments actually passed are sent to Linear.
- `priority` is `0` none, `1` urgent, `2` high, `3` medium, `4` low.
- `assignee` naming an app user (Claude itself) is refused: pass it as `delegate`. A new issue is
  delegated to this server's identity unless `delegate` names someone else or is `"none"`.
  `"unassigned"` filters for issues with no assignee in `list_issues`.
- `query` maps to `searchableContent: { contains: ... }`. The `issueSearch` query named in older
  docs is deprecated in the current schema and is not used. `search_issues` is the separate
  full-text route through Linear's own `searchIssues(term:)`.
- Every `save_*` tool creates when `id` is absent and updates when it is given; only the arguments
  actually passed are sent.
- On a project, `summary` is Linear's `description` (the one line under the title) and
  `description` is Linear's `content` (the markdown body). `state` is a project status name or a
  status type (`backlog`/`planned`/`started`/`paused`/`completed`/`canceled`), resolved through
  `projectStatuses`. `setTeams` replaces the team list, `addTeams` merges into the current one.
- `archive_project` uses `projectDelete`: `projectArchive` is deprecated in the current schema.
  The project is trashed and can be restored in Linear.
- `save_issue`'s `labels` replaces the label set, `addLabels` maps to `addedLabelIds` on an update
  and is merged into `labelIds` on a create. Labels resolve against the team's own labels plus the
  workspace-wide ones. `cycle` takes a cycle number, a name, a UUID or
  `current`/`next`/`previous`.
- `blockedBy` / `blocks` / `relatedTo` are written with `issueRelationCreate` after the issue
  itself is saved, and reported under `relations` in the result. Linear has no `blocked_by`
  relation type: `blockedBy` is a `blocks` relation with the two ends swapped.
- There is no `delete_issue`: issues are closed as Canceled with a reason (`cancel_issue`), and
  `archive_issue` is the reversible way to hide one. `cancel_issue` and `handoff` post their comment
  only if the same words are not already on the issue, so a rerun adds nothing.
- `handoff` prefixes the comment with the user's profile URL (Linear turns it into a notifying
  @mention; stored verbatim), sets the user as assignee and keeps this identity as delegate in the
  same update (verified live: assignee the user, delegate claude).
- `inbox` reads this app's own `notifications`, returns the unread ones oldest first and marks them
  read; `issueAddedToView` / `issueSubscribed` are skipped and left unread unless `allTypes`.
- Releases (Linear Releases, public GraphQL API): `save_release` finds the release by pipeline and
  `version`, creates it (`releaseCreate`, name `v<version>`) or updates SHA/notes/stage
  (`releaseUpdate`), then links each issue once with `issueToReleaseCreate`.
- Errors come back as the raw GraphQL `errors` array so the cause is not hidden.

## Registration in Claude Code

Registration is Hexis's step. To
register at user scope:

```
claude mcp add --scope user linear-claude -- python ~/.claude/mcp/linear_claude/server.py
```

which appends to `mcpServers` in `~/.claude.json` (the shell has already expanded `~`, so `<home>` below is the absolute home directory):

```json
"linear-claude": {
  "type": "stdio",
  "command": "python",
  "args": ["<home>/.claude/mcp/linear_claude/server.py"],
  "env": {}
}
```

If `claude` is not on PATH, add that object to `mcpServers` in `~/.claude.json` by hand (create the
key if it is missing) and restart Claude Code. `claude mcp list` should then show
`linear-claude: ... - ✔ Connected`.

## Requirements and tests

Python 3.13 with the `mcp` package (`pip install mcp`; built against 2.2.0, where `FastMCP` is named
`MCPServer`). HTTP is stdlib `urllib` only.

```
python ~/.claude/mcp/linear_claude/test_server.py
```

69 offline tests covering credential parsing, token reuse, name resolution, filter construction,
response formatting, delegate vs assignee, cancel, handoff, inbox and releases against canned
GraphQL responses.
