"""Project updates, saved views, issue templates and the team home for `linear_ops`, registered as its subcommands.

Every command here works on a team or a Linear project rather than on one issue, so it takes the config instead of a
`Project`. The transport and the errors come from the `linear_ops` module passed to `register`, so the commands
follow whatever `gql` that module holds at call time.
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

HEALTH = ("onTrack", "atRisk", "offTrack")
WAITING_MARK = "待ち:"

Q_PROJECT_LAST_UPDATE = "query ProjectLastUpdate($id: String!) { project(id: $id) { lastUpdate { body health url } } }"
Q_VIEWS = """query CustomViews($first: Int!, $after: String) {
  customViews(first: $first, after: $after) {
    nodes { id name slugId shared filterData team { id key } }
    pageInfo { hasNextPage endCursor }
  }
}"""
Q_TEMPLATES = "query Templates { templates { id name type content team { id key } } }"
Q_TEAM_DESCRIPTION = "query TeamDescription($id: String!) { team(id: $id) { id key description } }"
Q_TEAM_DOCUMENTS = """query TeamDocuments($filter: DocumentFilter) {
  documents(first: 100, filter: $filter) { nodes { id title content sortOrder url } }
}"""

M_PROJECT_UPDATE_CREATE = """mutation ProjectUpdateCreate($input: ProjectUpdateCreateInput!) {
  projectUpdateCreate(input: $input) { success projectUpdate { id url health } }
}"""
M_VIEW_CREATE = """mutation CustomViewCreate($input: CustomViewCreateInput!) {
  customViewCreate(input: $input) { success customView { id name slugId shared team { id key } } }
}"""
M_TEMPLATE_CREATE = """mutation TemplateCreate($input: TemplateCreateInput!) {
  templateCreate(input: $input) { success template { id name type team { id key } } }
}"""

M_TEAM_UPDATE = """mutation TeamUpdate($id: String!, $input: TeamUpdateInput!) {
  teamUpdate(id: $id, input: $input) { success team { id key description } }
}"""
M_DOCUMENT_CREATE = """mutation DocumentCreate($input: DocumentCreateInput!) {
  documentCreate(input: $input) { success document { id title url } }
}"""
M_DOCUMENT_UPDATE = """mutation DocumentUpdate($id: String!, $input: DocumentUpdateInput!) {
  documentUpdate(id: $id, input: $input) { success document { id title url } }
}"""
M_LINK_CREATE = """mutation EntityExternalLinkCreate($input: EntityExternalLinkCreateInput!) {
  entityExternalLinkCreate(input: $input) { success entityExternalLink { id label url sortOrder } }
}"""

TEMPLATE_SECTIONS = {
    "parent": ("背景", "要件", "受け入れ条件", "範囲外", "想定 tier", "見積り"),
    "agent-run": ("依頼", "証拠", "結果", "判断と不確かさ"),
}


def open_states(ops: ModuleType) -> dict[str, Any]:
    return {"state": {"type": {"nin": list(ops.CLOSED_TYPES)}}}


def view_presets(ops: ModuleType, team_id: str, user_id: str) -> dict[str, dict[str, Any]]:
    """The saved filters by name. Dates stay ISO 8601 durations, which Linear evaluates against now on every read."""
    team = {"team": {"id": {"eq": team_id}}}
    waiting = {"or": [{"assignee": {"id": {"eq": user_id}}}, {"description": {"contains": WAITING_MARK}}]}
    return {
        "waiting-on-user": {"and": [team, waiting, open_states(ops)]},
        "in-progress": {"and": [team, {"state": {"type": {"eq": "started"}}}]},
        "this-week": {"and": [team, {"updatedAt": {"gte": "-P7D"}}, open_states(ops)]},
    }


def template_markdown(kind: str) -> str:
    return "\n\n".join(f"## {heading}\n\n" for heading in TEMPLATE_SECTIONS[kind]).rstrip() + "\n"


def team_id(ops: ModuleType, config: dict[str, Any], key: str) -> str:
    """A team the config allows writing to, by key; anything outside write_teams is refused."""
    key = key.upper()
    writable = [t.upper() for t in config.get("write_teams") or []]
    if key not in writable:
        raise ops.OpsError(f"Team {key} is not in write_teams ({', '.join(writable)}); refusing.")
    configured = (config.get("teams") or {}).get(key)
    if configured:
        return configured
    for team in ops.gql(ops.Q_TEAMS)["teams"]["nodes"]:
        if team["key"].upper() == key:
            return team["id"]
    raise ops.OpsError(f"No team with key '{key}'.")


def linear_project(ops: ModuleType, config: dict[str, Any], name: str) -> dict[str, Any]:
    """A Linear project by a configured project key, its Linear name or its slugId, on a team the config may write."""
    wanted = ((config.get("projects") or {}).get(name) or {}).get("linear_project", name)
    for project in ops.gql(ops.Q_PROJECTS)["projects"]["nodes"]:
        if project["name"].lower() == wanted.lower() or project.get("slugId") == wanted:
            keys = {t["key"].upper() for t in (project.get("teams") or {}).get("nodes", [])}
            writable = {t.upper() for t in config.get("write_teams") or []}
            if not keys & writable:
                raise ops.OpsError(f"Project {project['name']} is on {', '.join(sorted(keys))}, not in write_teams.")
            return project
    raise ops.OpsError(f"No Linear project '{wanted}'.")


def view_url(config: dict[str, Any], view: dict[str, Any]) -> str:
    return f"https://linear.app/{config['workspace']}/view/{view['slugId']}"


# --------------------------------------------------------------------------- commands


def cmd_project_update(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body
    if not body:
        raise ops.OpsError("project-update needs --body or --body-file")
    project = linear_project(ops, config, args.target)
    last = (ops.gql(Q_PROJECT_LAST_UPDATE, {"id": project["id"]})["project"] or {}).get("lastUpdate") or {}
    if last.get("health") == args.health and ops.normalize(last.get("body")) == ops.normalize(body):
        print(f"skip   {project['name']} the latest update already says this ({last.get('url')})")
        return 0
    payload = {"projectId": project["id"], "health": args.health, "body": body}
    update = ops.write(M_PROJECT_UPDATE_CREATE, {"input": payload}, "projectUpdateCreate")["projectUpdate"]
    print(f"update {project['name']} [{args.health}]")
    print(update["url"])
    return 0


def cmd_view_new(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    team = team_id(ops, config, args.team)
    presets = view_presets(ops, team, config["user"]["id"])
    if args.filter in presets:
        filter_data = presets[args.filter]
    else:
        try:
            filter_data = json.loads(args.filter)
        except json.JSONDecodeError:
            raise ops.OpsError(f"--filter is neither a preset ({', '.join(presets)}) nor IssueFilter JSON.") from None
    name = args.name.strip()
    existing = next((v for v in ops.collect(Q_VIEWS, {}, "customViews") if v["name"].strip() == name), None)
    if existing:
        print(f"exists view {name}")
        print(view_url(config, existing))
        return 0
    payload: dict[str, Any] = {"name": name, "teamId": team, "filterData": filter_data, "shared": True}
    if args.project:
        payload["projectId"] = linear_project(ops, config, args.project)["id"]
    if args.description:
        payload["description"] = args.description
    view = ops.write(M_VIEW_CREATE, {"input": payload}, "customViewCreate")["customView"]
    print(f"create view {name}")
    print(view_url(config, view))
    return 0


def cmd_view_list(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    views = ops.collect(Q_VIEWS, {}, "customViews")
    for view in sorted(views, key=lambda v: v["name"]):
        team = (view.get("team") or {}).get("key") or "-"
        shared = "shared" if view.get("shared") else "personal"
        print(f"{team:<4} {shared:<8} {view['name']} {view_url(config, view)}")
    print(f"{len(views)} view(s)")
    return 0


def cmd_template_new(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    team = team_id(ops, config, args.team)
    name = args.name.strip()
    rows = ops.gql(Q_TEMPLATES)["templates"]
    existing = next(
        (t for t in rows if t["name"].strip() == name and (t.get("team") or {}).get("id") == team),
        None,
    )
    if existing:
        print(f"exists template {name}")
        print(existing["id"])
        return 0
    data = {"title": "", "description": template_markdown(args.kind)}
    payload = {"type": "issue", "teamId": team, "name": name, "templateData": json.dumps(data, ensure_ascii=False)}
    template = ops.write(M_TEMPLATE_CREATE, {"input": payload}, "templateCreate")["template"]
    print(f"create template {name} ({args.kind})")
    print(template["id"])
    return 0


def cmd_template_list(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    rows = ops.gql(Q_TEMPLATES)["templates"]
    for row in sorted(rows, key=lambda t: (t.get("type") or "", t["name"])):
        team = (row.get("team") or {}).get("key") or "-"
        body = "body" if row.get("content") else "no-body"
        print(f"{row['id']} {row.get('type') or '-':<14} {team:<4} {body:<7} {row['name']}")
    print(f"{len(rows)} template(s)")
    return 0


def body_text(ops: ModuleType, args: argparse.Namespace, command: str) -> str:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body
    if not body:
        raise ops.OpsError(f"{command} needs --body or --body-file")
    return body


def team_documents(ops: ModuleType, team: str) -> list[dict[str, Any]]:
    return ops.gql(Q_TEAM_DOCUMENTS, {"filter": {"team": {"id": {"eq": team}}}})["documents"]["nodes"]


def cmd_team_describe(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    body = body_text(ops, args, "team describe")
    team = team_id(ops, config, args.team)
    current = ops.gql(Q_TEAM_DESCRIPTION, {"id": team})["team"].get("description")
    if ops.normalize(current) == ops.normalize(body):
        print(f"skip   {args.team.upper()} description unchanged")
        return 0
    ops.write(M_TEAM_UPDATE, {"id": team, "input": {"description": body}}, "teamUpdate")
    print(f"update {args.team.upper()} description")
    return 0


def cmd_team_doc(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    body = body_text(ops, args, "team doc")
    team = team_id(ops, config, args.team)
    title = args.title.strip()
    payload: dict[str, Any] = {"title": title, "content": body}
    if args.sort is not None:
        payload["sortOrder"] = args.sort
    existing = next((d for d in team_documents(ops, team) if d["title"].strip() == title), None)
    if existing:
        unchanged = ops.normalize(existing.get("content")) == ops.normalize(body)
        if unchanged and (args.sort is None or existing.get("sortOrder") == args.sort):
            print(f"skip   document {title}")
            print(existing["url"])
            return 0
        document = ops.write(M_DOCUMENT_UPDATE, {"id": existing["id"], "input": payload}, "documentUpdate")["document"]
        print(f"update document {title}")
        print(document["url"])
        return 0
    payload["teamId"] = team
    document = ops.write(M_DOCUMENT_CREATE, {"input": payload}, "documentCreate")["document"]
    print(f"create document {title}")
    print(document["url"])
    return 0


def cmd_team_docs(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    rows = team_documents(ops, team_id(ops, config, args.team))
    for row in sorted(rows, key=lambda d: d.get("sortOrder") or 0):
        print(f"{row.get('sortOrder')} {row['title']} {row['url']}")
    print(f"{len(rows)} document(s)")
    return 0


def cmd_team_link(ops: ModuleType, config: dict[str, Any], args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"teamId": team_id(ops, config, args.team), "label": args.label, "url": args.url}
    if args.sort is not None:
        payload["sortOrder"] = args.sort
    link = ops.write(M_LINK_CREATE, {"input": payload}, "entityExternalLinkCreate")["entityExternalLink"]
    print(f"create link {link['label']} {link['url']} ({link['id']})")
    return 0


# --------------------------------------------------------------------------- registration


def register(subparsers: Any, ops: ModuleType) -> None:
    def add(parent: Any, name: str, help_text: str, func: Any) -> argparse.ArgumentParser:
        parser = parent.add_parser(name, help=help_text)
        parser.set_defaults(func=partial(func, ops), needs_project=False)
        return parser

    update = add(subparsers, "project-update", "post a project update (health + markdown body)", cmd_project_update)
    update.add_argument("target", metavar="project", help="configured project, Linear project name or slugId")
    update.add_argument("--health", choices=HEALTH, required=True)
    update.add_argument("--body")
    update.add_argument("--body-file", help="update body (markdown) from a file")

    view = subparsers.add_parser("view", help="saved issue views (custom views)").add_subparsers(
        dest="view_command", required=True
    )
    new_view = add(view, "new", "create a shared custom view from a preset or IssueFilter JSON", cmd_view_new)
    new_view.add_argument("name")
    new_view.add_argument(
        "--filter", required=True, help="waiting-on-user | in-progress | this-week, or raw IssueFilter JSON"
    )
    new_view.add_argument("--team", default="ERG")
    new_view.add_argument("--project", help="scope the view to this Linear project")
    new_view.add_argument("--description")
    add(view, "list", "every custom view the app can see", cmd_view_list)

    template = subparsers.add_parser("template", help="issue templates").add_subparsers(
        dest="template_command", required=True
    )
    new_template = add(template, "new", "create an issue template with the fixed sections", cmd_template_new)
    new_template.add_argument("name")
    new_template.add_argument("--kind", choices=tuple(TEMPLATE_SECTIONS), required=True)
    new_template.add_argument("--team", default="ERG")
    add(template, "list", "every template the app can see", cmd_template_list)

    team = subparsers.add_parser("team", help="the team home: description, documents, links").add_subparsers(
        dest="team_command", required=True
    )
    describe = add(team, "describe", "set the team description (skipped when unchanged)", cmd_team_describe)
    describe.add_argument("team")
    describe.add_argument("--body")
    describe.add_argument("--body-file", help="description from a file")
    doc = add(team, "doc", "create a team document, or update the one with this title", cmd_team_doc)
    doc.add_argument("team")
    doc.add_argument("title")
    doc.add_argument("--body")
    doc.add_argument("--body-file", help="document content (markdown) from a file")
    doc.add_argument("--sort", type=float, help="sortOrder in the team resources")
    docs = add(team, "docs", "list the team's documents", cmd_team_docs)
    docs.add_argument("team")
    link = add(
        team,
        "link",
        "add an external link to the team resources (the API cannot list them, so no dedupe)",
        cmd_team_link,
    )
    link.add_argument("team")
    link.add_argument("--label", required=True)
    link.add_argument("--url", required=True)
    link.add_argument("--sort", type=float, help="sortOrder in the team resources")
