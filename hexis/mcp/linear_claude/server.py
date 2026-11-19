"""Local MCP server that drives the Linear GraphQL API as a dedicated "Claude" identity.

Credentials, the token and the GraphQL transport live in `~/.claude/scripts/linear_client.py`, shared
with `scripts/linear_ops.py`: an OAuth2 client_credentials app actor token for the Linear app "Claude"
(scopes read, write, app:assignable, app:mentionable), or a Personal API key as the fallback.

The app cannot be an issue's assignee (Linear accepts `assigneeId` = the app and leaves it null), so
Claude takes work as the DELEGATE; the human is the assignee only when the next step is theirs. Issues
are never deleted here: `cancel_issue` closes one as Canceled with the reason as a comment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import linear_client as client
from linear_client import LinearError, auth_mode, oauth_credentials

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
IDENTIFIER_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)-([0-9]+)")

PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
INBOX_NOISE = ("issueAddedToView", "issueSubscribed")
MENTION_RE = re.compile(r"(?:https://linear\.app/[^/\s]+/profiles/[^\s)\]]+|@\S+)")


def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    return client.graphql(query, variables)


def try_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        return graphql(query, variables)
    except LinearError:
        return None


# --------------------------------------------------------------------------- queries

VIEWER_Q = "query { viewer { id name displayName email admin } }"
ORG_Q = "query { organization { id name urlKey } }"
APP_Q = "query($clientId: String!) { applicationInfo(clientId: $clientId) { id name developer imageUrl } }"
TEAMS_Q = "query { teams(first: 250) { nodes { id key name description private } } }"
PROJECTS_Q = """query($filter: ProjectFilter) {
  projects(first: 250, filter: $filter) {
    nodes { id name slugId url status { name type } lead { name } teams(first: 25) { nodes { id key name } } }
  }
}"""
STATES_Q = """query($teamId: ID!) {
  workflowStates(first: 100, filter: { team: { id: { eq: $teamId } } }) {
    nodes { id name type position description }
  }
}"""
USERS_Q = "query { users(first: 250) { nodes { id name displayName email active app url } } }"

ISSUE_BRIEF_FIELDS = """id identifier title url priority priorityLabel createdAt updatedAt
    state { name type } assignee { name email } delegate { name email } team { key name } project { name }"""
ISSUE_FULL_FIELDS = (
    ISSUE_BRIEF_FIELDS
    + """ description number estimate dueDate branchName startedAt completedAt canceledAt
    creator { name email } parent { identifier title } labels(first: 50) { nodes { name } }"""
)


_cache: dict[str, Any] = {
    "teams": None,
    "users": None,
    "projects": None,
    "states": {},
    "viewer": None,
    "project_statuses": None,
    "labels": None,
}


def reset_cache() -> None:
    _cache.update(
        {
            "teams": None,
            "users": None,
            "projects": None,
            "states": {},
            "viewer": None,
            "project_statuses": None,
            "labels": None,
        }
    )


def is_uuid(value: str) -> bool:
    return bool(UUID_RE.fullmatch(value.strip()))


def viewer() -> dict[str, Any] | None:
    if _cache["viewer"] is None:
        data = try_graphql(VIEWER_Q)
        _cache["viewer"] = (data or {}).get("viewer", False)
    return _cache["viewer"] or None


def all_teams() -> list[dict[str, Any]]:
    if _cache["teams"] is None:
        _cache["teams"] = graphql(TEAMS_Q)["teams"]["nodes"]
    return _cache["teams"]


def all_projects() -> list[dict[str, Any]]:
    if _cache["projects"] is None:
        _cache["projects"] = graphql(PROJECTS_Q, {"filter": None})["projects"]["nodes"]
    return _cache["projects"]


def all_users() -> list[dict[str, Any]]:
    if _cache["users"] is None:
        _cache["users"] = graphql(USERS_Q)["users"]["nodes"]
    return _cache["users"]


def team_states(team_id: str) -> list[dict[str, Any]]:
    if team_id not in _cache["states"]:
        _cache["states"][team_id] = graphql(STATES_Q, {"teamId": team_id})["workflowStates"]["nodes"]
    return _cache["states"][team_id]


# --------------------------------------------------------------------------- name resolution


def describe(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    return "/".join(str(record[k]) for k in keys if record.get(k))


def pick(candidates: list[dict[str, Any]], ref: str, keys: tuple[str, ...], kind: str) -> dict[str, Any]:
    """Resolve a human reference against a list of records: exact match first, then substring."""
    wanted = ref.strip().lower()
    exact = [c for c in candidates if any((c.get(k) or "").lower() == wanted for k in keys)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise LinearError(f"{kind} '{ref}' is ambiguous: {', '.join(describe(c, keys) for c in exact)}")
    partial = [c for c in candidates if any(wanted in (c.get(k) or "").lower() for k in keys)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise LinearError(f"{kind} '{ref}' is ambiguous: {', '.join(describe(c, keys) for c in partial)}")
    raise LinearError(f"No {kind} matches '{ref}'. Known: {', '.join(describe(c, keys) for c in candidates)}")


def resolve_team(ref: str) -> str:
    if is_uuid(ref):
        return ref.strip()
    return pick(all_teams(), ref, ("key", "name"), "team")["id"]


def resolve_project(ref: str, team_id: str | None = None) -> str:
    if is_uuid(ref):
        return ref.strip()
    candidates = all_projects()
    if team_id:
        scoped = [p for p in candidates if any(t["id"] == team_id for t in p.get("teams", {}).get("nodes", []))]
        if scoped:
            candidates = scoped
    return pick(candidates, ref, ("name", "slugId"), "project")["id"]


def resolve_state(team_id: str, ref: str) -> str:
    if is_uuid(ref):
        return ref.strip()
    return pick(team_states(team_id), ref, ("name", "type"), "workflow state")["id"]


def resolve_user(ref: str) -> str:
    ref = ref.strip()
    if ref.lower() in ("me", "self"):
        me = viewer()
        if not me:
            raise LinearError("'me' cannot be resolved: this token has no Linear user (app actor token).")
        return me["id"]
    if is_uuid(ref):
        return ref
    return pick(all_users(), ref, ("email", "name", "displayName"), "user")["id"]


def resolve_issue_id(ref: str) -> str:
    """Accept a UUID or a human identifier such as 'ERG-12'."""
    ref = ref.strip()
    if is_uuid(ref):
        return ref
    match = IDENTIFIER_RE.fullmatch(ref)
    if not match:
        raise LinearError(f"'{ref}' is neither a Linear issue UUID nor an identifier like 'ERG-12'.")
    team_key, number = match.group(1).upper(), int(match.group(2))
    query = """query($key: String!, $number: Float!) {
      issues(first: 2, filter: { team: { key: { eq: $key } }, number: { eq: $number } }) { nodes { id } }
    }"""
    nodes = graphql(query, {"key": team_key, "number": number})["issues"]["nodes"]
    if not nodes:
        raise LinearError(f"No issue {ref} found (team key '{team_key}', number {number}).")
    return nodes[0]["id"]


# --------------------------------------------------------------------------- formatting


def brief(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": issue["identifier"],
        "uuid": issue["id"],
        "title": issue["title"],
        "status": (issue.get("state") or {}).get("name"),
        "priority": issue.get("priorityLabel") or PRIORITY_LABELS.get(cast(int, issue.get("priority"))),
        "assignee": (issue.get("assignee") or {}).get("name"),
        "delegate": (issue.get("delegate") or {}).get("name"),
        "team": (issue.get("team") or {}).get("key"),
        "project": (issue.get("project") or {}).get("name"),
        "url": issue.get("url"),
        "updatedAt": issue.get("updatedAt"),
    }


def full(issue: dict[str, Any]) -> dict[str, Any]:
    out = brief(issue)
    out.update(
        {
            "description": issue.get("description"),
            "number": issue.get("number"),
            "estimate": issue.get("estimate"),
            "dueDate": issue.get("dueDate"),
            "branchName": issue.get("branchName"),
            "createdAt": issue.get("createdAt"),
            "startedAt": issue.get("startedAt"),
            "completedAt": issue.get("completedAt"),
            "canceledAt": issue.get("canceledAt"),
            "creator": (issue.get("creator") or {}).get("name"),
            "parent": (issue.get("parent") or {}).get("identifier"),
            "labels": [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])],
        }
    )
    return out


# --------------------------------------------------------------------------- tools

mcp = MCPServer(
    name="linear-claude",
    instructions=(
        "Linear access under the dedicated 'Claude' identity. Every issue, update and comment "
        "written through these tools is attributed to it, not to the signed-in user. "
        "Teams, projects, workflow states and assignees may be given as a name, a key or a UUID. "
        "Claude takes work as an issue's delegate, never its assignee; the human is assigned only by "
        "`handoff`. Issues are never deleted: `cancel_issue` closes one as Canceled with a reason."
    ),
)


@mcp.tool()
def linear_whoami() -> dict[str, Any]:
    """Show which Linear identity this server writes as, and how it authenticated."""
    mode = auth_mode()
    out: dict[str, Any] = {"auth": "oauth client_credentials (app actor)" if mode == "oauth" else "personal api key"}
    me = viewer()
    if me:
        out["viewer"] = me
        out["writes_as"] = f"{me['name']} <{me['email']}>"
    if mode == "oauth":
        creds = oauth_credentials()
        assert creds  # auth_mode() returning "oauth" means this just succeeded
        app = try_graphql(APP_Q, {"clientId": creds[0]})
        if app:
            out["application"] = app["applicationInfo"]
            out.setdefault("writes_as", f"app actor ({app['applicationInfo']['name']})")
        out.setdefault("writes_as", "app actor (Claude)")
    org = try_graphql(ORG_Q)
    if org:
        out["organization"] = org["organization"]
    out["teams_visible"] = len(all_teams())
    return out


@mcp.tool()
def list_teams() -> list[dict[str, Any]]:
    """List the Linear teams this identity can see, with their key, name and id."""
    return [{"id": t["id"], "key": t["key"], "name": t["name"], "private": t["private"]} for t in all_teams()]


@mcp.tool()
def list_projects(team: str | None = None) -> list[dict[str, Any]]:
    """List Linear projects, optionally only those accessible to one team (name, key or id)."""
    if team is None:
        nodes = all_projects()
    else:
        team_id = resolve_team(team)
        nodes = graphql(PROJECTS_Q, {"filter": {"accessibleTeams": {"some": {"id": {"eq": team_id}}}}})["projects"][
            "nodes"
        ]
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "status": (p.get("status") or {}).get("name"),
            "lead": (p.get("lead") or {}).get("name"),
            "teams": [t["key"] for t in p.get("teams", {}).get("nodes", [])],
            "url": p.get("url"),
        }
        for p in nodes
    ]


@mcp.tool()
def list_issue_statuses(team: str) -> list[dict[str, Any]]:
    """List one team's workflow states - the values `save_issue` accepts as `state`."""
    return [
        {"id": s["id"], "name": s["name"], "type": s["type"], "position": s["position"]}
        for s in sorted(team_states(resolve_team(team)), key=lambda s: s["position"])
    ]


@mcp.tool()
def list_issues(
    project: str | None = None,
    team: str | None = None,
    state: str | None = None,
    assignee: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List issues filtered by project, team, workflow state, assignee and/or a text query."""
    issue_filter: dict[str, Any] = {}
    team_id = resolve_team(team) if team else None
    if team_id:
        issue_filter["team"] = {"id": {"eq": team_id}}
    if project:
        issue_filter["project"] = {"id": {"eq": resolve_project(project, team_id)}}
    if state:
        issue_filter["state"] = {"id": {"eq": state}} if is_uuid(state) else {"name": {"eqIgnoreCase": state}}
    if assignee:
        if assignee.strip().lower() in ("none", "unassigned"):
            issue_filter["assignee"] = {"null": True}
        elif assignee.strip().lower() in ("me", "self"):
            issue_filter["assignee"] = {"isMe": {"eq": True}}
        else:
            issue_filter["assignee"] = {"id": {"eq": resolve_user(assignee)}}
    if query:
        issue_filter["searchableContent"] = {"contains": query}
    gql = f"""query($filter: IssueFilter, $first: Int!) {{
      issues(first: $first, filter: $filter, orderBy: updatedAt) {{ nodes {{ {ISSUE_BRIEF_FIELDS} }} }}
    }}"""
    nodes = graphql(gql, {"filter": issue_filter or None, "first": max(1, min(int(limit), 250))})["issues"]["nodes"]
    return [brief(n) for n in nodes]


@mcp.tool()
def get_issue(id: str) -> dict[str, Any]:
    """Get one issue in full, including its description. `id` is an identifier like 'ERG-12' or a UUID."""
    gql = f"query($id: String!) {{ issue(id: $id) {{ {ISSUE_FULL_FIELDS} }} }}"
    return full(graphql(gql, {"id": resolve_issue_id(id)})["issue"])


@mcp.tool()
def save_issue(
    id: str | None = None,
    team: str | None = None,
    project: str | None = None,
    title: str | None = None,
    description: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    assignee: str | None = None,
    delegate: str | None = None,
    milestone: str | None = None,
    parentId: str | None = None,
    labels: list[str] | None = None,
    addLabels: list[str] | None = None,
    blockedBy: list[str] | None = None,
    blocks: list[str] | None = None,
    relatedTo: list[str] | None = None,
    dueDate: str | None = None,
    estimate: int | None = None,
    cycle: str | None = None,
) -> dict[str, Any]:
    """Create an issue (no `id`; `team` and `title` required) or update the one given by `id`.

    `state` is a workflow state name such as 'In Progress', `assignee` a name, email or UUID,
    `priority` 0 none / 1 urgent / 2 high / 3 medium / 4 low.

    Claude takes work as the `delegate`, never as the assignee: Linear accepts `assigneeId` = an app
    user and leaves it null, so an app given as `assignee` is refused. A new issue is delegated to this
    server's own identity unless `delegate` names someone else or is 'none'. The human is the assignee
    only when the next step is theirs (see `handoff`). `milestone` is a project milestone name or UUID;
    an issue carries one.

    `labels` replaces the issue's labels, `addLabels` only adds; both take label names or UUIDs.
    `dueDate` is 'YYYY-MM-DD', `estimate` the story-point value, `cycle` a cycle number, a cycle
    name, a UUID or 'current' / 'next' / 'previous'. `blockedBy`, `blocks` and `relatedTo` take
    lists of issue identifiers and are written as issue relations after the issue itself is saved;
    the relations created are reported under `relations` in the result.
    """
    updating = bool(id)
    issue_uuid = resolve_issue_id(id) if updating else None
    team_id = resolve_team(team) if team else None

    if not updating:
        if not team_id:
            raise LinearError("Creating an issue needs `team` (name, key or id).")
        if not title:
            raise LinearError("Creating an issue needs `title`.")
    if (state or cycle) and not team_id:
        gql = "query($id: String!) { issue(id: $id) { team { id } } }"
        team_id = graphql(gql, {"id": issue_uuid})["issue"]["team"]["id"]

    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    if priority is not None:
        payload["priority"] = int(priority)
    if project is not None:
        payload["projectId"] = resolve_project(project, team_id)
    if state is not None:
        payload["stateId"] = resolve_state(cast(str, team_id), state)  # ensured above: (state or cycle) implies team_id
    if assignee is not None:
        payload["assigneeId"] = resolve_user(assignee)
        if any(u["id"] == payload["assigneeId"] and u.get("app") for u in all_users()):
            raise LinearError(
                f"'{assignee}' is an app user and cannot be an assignee (Linear leaves it null); pass it as `delegate`."
            )
    if delegate is not None:
        payload["delegateId"] = None if delegate.strip().lower() == "none" else resolve_user(delegate)
    elif not updating and (me := viewer()):
        payload["delegateId"] = me["id"]
    if milestone is not None:
        payload["projectMilestoneId"] = resolve_milestone_id(milestone, payload.get("projectId"))
    if parentId is not None:
        payload["parentId"] = resolve_issue_id(parentId)
    if dueDate is not None:
        payload["dueDate"] = dueDate
    if estimate is not None:
        payload["estimate"] = int(estimate)
    if cycle is not None:
        payload["cycleId"] = resolve_cycle(cast(str, team_id), cycle)  # ensured above: (state or cycle) implies team_id
    if labels is not None:
        payload["labelIds"] = [resolve_label(lbl, team_id) for lbl in labels]
    if addLabels:
        added = [resolve_label(lbl, team_id) for lbl in addLabels]
        if updating and labels is None:
            payload["addedLabelIds"] = added
        else:
            payload["labelIds"] = payload.get("labelIds", []) + [
                lbl for lbl in added if lbl not in payload.get("labelIds", [])
            ]
    wanted_relations = bool(blockedBy or blocks or relatedTo)

    if updating:
        if not payload and not wanted_relations:
            raise LinearError(
                "Nothing to update: pass at least one of title, description, state, priority, assignee, delegate, "
                "milestone, project, parentId, labels, addLabels, dueDate, estimate, cycle, blockedBy, blocks, relatedTo."
            )
        if not payload:
            gql = f"query($id: String!) {{ issue(id: $id) {{ {ISSUE_BRIEF_FIELDS} }} }}"
            result = {"success": True, "issue": graphql(gql, {"id": issue_uuid})["issue"]}
        else:
            gql = (
                "mutation($id: String!, $input: IssueUpdateInput!) "
                f"{{ issueUpdate(id: $id, input: $input) {{ success issue {{ {ISSUE_BRIEF_FIELDS} }} }} }}"
            )
            result = graphql(gql, {"id": issue_uuid, "input": payload})["issueUpdate"]
    else:
        payload["teamId"] = team_id
        gql = (
            "mutation($input: IssueCreateInput!) "
            f"{{ issueCreate(input: $input) {{ success issue {{ {ISSUE_BRIEF_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"input": payload})["issueCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the write as unsuccessful.")
    out = brief(result["issue"])
    if wanted_relations:
        out["relations"] = create_relations(result["issue"]["id"], blocks, blockedBy, relatedTo)
    return out


@mcp.tool()
def add_comment(id: str, body: str) -> dict[str, Any]:
    """Comment on an issue ('ERG-12' or a UUID) under this server's Linear identity."""
    gql = """mutation($input: CommentCreateInput!) {
      commentCreate(input: $input) { success comment { id url createdAt user { name } } }
    }"""
    result = graphql(gql, {"input": {"issueId": resolve_issue_id(id), "body": body}})["commentCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the comment as unsuccessful.")
    comment = result["comment"]
    return {
        "id": comment["id"],
        "url": comment.get("url"),
        "author": (comment.get("user") or {}).get("name"),
        "createdAt": comment.get("createdAt"),
    }


# --------------------------------------------------------------------------- projects, labels, cycles, docs

PROJECT_FIELDS = """id name slugId url description content priority priorityLabel startDate targetDate
    createdAt updatedAt archivedAt status { id name type } lead { id name email }
    teams(first: 50) { nodes { id key name } }"""
PROJECT_Q = f"query($id: String!) {{ project(id: $id) {{ {PROJECT_FIELDS} }} }}"
PROJECT_TEAMS_Q = "query($id: String!) { project(id: $id) { teams(first: 50) { nodes { id key name } } } }"
PROJECT_STATUSES_Q = "query { projectStatuses(first: 100) { nodes { id name type position } } }"
LABEL_FIELDS = "id name color description isGroup parent { id name } team { id key name }"
LABELS_Q = (
    f"query($filter: IssueLabelFilter) {{ issueLabels(first: 250, filter: $filter) {{ nodes {{ {LABEL_FIELDS} }} }} }}"
)
CYCLE_FIELDS = """id number name description startsAt endsAt completedAt progress
    isActive isNext isPrevious isFuture isPast team { id key name }"""
CYCLES_Q = f"query($filter: CycleFilter) {{ cycles(first: 100, filter: $filter) {{ nodes {{ {CYCLE_FIELDS} }} }} }}"
MILESTONE_FIELDS = "id name description targetDate sortOrder progress status project { id name }"
MILESTONES_Q = f"query($filter: ProjectMilestoneFilter) {{ projectMilestones(first: 100, filter: $filter) {{ nodes {{ {MILESTONE_FIELDS} }} }} }}"
COMMENT_FIELDS = "id body url createdAt updatedAt editedAt user { id name email } parent { id }"
COMMENTS_Q = (
    f"query($filter: CommentFilter) {{ comments(first: 100, filter: $filter) {{ nodes {{ {COMMENT_FIELDS} }} }} }}"
)
DOCUMENT_FIELDS = """id title slugId url icon color content createdAt updatedAt
    creator { name } project { id name } team { id key name }"""
DOCUMENTS_Q = (
    f"query($filter: DocumentFilter) {{ documents(first: 100, filter: $filter) {{ nodes {{ {DOCUMENT_FIELDS} }} }} }}"
)
DOCUMENT_Q = f"query($id: String!) {{ document(id: $id) {{ {DOCUMENT_FIELDS} }} }}"
USER_FIELDS = "id name displayName email active admin guest app isMe url timezone title description createdAt"
USER_Q = f"query($id: String!) {{ user(id: $id) {{ {USER_FIELDS} }} }}"

RELATION_M = """mutation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) {
    success issueRelation { id type issue { identifier } relatedIssue { identifier } }
  }
}"""


def all_project_statuses() -> list[dict[str, Any]]:
    if _cache["project_statuses"] is None:
        _cache["project_statuses"] = graphql(PROJECT_STATUSES_Q)["projectStatuses"]["nodes"]
    return _cache["project_statuses"]


def all_labels() -> list[dict[str, Any]]:
    if _cache["labels"] is None:
        _cache["labels"] = graphql(LABELS_Q, {"filter": None})["issueLabels"]["nodes"]
    return _cache["labels"]


def resolve_project_status(ref: str) -> str:
    if is_uuid(ref):
        return ref.strip()
    return pick(all_project_statuses(), ref, ("name", "type"), "project status")["id"]


def resolve_label(ref: str, team_id: str | None = None) -> str:
    if is_uuid(ref):
        return ref.strip()
    candidates = all_labels()
    if team_id:
        scoped = [lbl for lbl in candidates if (lbl.get("team") or {}).get("id") in (team_id, None)]
        if scoped:
            candidates = scoped
    return pick(candidates, ref, ("name",), "label")["id"]


def resolve_cycle(team_id: str, ref: str) -> str:
    ref = str(ref).strip()
    if is_uuid(ref):
        return ref
    nodes = graphql(CYCLES_Q, {"filter": {"team": {"id": {"eq": team_id}}}})["cycles"]["nodes"]
    aliases = {
        "current": "isActive",
        "active": "isActive",
        "next": "isNext",
        "previous": "isPrevious",
        "last": "isPrevious",
    }
    wanted = ref.lower()
    if wanted in aliases:
        for node in nodes:
            if node.get(aliases[wanted]):
                return node["id"]
        raise LinearError(f"This team has no '{ref}' cycle.")
    if wanted.isdigit():
        for node in nodes:
            if int(node["number"]) == int(wanted):
                return node["id"]
        raise LinearError(f"This team has no cycle number {wanted}.")
    return pick(nodes, ref, ("name",), "cycle")["id"]


def resolve_milestone_id(ref: str, project_id: str | None = None) -> str:
    if is_uuid(ref):
        return ref.strip()
    project_filter = {"project": {"id": {"eq": project_id}}} if project_id else None
    nodes = graphql(MILESTONES_Q, {"filter": project_filter})["projectMilestones"]["nodes"]
    return pick(nodes, ref, ("name",), "milestone")["id"]


def resolve_document_id(ref: str) -> str:
    ref = ref.strip()
    if is_uuid(ref):
        return ref
    gql = """query($ref: String!) {
      documents(first: 2, filter: { or: [{ slugId: { eq: $ref } }, { title: { eqIgnoreCase: $ref } }] }) {
        nodes { id title }
      }
    }"""
    nodes = graphql(gql, {"ref": ref})["documents"]["nodes"]
    if not nodes:
        raise LinearError(f"No document matches '{ref}' (tried its slug id and its exact title).")
    if len(nodes) > 1:
        raise LinearError(f"Document '{ref}' is ambiguous: {', '.join(n['title'] for n in nodes)}")
    return nodes[0]["id"]


def project_out(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project["id"],
        "name": project.get("name"),
        "slugId": project.get("slugId"),
        "status": (project.get("status") or {}).get("name"),
        "summary": project.get("description"),
        "description": project.get("content"),
        "priority": project.get("priorityLabel"),
        "lead": (project.get("lead") or {}).get("name"),
        "teams": [t["key"] for t in (project.get("teams") or {}).get("nodes", [])],
        "startDate": project.get("startDate"),
        "targetDate": project.get("targetDate"),
        "archivedAt": project.get("archivedAt"),
        "url": project.get("url"),
        "updatedAt": project.get("updatedAt"),
    }


def label_out(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": label["id"],
        "name": label.get("name"),
        "color": label.get("color"),
        "description": label.get("description"),
        "isGroup": label.get("isGroup"),
        "parent": (label.get("parent") or {}).get("name"),
        "team": (label.get("team") or {}).get("key"),
    }


def cycle_out(cycle: dict[str, Any]) -> dict[str, Any]:
    if cycle.get("isActive"):
        state = "active"
    elif cycle.get("isNext"):
        state = "next"
    elif cycle.get("isPrevious"):
        state = "previous"
    elif cycle.get("isFuture"):
        state = "future"
    elif cycle.get("isPast"):
        state = "past"
    else:
        state = None
    return {
        "id": cycle["id"],
        "number": cycle.get("number"),
        "name": cycle.get("name"),
        "state": state,
        "startsAt": cycle.get("startsAt"),
        "endsAt": cycle.get("endsAt"),
        "completedAt": cycle.get("completedAt"),
        "progress": cycle.get("progress"),
        "team": (cycle.get("team") or {}).get("key"),
    }


def milestone_out(milestone: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": milestone["id"],
        "name": milestone.get("name"),
        "description": milestone.get("description"),
        "targetDate": milestone.get("targetDate"),
        "status": milestone.get("status"),
        "progress": milestone.get("progress"),
        "project": (milestone.get("project") or {}).get("name"),
    }


def user_out(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "name": user.get("name"),
        "displayName": user.get("displayName"),
        "email": user.get("email"),
        "active": user.get("active"),
        "admin": user.get("admin"),
        "guest": user.get("guest"),
        "app": user.get("app"),
        "isMe": user.get("isMe"),
        "title": user.get("title"),
        "timezone": user.get("timezone"),
        "url": user.get("url"),
    }


def comment_out(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment["id"],
        "author": (comment.get("user") or {}).get("name"),
        "body": comment.get("body"),
        "createdAt": comment.get("createdAt"),
        "editedAt": comment.get("editedAt"),
        "parent": (comment.get("parent") or {}).get("id"),
        "url": comment.get("url"),
    }


def document_out(document: dict[str, Any], with_content: bool = True) -> dict[str, Any]:
    out = {
        "id": document["id"],
        "title": document.get("title"),
        "slugId": document.get("slugId"),
        "project": (document.get("project") or {}).get("name"),
        "team": (document.get("team") or {}).get("key"),
        "creator": (document.get("creator") or {}).get("name"),
        "createdAt": document.get("createdAt"),
        "updatedAt": document.get("updatedAt"),
        "url": document.get("url"),
    }
    if with_content:
        out["content"] = document.get("content")
    return out


def create_relations(
    issue_uuid: str,
    blocks: list[str] | None,
    blocked_by: list[str] | None,
    related_to: list[str] | None,
) -> list[dict[str, Any]]:
    """Create issue relations around `issue_uuid`. 'blockedBy' is 'blocks' with the two ends swapped."""
    out: list[dict[str, Any]] = []
    for refs, label, relation_type, inverse in (
        (blocks, "blocks", "blocks", False),
        (blocked_by, "blockedBy", "blocks", True),
        (related_to, "relatedTo", "related", False),
    ):
        for ref in refs or []:
            other = resolve_issue_id(ref)
            first, second = (other, issue_uuid) if inverse else (issue_uuid, other)
            result = graphql(
                RELATION_M, {"input": {"issueId": first, "relatedIssueId": second, "type": relation_type}}
            )["issueRelationCreate"]
            if not result["success"]:
                raise LinearError(f"Linear reported the {label} relation to '{ref}' as unsuccessful.")
            relation = result["issueRelation"]
            out.append(
                {
                    "id": relation["id"],
                    "type": label,
                    "issue": (relation.get("issue") or {}).get("identifier"),
                    "relatedIssue": (relation.get("relatedIssue") or {}).get("identifier"),
                }
            )
    return out


@mcp.tool()
def save_project(
    id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    summary: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    lead: str | None = None,
    addTeams: list[str] | None = None,
    setTeams: list[str] | None = None,
    startDate: str | None = None,
    targetDate: str | None = None,
) -> dict[str, Any]:
    """Create a project (no `id`; `name` and at least one team required) or update the one given by `id`.

    `summary` is the one-line summary under the project title (Linear's `description` field) and
    `description` is the markdown body (Linear's `content` field). `state` is a project status name
    such as 'In Progress', or a status type (backlog / planned / started / paused / completed /
    canceled). `lead` is a name, email or UUID; `setTeams` replaces the project's teams and
    `addTeams` adds to them, each team given as a name, key or UUID. Dates are 'YYYY-MM-DD'.
    """
    updating = bool(id)
    project_id = resolve_project(id) if updating else None

    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if summary is not None:
        payload["description"] = summary
    if description is not None:
        payload["content"] = description
    if priority is not None:
        payload["priority"] = int(priority)
    if lead is not None:
        payload["leadId"] = resolve_user(lead)
    if state is not None:
        payload["statusId"] = resolve_project_status(state)
    if startDate is not None:
        payload["startDate"] = startDate
    if targetDate is not None:
        payload["targetDate"] = targetDate

    set_ids = [resolve_team(t) for t in (setTeams or [])]
    add_ids = [resolve_team(t) for t in (addTeams or [])]

    if updating:
        team_ids = list(set_ids)
        if add_ids:
            if not team_ids:
                current = graphql(PROJECT_TEAMS_Q, {"id": project_id})["project"]["teams"]["nodes"]
                team_ids = [t["id"] for t in current]
            team_ids += [t for t in add_ids if t not in team_ids]
        if team_ids:
            payload["teamIds"] = team_ids
        if not payload:
            raise LinearError(
                "Nothing to update: pass at least one of name, summary, description, state, priority, lead, "
                "addTeams, setTeams, startDate, targetDate."
            )
        gql = (
            "mutation($id: String!, $input: ProjectUpdateInput!) "
            f"{{ projectUpdate(id: $id, input: $input) {{ success project {{ {PROJECT_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"id": project_id, "input": payload})["projectUpdate"]
    else:
        if not name:
            raise LinearError("Creating a project needs `name`.")
        team_ids = set_ids + [t for t in add_ids if t not in set_ids]
        if not team_ids:
            raise LinearError("Creating a project needs `setTeams` (or `addTeams`) with at least one team.")
        payload["teamIds"] = team_ids
        gql = (
            "mutation($input: ProjectCreateInput!) "
            f"{{ projectCreate(input: $input) {{ success project {{ {PROJECT_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"input": payload})["projectCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the write as unsuccessful.")
    _cache["projects"] = None
    return project_out(result["project"])


@mcp.tool()
def get_project(id: str) -> dict[str, Any]:
    """Get one project in full, including its markdown body. `id` is a project name, slug id or UUID."""
    return project_out(graphql(PROJECT_Q, {"id": resolve_project(id)})["project"])


@mcp.tool()
def archive_project(id: str) -> dict[str, Any]:
    """Archive a project. Uses `projectDelete`, which trashes it; `projectArchive` is deprecated and unused."""
    project_id = resolve_project(id)
    gql = "mutation($id: String!) { projectDelete(id: $id) { success entity { id name archivedAt } } }"
    result = graphql(gql, {"id": project_id})["projectDelete"]
    if not result["success"]:
        raise LinearError("Linear reported the archive as unsuccessful.")
    _cache["projects"] = None
    entity = result.get("entity") or {}
    return {"id": entity.get("id", project_id), "name": entity.get("name"), "archivedAt": entity.get("archivedAt")}


@mcp.tool()
def list_issue_labels(team: str | None = None) -> list[dict[str, Any]]:
    """List issue labels: all of them, or only one team's own plus the workspace-wide ones."""
    if team is None:
        return [label_out(lbl) for lbl in all_labels()]
    team_id = resolve_team(team)
    label_filter = {"or": [{"team": {"id": {"eq": team_id}}}, {"team": {"null": True}}]}
    nodes = graphql(LABELS_Q, {"filter": label_filter})["issueLabels"]["nodes"]
    return [label_out(lbl) for lbl in nodes]


@mcp.tool()
def save_issue_label(
    id: str | None = None,
    name: str | None = None,
    color: str | None = None,
    team: str | None = None,
    parentId: str | None = None,
) -> dict[str, Any]:
    """Create an issue label (no `id`; `name` required) or update the one given by `id` (a label name or UUID).

    `color` is a hex string such as '#4cb782'. Without `team` the label is workspace-wide; `team`
    scopes a new label to one team and only narrows the lookup on update, because Linear's update
    input carries no team field. `parentId` puts the label inside a label group.
    """
    updating = bool(id)
    team_id = resolve_team(team) if team else None
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if color is not None:
        payload["color"] = color
    if parentId is not None:
        payload["parentId"] = resolve_label(parentId, team_id)

    if updating:
        if not payload:
            raise LinearError("Nothing to update: pass at least one of name, color, parentId.")
        gql = (
            "mutation($id: String!, $input: IssueLabelUpdateInput!) "
            f"{{ issueLabelUpdate(id: $id, input: $input) {{ success issueLabel {{ {LABEL_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"id": resolve_label(id, team_id), "input": payload})["issueLabelUpdate"]
    else:
        if not name:
            raise LinearError("Creating a label needs `name`.")
        if team_id:
            payload["teamId"] = team_id
        gql = (
            "mutation($input: IssueLabelCreateInput!) "
            f"{{ issueLabelCreate(input: $input) {{ success issueLabel {{ {LABEL_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"input": payload})["issueLabelCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the write as unsuccessful.")
    _cache["labels"] = None
    return label_out(result["issueLabel"])


@mcp.tool()
def list_cycles(team: str) -> list[dict[str, Any]]:
    """List one team's cycles by number. `team` is a name, key or UUID."""
    nodes = graphql(CYCLES_Q, {"filter": {"team": {"id": {"eq": resolve_team(team)}}}})["cycles"]["nodes"]
    return [cycle_out(c) for c in sorted(nodes, key=lambda c: c["number"])]


@mcp.tool()
def list_milestones(project: str) -> list[dict[str, Any]]:
    """List a project's milestones in board order. `project` is a name, slug id or UUID."""
    project_id = resolve_project(project)
    nodes = graphql(MILESTONES_Q, {"filter": {"project": {"id": {"eq": project_id}}}})["projectMilestones"]["nodes"]
    return [milestone_out(m) for m in sorted(nodes, key=lambda m: m["sortOrder"])]


@mcp.tool()
def save_milestone(
    id: str | None = None,
    project: str | None = None,
    name: str | None = None,
    targetDate: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a project milestone (no `id`; `project` and `name` required) or update the one given by `id`.

    `id` is a milestone UUID or, together with `project`, its name. `targetDate` is 'YYYY-MM-DD'.
    """
    updating = bool(id)
    project_id = resolve_project(project) if project else None
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if targetDate is not None:
        payload["targetDate"] = targetDate
    if description is not None:
        payload["description"] = description

    if updating:
        if project_id is not None:
            payload["projectId"] = project_id
        if not payload:
            raise LinearError("Nothing to update: pass at least one of name, targetDate, description, project.")
        gql = (
            "mutation($id: String!, $input: ProjectMilestoneUpdateInput!) "
            f"{{ projectMilestoneUpdate(id: $id, input: $input) {{ success projectMilestone {{ {MILESTONE_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"id": resolve_milestone_id(id, project_id), "input": payload})["projectMilestoneUpdate"]
    else:
        if not project_id:
            raise LinearError("Creating a milestone needs `project` (name, slug id or UUID).")
        if not name:
            raise LinearError("Creating a milestone needs `name`.")
        payload["projectId"] = project_id
        gql = (
            "mutation($input: ProjectMilestoneCreateInput!) "
            f"{{ projectMilestoneCreate(input: $input) {{ success projectMilestone {{ {MILESTONE_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"input": payload})["projectMilestoneCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the write as unsuccessful.")
    return milestone_out(result["projectMilestone"])


@mcp.tool()
def list_users(query: str | None = None) -> list[dict[str, Any]]:
    """List the workspace's users, optionally only those whose name, display name or email contains `query`."""
    nodes = all_users()
    if query:
        wanted = query.strip().lower()
        nodes = [u for u in nodes if any(wanted in (u.get(k) or "").lower() for k in ("name", "displayName", "email"))]
    return [
        {"id": u["id"], "name": u["name"], "displayName": u["displayName"], "email": u["email"], "active": u["active"]}
        for u in nodes
    ]


@mcp.tool()
def get_user(id: str) -> dict[str, Any]:
    """Get one user in full. `id` is a name, email or UUID; 'me' is this server's own Linear identity."""
    return user_out(graphql(USER_Q, {"id": resolve_user(id)})["user"])


@mcp.tool()
def list_comments(issue: str) -> list[dict[str, Any]]:
    """List an issue's comments, oldest first. `issue` is an identifier like 'XX-12' or a UUID."""
    issue_uuid = resolve_issue_id(issue)
    nodes = graphql(COMMENTS_Q, {"filter": {"issue": {"id": {"eq": issue_uuid}}}})["comments"]["nodes"]
    return [comment_out(c) for c in sorted(nodes, key=lambda c: c["createdAt"])]


@mcp.tool()
def list_documents(project: str | None = None) -> list[dict[str, Any]]:
    """List documents without their bodies, optionally only one project's (name, slug id or UUID)."""
    document_filter = {"project": {"id": {"eq": resolve_project(project)}}} if project else None
    nodes = graphql(DOCUMENTS_Q, {"filter": document_filter})["documents"]["nodes"]
    return [document_out(d, with_content=False) for d in nodes]


@mcp.tool()
def get_document(id: str) -> dict[str, Any]:
    """Get one document including its markdown content. `id` is a UUID, a slug id or the exact title."""
    return document_out(graphql(DOCUMENT_Q, {"id": resolve_document_id(id)})["document"])


@mcp.tool()
def save_document(
    id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Create a document (no `id`; `title` required) or update the one given by `id` (UUID, slug id or title).

    `content` is markdown. `project` attaches the document to a project (name, slug id or UUID).
    """
    updating = bool(id)
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    if project is not None:
        payload["projectId"] = resolve_project(project)

    if updating:
        if not payload:
            raise LinearError("Nothing to update: pass at least one of title, content, project.")
        gql = (
            "mutation($id: String!, $input: DocumentUpdateInput!) "
            f"{{ documentUpdate(id: $id, input: $input) {{ success document {{ {DOCUMENT_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"id": resolve_document_id(id), "input": payload})["documentUpdate"]
    else:
        if not title:
            raise LinearError("Creating a document needs `title`.")
        gql = (
            "mutation($input: DocumentCreateInput!) "
            f"{{ documentCreate(input: $input) {{ success document {{ {DOCUMENT_FIELDS} }} }} }}"
        )
        result = graphql(gql, {"input": payload})["documentCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the write as unsuccessful.")
    return document_out(result["document"])


@mcp.tool()
def archive_issue(id: str) -> dict[str, Any]:
    """Archive an issue ('XX-12' or a UUID). Archived issues stay searchable and can be unarchived in Linear."""
    issue_uuid = resolve_issue_id(id)
    gql = "mutation($id: String!) { issueArchive(id: $id) { success entity { id identifier title archivedAt } } }"
    result = graphql(gql, {"id": issue_uuid})["issueArchive"]
    if not result["success"]:
        raise LinearError("Linear reported the archive as unsuccessful.")
    entity = result.get("entity") or {}
    return {
        "id": entity.get("identifier"),
        "uuid": entity.get("id", issue_uuid),
        "title": entity.get("title"),
        "archivedAt": entity.get("archivedAt"),
    }


def ensure_comment(issue_uuid: str, body: str) -> dict[str, Any] | None:
    """Post `body` unless a comment with the same words is already on the issue; None when it was."""
    wanted = " ".join(MENTION_RE.sub(" ", body).split())
    nodes = graphql(COMMENTS_Q, {"filter": {"issue": {"id": {"eq": issue_uuid}}}})["comments"]["nodes"]
    if any(" ".join(MENTION_RE.sub(" ", c.get("body") or "").split()) == wanted for c in nodes):
        return None
    gql = "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id } } }"
    result = graphql(gql, {"input": {"issueId": issue_uuid, "body": body}})["commentCreate"]
    if not result["success"]:
        raise LinearError("Linear reported the comment as unsuccessful.")
    return result["comment"]


def workflow_state_of_type(issue_uuid: str, name: str) -> str:
    gql = "query($id: String!) { issue(id: $id) { team { id } } }"
    team_id = graphql(gql, {"id": issue_uuid})["issue"]["team"]["id"]
    return resolve_state(team_id, name)


@mcp.tool()
def cancel_issue(id: str, reason: str) -> dict[str, Any]:
    """Close an issue as Canceled, with `reason` as a comment. Issues are never deleted.

    `id` is an identifier like 'ERG-12' or a UUID. Running it twice adds no second comment.
    """
    issue_uuid = resolve_issue_id(id)
    comment = ensure_comment(issue_uuid, f"キャンセル: {reason}")
    gql = (
        "mutation($id: String!, $input: IssueUpdateInput!) "
        f"{{ issueUpdate(id: $id, input: $input) {{ success issue {{ {ISSUE_BRIEF_FIELDS} }} }} }}"
    )
    input_ = {"stateId": workflow_state_of_type(issue_uuid, "Canceled")}
    result = graphql(gql, {"id": issue_uuid, "input": input_})["issueUpdate"]
    if not result["success"]:
        raise LinearError("Linear reported the cancel as unsuccessful.")
    out = brief(result["issue"])
    out["comment"] = comment["id"] if comment else "already there"
    return out


@mcp.tool()
def handoff(id: str, text: str, user: str = "", mention: bool = False) -> dict[str, Any]:
    """Hand the next step to a human: comment `text` (with an @mention only if `mention`), make them the assignee and
    keep Claude as the delegate. The assignment is what notifies them; a mention would notify a second time.

    `id` is 'ERG-12' or a UUID; `user` a name, display name, email or UUID - when empty, the env value
    LINEAR_HANDOFF_USER, else 'owner'.
    """
    issue_uuid = resolve_issue_id(id)
    user_id = resolve_user(user or os.environ.get("LINEAR_HANDOFF_USER") or "owner")
    person = next((u for u in all_users() if u["id"] == user_id), {})
    body = f"{person['url']} {text}" if mention and person.get("url") else text
    comment = ensure_comment(issue_uuid, body)
    me = viewer()
    input_: dict[str, Any] = {"assigneeId": user_id}
    if me:
        input_["delegateId"] = me["id"]
    gql = (
        "mutation($id: String!, $input: IssueUpdateInput!) "
        f"{{ issueUpdate(id: $id, input: $input) {{ success issue {{ {ISSUE_BRIEF_FIELDS} }} }} }}"
    )
    result = graphql(gql, {"id": issue_uuid, "input": input_})["issueUpdate"]
    if not result["success"]:
        raise LinearError("Linear reported the handoff as unsuccessful.")
    out = brief(result["issue"])
    out["comment"] = comment["id"] if comment else "already there"
    return out


NOTIFICATIONS_Q = """query($first: Int!, $after: String) {
  notifications(first: $first, after: $after) {
    nodes { id type createdAt readAt archivedAt title actor { name displayName }
      ... on IssueNotification { issue { identifier title } comment { id body user { name displayName } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""
NOTIFICATION_READ_M = """mutation($id: String!, $readAt: DateTime!) {
  notificationUpdate(id: $id, input: { readAt: $readAt }) { success }
}"""


@mcp.tool()
def inbox(markRead: bool = True, allTypes: bool = False) -> list[dict[str, Any]]:
    """This app's unread notifications - @mentions, assignments, delegations, replies on its issues - oldest first.

    The listed ones are marked read unless `markRead` is false, so the next call returns only what is new.
    `issueAddedToView` and `issueSubscribed` are skipped (and left unread) unless `allTypes` is true.
    """
    rows = client.collect(NOTIFICATIONS_Q, {}, "notifications", send=graphql)
    hits = [
        r
        for r in rows
        if not r.get("readAt") and not r.get("archivedAt") and (allTypes or r.get("type") not in INBOX_NOISE)
    ]
    hits.sort(key=lambda r: r.get("createdAt") or "")
    if markRead:
        now = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        for row in hits:
            graphql(NOTIFICATION_READ_M, {"id": row["id"], "readAt": now})
    out = []
    for row in hits:
        comment = row.get("comment") or {}
        author = comment.get("user") or row.get("actor") or {}
        out.append(
            {
                "id": row["id"],
                "type": row.get("type"),
                "issue": (row.get("issue") or {}).get("identifier"),
                "title": row.get("title"),
                "author": author.get("displayName") or author.get("name"),
                "comment": comment.get("body"),
                "commentId": comment.get("id"),
                "createdAt": row.get("createdAt"),
            }
        )
    return out


PIPELINES_Q = """query {
  releasePipelines(first: 50) { nodes { id name slugId type url stages(first: 20) { nodes { id name type } } } }
}"""
RELEASE_FIELDS = "id name version commitSha description url completedAt stage { id name type } pipeline { name }"
RELEASES_Q = f"""query($filter: ReleaseFilter) {{
  releases(first: 100, filter: $filter) {{ nodes {{ {RELEASE_FIELDS} issues(first: 100) {{ nodes {{ id identifier }} }} }} }}
}}"""


def all_pipelines() -> list[dict[str, Any]]:
    return graphql(PIPELINES_Q)["releasePipelines"]["nodes"]


def resolve_pipeline(ref: str) -> dict[str, Any]:
    pipelines = all_pipelines()
    if is_uuid(ref):
        return next(p for p in pipelines if p["id"] == ref.strip())
    return pick(pipelines, ref, ("name", "slugId"), "release pipeline")


def release_out(release: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": release["id"],
        "name": release.get("name"),
        "version": release.get("version"),
        "commitSha": release.get("commitSha"),
        "description": release.get("description"),
        "stage": (release.get("stage") or {}).get("name"),
        "pipeline": (release.get("pipeline") or {}).get("name"),
        "completedAt": release.get("completedAt"),
        "issues": [i["identifier"] for i in (release.get("issues") or {}).get("nodes", [])],
        "url": release.get("url"),
    }


@mcp.tool()
def list_release_pipelines() -> list[dict[str, Any]]:
    """List Linear release pipelines with their stages."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "slugId": p["slugId"],
            "type": p["type"],
            "stages": [s["name"] for s in p["stages"]["nodes"]],
            "url": p["url"],
        }
        for p in all_pipelines()
    ]


@mcp.tool()
def list_releases(pipeline: str) -> list[dict[str, Any]]:
    """List one pipeline's releases with their version, SHA, stage and issues. `pipeline` is a name, slug or UUID."""
    pipe = resolve_pipeline(pipeline)
    nodes = graphql(RELEASES_Q, {"filter": {"pipeline": {"id": {"eq": pipe["id"]}}}})["releases"]["nodes"]
    return [release_out(r) for r in nodes]


@mcp.tool()
def save_release(
    pipeline: str,
    version: str,
    commitSha: str | None = None,
    notes: str | None = None,
    issues: list[str] | None = None,
    stage: str = "completed",
) -> dict[str, Any]:
    """Create the release `version` in `pipeline`, or update the one that already carries that version, and
    link `issues` (identifiers like 'ERG-12') to it. Linking an issue twice does nothing.

    `stage` is a stage name or type (planned / started / completed / canceled); a deploy that has shipped is
    `completed`. `notes` becomes the release description.
    """
    pipe = resolve_pipeline(pipeline)
    stage_id = pick(pipe["stages"]["nodes"], stage, ("name", "type"), "release stage")["id"]
    found = graphql(RELEASES_Q, {"filter": {"pipeline": {"id": {"eq": pipe["id"]}}, "version": {"eq": version}}})[
        "releases"
    ]["nodes"]
    fields: dict[str, Any] = {"stageId": stage_id}
    if commitSha is not None:
        fields["commitSha"] = commitSha
    if notes is not None:
        fields["description"] = notes
    if found:
        release_id = found[0]["id"]
        linked = {i["id"] for i in found[0]["issues"]["nodes"]}
        gql = (
            "mutation($id: String!, $input: ReleaseUpdateInput!) { releaseUpdate(id: $id, input: $input) { success } }"
        )
        result = graphql(gql, {"id": release_id, "input": fields})["releaseUpdate"]
    else:
        linked = set()
        gql = "mutation($input: ReleaseCreateInput!) { releaseCreate(input: $input) { success release { id } } }"
        fields.update({"pipelineId": pipe["id"], "name": f"v{version}", "version": version})
        result = graphql(gql, {"input": fields})["releaseCreate"]
        release_id = (result.get("release") or {}).get("id")
    if not result["success"]:
        raise LinearError("Linear reported the release write as unsuccessful.")
    link = "mutation($input: IssueToReleaseCreateInput!) { issueToReleaseCreate(input: $input) { success } }"
    for ref in issues or []:
        issue_uuid = resolve_issue_id(ref)
        if issue_uuid not in linked:
            graphql(link, {"input": {"issueId": issue_uuid, "releaseId": release_id}})
            linked.add(issue_uuid)
    nodes = graphql(RELEASES_Q, {"filter": {"id": {"eq": release_id}}})["releases"]["nodes"]
    return release_out(nodes[0])


@mcp.tool()
def search_issues(query: str, team: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Full-text search over issues through Linear's own `searchIssues`, optionally inside one team."""
    variables = {
        "term": query,
        "first": max(1, min(int(limit), 250)),
        "teamId": resolve_team(team) if team else None,
    }
    gql = f"""query($term: String!, $first: Int!, $teamId: String) {{
      searchIssues(term: $term, first: $first, teamId: $teamId) {{ nodes {{ {ISSUE_BRIEF_FIELDS} }} }}
    }}"""
    return [brief(n) for n in graphql(gql, variables)["searchIssues"]["nodes"]]


# --------------------------------------------------------------------------- entry point


def check() -> int:
    try:
        mode = auth_mode()
    except LinearError as exc:
        print(f"NG  {exc}", file=sys.stderr)
        return 2
    print(f"auth mode  : {mode}")
    print(f"credentials: {client.credential_source()}")
    try:
        info = linear_whoami()
    except LinearError as exc:
        print(f"NG  {exc}", file=sys.stderr)
        return 1
    if mode == "oauth":
        print(
            f"token      : scope={client._token['scope']} expires_in={client._token['expires_in']}s (kept in memory only)"
        )
    print(f"OK  writes as: {info.get('writes_as')}")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Linear MCP server running under the dedicated 'Claude' identity.")
    parser.add_argument(
        "--check", action="store_true", help="Verify the credentials and print the identity, then exit."
    )
    args = parser.parse_args()
    if args.check:
        raise SystemExit(check())
    try:
        auth_mode()
    except LinearError as exc:
        print(f"linear-claude MCP server cannot start: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    mcp.run()
