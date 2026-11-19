"""Task operations over Linear, written under the dedicated "Claude" app identity.

The transport and the credentials come from `linear_client.py` beside this file: this file only adds
the conventions on top of it - a Linear project per configured project, project milestones as release
versions, themes as labels, Claude as the DELEGATE of every issue it works on (an app user cannot be
the assignee), the human as assignee only on a handoff, progress as comments, a Linear Release per
deploy - and makes each of them a command that can be run twice without doing anything twice.
Issues are never deleted: `cancel` closes them as Canceled with a reason.

Configuration is `linear_ops.json` beside this file; the project is picked from the working
directory unless `--project` names one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import linear_client
import linear_ops_ext

CONFIG_PATH = SCRIPTS_DIR / "linear_ops.json"
PATH_KEYS = ("root", "state_file", "version_history", "repo")

PRIORITIES = {"urgent": 1, "high": 2, "medium": 3, "low": 4, "none": 0}
CLOSED_TYPES = ("completed", "canceled", "duplicate")
OPEN_STATE_NAMES = ("In Progress", "Todo")
VERSION_MILESTONE_RE = re.compile(r"^v(\d+)\.(\d+)$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{8}$")
HEADING_RE = re.compile(r"^## (\d+)\.(\d+)\.(\d+) ")
IDENT_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)-(\d+)")
PENDING_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) pending(?:\[(p\d+)\])?: (.*)$")
CLOSE_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} (?:done|ruled-out)(?:\[(p\d+)\])?: (.*)$")
MENTION_RE = re.compile(r"(?:https://linear\.app/[^/\s]+/profiles/[^\s)\]]+|@\S+)")
INBOX_NOISE = ("issueAddedToView", "issueSubscribed")

gql = linear_client.graphql


class OpsError(Exception):
    """Anything this CLI refuses to do, or that Linear refuses to do for it."""


# --------------------------------------------------------------------------- queries

ISSUE_FIELDS = """id identifier number title description url priority createdAt updatedAt
  state { id name type } assignee { id name displayName } delegate { id name displayName }
  team { id key } project { id name } projectMilestone { id name } cycle { id name number }
  parent { identifier } labels(first: 20) { nodes { id name } }"""

Q_ISSUE = f"query Issue($id: String!) {{ issue(id: $id) {{ {ISSUE_FIELDS} }} }}"
Q_ISSUES = f"""query Issues($filter: IssueFilter, $first: Int!, $after: String) {{
  issues(first: $first, after: $after, filter: $filter) {{ nodes {{ {ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }}
}}"""
Q_COMMENTS = """query IssueComments($id: String!) {
  issue(id: $id) { comments(first: 250) { nodes { id body createdAt user { id name displayName } } } }
}"""
Q_TEAMS = "query Teams { teams(first: 50) { nodes { id key name } } }"
Q_STATES = """query TeamStates($teamId: ID!) {
  workflowStates(first: 50, filter: { team: { id: { eq: $teamId } } }) { nodes { id name type } }
}"""
Q_PROJECTS = (
    "query Projects { projects(first: 250) { nodes { id name slugId url teams(first: 10) { nodes { id key } } } } }"
)
Q_MILESTONES = """query Milestones($projectId: ID!) {
  projectMilestones(first: 100, filter: { project: { id: { eq: $projectId } } }) { nodes { id name sortOrder } }
}"""
Q_LABELS = "query Labels { issueLabels(first: 250) { nodes { id name team { id } } } }"
Q_CYCLES = """query Cycles($teamId: ID!) {
  cycles(first: 100, filter: { team: { id: { eq: $teamId } } }) { nodes { id number name startsAt endsAt isActive } }
}"""
Q_NOTIFICATIONS = """query Notifications($first: Int!, $after: String) {
  notifications(first: $first, after: $after) {
    nodes { id type createdAt readAt archivedAt title actor { id name displayName }
      ... on IssueNotification { issue { identifier title } comment { id body user { name displayName } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""
Q_PIPELINES = """query Pipelines {
  releasePipelines(first: 50) { nodes { id name slugId url stages(first: 20) { nodes { id name type } } } }
}"""
Q_RELEASES = """query Releases($pipelineId: ID!, $version: String!) {
  releases(first: 5, filter: { pipeline: { id: { eq: $pipelineId } }, version: { eq: $version } }) {
    nodes { id name version commitSha url stage { id type } issues(first: 250) { nodes { id } } }
  }
}"""

M_ISSUE_CREATE = f"mutation IssueCreate($input: IssueCreateInput!) {{ issueCreate(input: $input) {{ success issue {{ {ISSUE_FIELDS} }} }} }}"
M_ISSUE_UPDATE = (
    "mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) "
    f"{{ issueUpdate(id: $id, input: $input) {{ success issue {{ {ISSUE_FIELDS} }} }} }}"
)
M_COMMENT_CREATE = """mutation CommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id url } }
}"""
M_NOTIFICATION_READ = """mutation NotificationRead($id: String!, $readAt: DateTime!) {
  notificationUpdate(id: $id, input: { readAt: $readAt }) { success }
}"""
M_CYCLE_CREATE = """mutation CycleCreate($input: CycleCreateInput!) {
  cycleCreate(input: $input) { success cycle { id number name startsAt endsAt isActive } }
}"""
M_RELEASE_CREATE = """mutation ReleaseCreate($input: ReleaseCreateInput!) {
  releaseCreate(input: $input) { success release { id name version commitSha url stage { id type } } }
}"""
M_RELEASE_UPDATE = """mutation ReleaseUpdate($id: String!, $input: ReleaseUpdateInput!) {
  releaseUpdate(id: $id, input: $input) { success release { id name version commitSha url stage { id type } } }
}"""
M_ISSUE_TO_RELEASE = """mutation IssueToRelease($input: IssueToReleaseCreateInput!) {
  issueToReleaseCreate(input: $input) { success }
}"""


def collect(query: str, variables: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    return linear_client.collect(query, variables, key, send=gql)


def write(query: str, variables: dict[str, Any], key: str) -> dict[str, Any]:
    result = gql(query, variables)[key]
    if not result.get("success"):
        raise OpsError(f"Linear reported {key} as unsuccessful.")
    return result


# --------------------------------------------------------------------------- configuration


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_config(base[key], value)
        else:
            base[key] = value
    return base


STATE_DIR = Path.home() / ".claude" / "projects"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """The shared config, with `<name>.local.json` beside it merged over it and `~` expanded in paths."""
    path = path or CONFIG_PATH
    if not path.is_file():
        raise OpsError(f"No config at {path}.")
    config = json.loads(path.read_text(encoding="utf-8"))
    local = path.with_name(f"{path.stem}.local.json")
    if local.is_file():
        merge_config(config, json.loads(local.read_text(encoding="utf-8")))
    for project in (config.get("projects") or {}).values():
        for key in PATH_KEYS:
            if project.get(key):
                project[key] = str(Path(project[key]).expanduser())
        if project.get("root") and "state_file" not in project:
            project["state_file"] = str(STATE_DIR / project_key(project["root"]) / "memory" / "STATE.md")
    return config


def project_key(root: str) -> str:
    """Claude Code's per-project directory name for a cwd: every character that is not a letter or digit becomes
    '-' (C:\\Users\\owner\\.claude -> C--Users-owner--claude, /home/k/x_y -> -home-k-x-y). One-way only."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).expanduser()))


def pick_project(config: dict[str, Any], name: str | None, cwd: Path | None = None) -> str:
    """Name the configured project: `--project` wins, else the one whose root holds the cwd."""
    projects = config.get("projects") or {}
    if name:
        if name not in projects:
            raise OpsError(f"No project '{name}' in the config. Known: {', '.join(projects)}.")
        return name
    here = (cwd or Path.cwd()).resolve()
    parts = [p.lower() for p in here.parts]
    # The deepest root that holds the cwd wins, so a broad root (Hexis at the home directory) never
    # shadows a project rooted inside it, whatever order the config lists them in.
    best, depth = None, -1
    for key, project in projects.items():
        root = project.get("root")
        if root:
            r = Path(root).resolve()
            if (here == r or r in here.parents) and len(r.parts) > depth:
                best, depth = key, len(r.parts)
    if best:
        return best
    for key in projects:
        if key.lower() in parts:
            return key
    raise OpsError(f"Cannot tell which project {here} is. Pass --project (known: {', '.join(projects)}).")


# --------------------------------------------------------------------------- project context


class Project:
    """One configured Linear project on its team, with the lookups a command needs cached per run."""

    def __init__(self, config: dict[str, Any], name: str) -> None:
        self.config = config
        self.name = name
        self.settings = config["projects"][name]
        self.linear_name = self.settings.get("linear_project", name)
        self.team_key = self.settings["team"].upper()
        writable = [t.upper() for t in config.get("write_teams") or []]
        if self.team_key not in writable:
            raise OpsError(f"Team {self.team_key} is not in write_teams ({', '.join(writable)}); refusing.")
        self._cache: dict[str, Any] = {}

    def _cached(self, slot: str, produce: Any) -> Any:
        if slot not in self._cache:
            self._cache[slot] = produce()
        return self._cache[slot]

    @property
    def team_id(self) -> str:
        def find() -> str:
            configured = (self.config.get("teams") or {}).get(self.team_key)
            if configured:
                return configured
            for team in gql(Q_TEAMS)["teams"]["nodes"]:
                if team["key"].upper() == self.team_key:
                    return team["id"]
            raise OpsError(f"No team with key '{self.team_key}'.")

        return self._cached("team_id", find)

    @property
    def id(self) -> str:
        def find() -> str:
            for project in gql(Q_PROJECTS)["projects"]["nodes"]:
                if project["name"].lower() == self.linear_name.lower() or project.get("slugId") == self.linear_name:
                    return project["id"]
            raise OpsError(f"No Linear project '{self.linear_name}'.")

        return self._cached("id", find)

    @property
    def claude_id(self) -> str:
        return self.config["claude"]["id"]

    @property
    def user_id(self) -> str:
        return self.config["user"]["id"]

    @property
    def user_profile(self) -> str:
        return self.config["user"]["profile_url"]

    def states(self) -> list[dict[str, Any]]:
        return self._cached("states", lambda: gql(Q_STATES, {"teamId": self.team_id})["workflowStates"]["nodes"])

    def labels(self) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            nodes = gql(Q_LABELS)["issueLabels"]["nodes"]
            return [l for l in nodes if (l.get("team") or {}).get("id") in (None, self.team_id)]

        return self._cached("labels", read)

    def milestones(self) -> list[dict[str, Any]]:
        return self._cached(
            "milestones", lambda: gql(Q_MILESTONES, {"projectId": self.id})["projectMilestones"]["nodes"]
        )

    def cycles(self) -> list[dict[str, Any]]:
        return self._cached("cycles", lambda: gql(Q_CYCLES, {"teamId": self.team_id})["cycles"]["nodes"])

    def items(self) -> list[dict[str, Any]]:
        return self._cached(
            "items", lambda: collect(Q_ISSUES, {"filter": {"project": {"id": {"eq": self.id}}}}, "issues")
        )

    def forget_items(self) -> None:
        self._cache.pop("items", None)

    # ------------------------------------------------------------------ resolution

    def state(self, name: str) -> dict[str, Any]:
        for state in self.states():
            if state["name"].lower() == name.lower():
                return state
        raise OpsError(f"No state '{name}'. Known: {', '.join(s['name'] for s in self.states())}.")

    def label(self, name: str) -> dict[str, Any]:
        for label in self.labels():
            if label["name"].lower() == name.lower():
                return label
        raise OpsError(f"No label '{name}'. Known: {', '.join(l['name'] for l in self.labels())}.")

    def milestone(self, name: str) -> dict[str, Any]:
        for milestone in self.milestones():
            if milestone["name"].lower() == name.lower():
                return milestone
        raise OpsError(f"No milestone '{name}'. Known: {', '.join(m['name'] for m in self.milestones())}.")

    def item(self, ref: str) -> dict[str, Any]:
        """One issue by its 'ERG-12' identifier; an issue of another team is refused."""
        ref = ref.strip()
        match = IDENT_RE.fullmatch(ref)
        if not match:
            raise OpsError(f"'{ref}' is not an identifier like {self.team_key}-12.")
        if match.group(1).upper() != self.team_key:
            raise OpsError(f"'{ref}' is not in team {self.team_key}.")
        try:
            issue = gql(Q_ISSUE, {"id": ref.upper()})["issue"]
        except linear_client.LinearError as exc:
            raise OpsError(f"No issue {ref}: {exc}") from None
        if not issue:
            raise OpsError(f"No issue {ref}.")
        return issue


# --------------------------------------------------------------------------- shared actions


def ident(item: dict[str, Any]) -> str:
    return item["identifier"]


def name_of(user: dict[str, Any] | None) -> str:
    return (user or {}).get("displayName") or (user or {}).get("name") or "-"


def normalize(body: str | None) -> str:
    """Compare comments by their words, ignoring whatever form Linear gave a mention on the way in."""
    return " ".join(MENTION_RE.sub(" ", body or "").split())


def comments(item: dict[str, Any]) -> list[dict[str, Any]]:
    return gql(Q_COMMENTS, {"id": item["id"]})["issue"]["comments"]["nodes"]


def ensure_comment(project: Project, item: dict[str, Any], text: str, mention: bool = False) -> str:
    """Comment unless the very same text is already the record on that item."""
    body = f"{project.user_profile} {text}" if mention else text
    wanted = normalize(body)
    if any(normalize(row.get("body")) == wanted for row in comments(item)):
        return f"skip   {ident(item)} comment already there"
    write(M_COMMENT_CREATE, {"input": {"issueId": item["id"], "body": body}}, "commentCreate")
    return f"comment {ident(item)}: {' '.join(text.split())[:60]}"


def update(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return write(M_ISSUE_UPDATE, {"id": item["id"], "input": payload}, "issueUpdate")["issue"]


def ensure_state(project: Project, item: dict[str, Any], name: str) -> tuple[dict[str, Any], str]:
    state = project.state(name)
    if (item.get("state") or {}).get("id") == state["id"]:
        return item, f"skip   {ident(item)} already {name}"
    return update(item, {"stateId": state["id"]}), f"state  {ident(item)} -> {name}"


def ensure_delegate(project: Project, item: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Claude takes work as the delegate; `assigneeId` = the app is accepted by Linear and stays null."""
    if (item.get("delegate") or {}).get("id") == project.claude_id:
        return item, None
    return update(item, {"delegateId": project.claude_id}), f"delegate {ident(item)} -> Claude"


def ensure_milestone(project: Project, item: dict[str, Any], name: str) -> tuple[dict[str, Any], str]:
    """An issue carries one milestone: set it when there is none, never move one that is already set."""
    milestone = project.milestone(name)
    current = item.get("projectMilestone") or {}
    if current.get("id") == milestone["id"]:
        return item, f"skip   {ident(item)} already in {name}"
    if current:
        return item, f"keep   {ident(item)} milestone {current.get('name')} (asked {name}; move it by hand)"
    return update(item, {"projectMilestoneId": milestone["id"]}), f"milestone {ident(item)} -> {name}"


def label_ids(item: dict[str, Any]) -> set[str]:
    return {l["id"] for l in (item.get("labels") or {}).get("nodes", [])}


def milestone_items(project: Project, name: str) -> list[dict[str, Any]]:
    milestone = project.milestone(name)
    return [i for i in project.items() if (i.get("projectMilestone") or {}).get("id") == milestone["id"]]


def open_items(project: Project, name: str) -> list[dict[str, Any]]:
    return [i for i in milestone_items(project, name) if (i.get("state") or {}).get("type") not in CLOSED_TYPES]


def lowest_open_version_milestone(project: Project) -> str | None:
    """The version milestone that is released next: the lowest v-numbered one still holding open work."""
    candidates = []
    for milestone in project.milestones():
        match = VERSION_MILESTONE_RE.match(milestone["name"])
        if match and open_items(project, milestone["name"]):
            candidates.append(((int(match.group(1)), int(match.group(2))), milestone["name"]))
    return min(candidates)[1] if candidates else None


# --------------------------------------------------------------------------- commands


def cmd_new(project: Project, args: argparse.Namespace) -> int:
    title = args.title.strip()
    description = None
    if args.desc_file:
        description = Path(args.desc_file).read_text(encoding="utf-8")
    elif args.desc:
        description = args.desc
    labels = [project.label(name)["id"] for name in args.label]

    existing = next((i for i in project.items() if i["title"].strip() == title), None)
    if existing:
        print(f"exists {ident(existing)} {title}")
        item = existing
    else:
        payload: dict[str, Any] = {
            "teamId": project.team_id,
            "projectId": project.id,
            "title": title,
            "stateId": project.state(args.state)["id"],
            "priority": PRIORITIES[args.priority],
            "delegateId": project.claude_id,
        }
        if labels:
            payload["labelIds"] = labels
        if description is not None:
            payload["description"] = description
        if args.milestone:
            payload["projectMilestoneId"] = project.milestone(args.milestone)["id"]
        if args.parent:
            payload["parentId"] = project.item(args.parent)["id"]
        item = write(M_ISSUE_CREATE, {"input": payload}, "issueCreate")["issue"]
        project.forget_items()
        print(f"create {ident(item)} {title}")

    item, line = ensure_delegate(project, item)
    if line:
        print(line)
    if labels and not set(labels) <= label_ids(item):
        item = update(item, {"addedLabelIds": sorted(set(labels) - label_ids(item))})
        print(f"labels {ident(item)} -> {', '.join(args.label)}")
    if args.milestone:
        item, line = ensure_milestone(project, item, args.milestone)
        print(line)
    print(ident(item))
    return 0


def cmd_progress(project: Project, args: argparse.Namespace) -> int:
    item = project.item(args.item)
    if args.report_file:
        text = Path(args.report_file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise OpsError("progress needs --text (or a positional comment) or --report-file")
    print(ensure_comment(project, item, text, mention=args.mention))
    return 0


FOOTER = (
    "Report back under: Done / Evidence (tests, commands, last lines) / Decisions and uncertainties / "
    "Files changed. Post the same report as a comment on {ident} with "
    "`python ~/.claude/scripts/linear_ops.py progress {ident} --report-file <file>` before "
    "finishing. Do the work yourself; never launch another agent."
)


def build_brief(project: Project, item: dict[str, Any]) -> str:
    """A self-contained brief for an implementing agent: everything on the ticket, nothing more."""
    lines = [
        f"# {ident(item)}: {item['title']}",
        "",
        f"project: {(item.get('project') or {}).get('name') or '-'}",
        f"milestone: {(item.get('projectMilestone') or {}).get('name') or '-'}",
        f"labels: {', '.join(l['name'] for l in (item.get('labels') or {}).get('nodes', [])) or '-'}",
        f"priority: {next((k for k, v in PRIORITIES.items() if v == item.get('priority')), 'none')}",
        f"state: {(item.get('state') or {}).get('name')}",
        f"delegate: {name_of(item.get('delegate'))}",
        f"assignee: {name_of(item.get('assignee'))}",
    ]
    if item.get("parent"):
        lines.append(f"parent: {item['parent']['identifier']}")
    lines.append("")
    description = (item.get("description") or "").strip()
    if description:
        lines += [description, ""]
    for comment in sorted(comments(item), key=lambda c: c.get("createdAt") or ""):
        lines += [f"## 進捗 ({name_of(comment.get('user'))}, {(comment.get('createdAt') or '')[:10]})", ""]
        body = (comment.get("body") or "").strip()
        if body:
            lines += [body, ""]
    lines.append("---")
    lines.append(FOOTER.format(ident=ident(item)))
    return "\n".join(lines).rstrip() + "\n"


def cmd_brief(project: Project, args: argparse.Namespace) -> int:
    item = project.item(args.item)
    text = build_brief(project, item)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"brief  {ident(item)} -> {args.out}")
    else:
        print(text)
    return 0


def cmd_done(project: Project, args: argparse.Namespace) -> int:
    item = project.item(args.item)
    if args.text:
        print(ensure_comment(project, item, args.text, mention=args.mention))
    item, line = ensure_state(project, item, "Done")
    print(line)
    return 0


def cmd_cancel(project: Project, args: argparse.Namespace) -> int:
    """Close as Canceled with the reason as a comment. Nothing in this tool deletes an issue."""
    item = project.item(args.item)
    print(ensure_comment(project, item, f"キャンセル: {args.reason}"))
    item, line = ensure_state(project, item, "Canceled")
    print(line)
    return 0


def cmd_handoff(project: Project, args: argparse.Namespace) -> int:
    """The next step is the human's: comment it (with a mention), assign them, keep Claude as the delegate."""
    item = project.item(args.item)
    print(ensure_comment(project, item, args.text, mention=args.mention))
    payload: dict[str, Any] = {}
    if (item.get("assignee") or {}).get("id") != project.user_id:
        payload["assigneeId"] = project.user_id
    if (item.get("delegate") or {}).get("id") != project.claude_id:
        payload["delegateId"] = project.claude_id
    if not payload:
        print(f"skip   {ident(item)} already assigned to {project.config['user']['name']}, delegate Claude")
        return 0
    item = update(item, payload)
    print(f"assign {ident(item)} -> {name_of(item.get('assignee'))}, delegate {name_of(item.get('delegate'))}")
    if (item.get("delegate") or {}).get("id") != project.claude_id:
        raise OpsError(f"{ident(item)}: Linear dropped the Claude delegate when the assignee was set.")
    return 0


def cmd_status(project: Project, args: argparse.Namespace) -> int:
    items = milestone_items(project, args.milestone) if args.milestone else project.items()
    print(f"{'id':<8} {'state':<12} {'prio':<7} {'milestone':<16} {'delegate':<9} {'assignee':<9} title")
    for item in sorted(items, key=lambda i: i.get("number") or 0):
        prio = next((k for k, v in PRIORITIES.items() if v == item.get("priority")), "none")
        print(
            f"{ident(item):<8} {(item.get('state') or {}).get('name', ''):<12} {prio:<7} "
            f"{(item.get('projectMilestone') or {}).get('name') or '-':<16} {name_of(item.get('delegate')):<9} "
            f"{name_of(item.get('assignee')):<9} {item['title']}"
        )
    return 0


def cmd_release_check(project: Project, args: argparse.Namespace) -> int:
    pending = open_items(project, args.milestone)
    for item in sorted(pending, key=lambda i: i.get("number") or 0):
        print(f"open   {ident(item)} [{(item.get('state') or {}).get('name')}] {item['title']}")
    if pending:
        print(f"NG {args.milestone}: {len(pending)} item(s) not Done")
        return 1
    print(f"OK {args.milestone}: every item is Done")
    return 0


def version_history_line(text: str, version: str, date: str, notes: str) -> tuple[str, bool]:
    """Insert a version section at the top of the newest-first block; report whether it was new."""
    if f"## {version} (" in text or f"| {version} |" in text:
        return text, False
    lines = text.splitlines(keepends=True)
    best, best_at = None, None
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            number = tuple(int(g) for g in match.groups())
            if best is None or number > best:
                best, best_at = number, index
    section = f"## {version} ({date}) — {notes}\n\n"
    if best_at is None:
        return text + ("" if text.endswith("\n") else "\n") + "\n" + section, True
    lines.insert(best_at, section)
    return "".join(lines), True


def ensure_heading_sha(text: str, version: str, sha: str) -> tuple[str, bool]:
    """Append ' — SHA xxxxxxxx' to a VERSION_HISTORY.md section's heading line, if it lacks one."""
    prefix = f"## {version} ("
    at = text.find(prefix)
    if at == -1:
        return text, False
    line_end = text.find("\n", at)
    if line_end == -1:
        line_end = len(text)
    line = text[at:line_end]
    if re.search(r"— SHA [0-9a-fA-F]{8}\s*$", line):
        return text, False
    return text[:at] + line + f" — SHA {sha}" + text[line_end:], True


def git_tag(project: Project, version: str, notes: str, run: Any = subprocess.run) -> str:
    """Tag the configured repo vX.Y.Z once its working tree is clean. Never commits."""
    repo = project.settings.get("repo")
    if not repo:
        return "no-repo"
    status = run(["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True, check=True)
    if status.stdout.strip():
        return "dirty"
    run(["git", "-C", repo, "tag", "-a", f"v{version}", "-m", notes], check=True)
    return "tagged"


def maybe_tag(project: Project, args: argparse.Namespace) -> None:
    if not getattr(args, "tag", False):
        return
    outcome = git_tag(project, args.version, args.notes)
    if outcome == "no-repo":
        print(f"tag    skip v{args.version} (no repo configured)")
    elif outcome == "dirty":
        print(f"tag    WARNING v{args.version} skipped - repo has uncommitted changes, commit first")
    else:
        print(f"tag    v{args.version}")


def pipeline(name: str) -> dict[str, Any]:
    for row in gql(Q_PIPELINES)["releasePipelines"]["nodes"]:
        if row["name"].lower() == name.lower() or row["slugId"] == name:
            return row
    raise OpsError(f"No release pipeline '{name}'.")


def ensure_release(pipe: dict[str, Any], version: str, sha: str, notes: str) -> tuple[dict[str, Any], str]:
    """One Release per pipeline and version, in the pipeline's completed stage, carrying the SHA."""
    stage = next((s for s in pipe["stages"]["nodes"] if s["type"] == "completed"), None)
    if not stage:
        raise OpsError(f"Pipeline {pipe['name']} has no completed stage.")
    rows = gql(Q_RELEASES, {"pipelineId": pipe["id"], "version": version})["releases"]["nodes"]
    if not rows:
        payload = {
            "pipelineId": pipe["id"],
            "name": f"v{version}",
            "version": version,
            "commitSha": sha,
            "description": notes,
            "stageId": stage["id"],
        }
        release = write(M_RELEASE_CREATE, {"input": payload}, "releaseCreate")["release"]
        release["issues"] = {"nodes": []}
        return release, f"release {pipe['name']} v{version} created ({release.get('url')})"
    release = rows[0]
    fix: dict[str, Any] = {}
    if not release.get("commitSha"):
        fix["commitSha"] = sha
    if (release.get("stage") or {}).get("id") != stage["id"]:
        fix["stageId"] = stage["id"]
    if not fix:
        return release, f"skip   release {pipe['name']} v{version} exists"
    issues = release.get("issues")
    release = write(M_RELEASE_UPDATE, {"id": release["id"], "input": fix}, "releaseUpdate")["release"]
    release["issues"] = issues
    return release, f"release {pipe['name']} v{version} updated ({', '.join(fix)})"


def cmd_release(project: Project, args: argparse.Namespace) -> int:
    if not VERSION_RE.match(args.version):
        raise OpsError(f"--version '{args.version}' is not X.Y.Z.")
    if not SHA_RE.match(args.sha):
        raise OpsError(f"--sha '{args.sha}' is not 8 hex digits.")
    items = [project.item(ref) for ref in (args.issues or "").split(",") if ref.strip()]
    if args.milestone:
        if cmd_release_check(project, args) != 0:
            print(f"refuse {args.milestone}: not released while items are open")
            return 1
        known = {i["id"] for i in items}
        items += [i for i in milestone_items(project, args.milestone) if i["id"] not in known]
    if not items:
        raise OpsError("release needs --issues and/or --milestone naming at least one issue")
    pipe = pipeline(args.pipeline)

    history_path = project.settings.get("version_history")
    if history_path:
        date = args.date or dt.datetime.now().astimezone().date().isoformat()
        history = Path(history_path)
        text = history.read_text(encoding="utf-8")
        text, wrote = version_history_line(text, args.version, date, args.notes)
        text, sha_added = ensure_heading_sha(text, args.version, args.sha)
        if wrote or sha_added:
            history.write_text(text, encoding="utf-8")
        print(f"{'history' if wrote else 'sha    ' if sha_added else 'skip   '} {history} {args.version}")

    release, line = ensure_release(pipe, args.version, args.sha, args.notes)
    print(line)
    linked = {row["id"] for row in (release.get("issues") or {}).get("nodes", [])}
    for item in sorted(items, key=lambda i: i.get("number") or 0):
        if item["id"] in linked:
            print(f"skip   {ident(item)} already in v{args.version}")
        else:
            write(
                M_ISSUE_TO_RELEASE,
                {"input": {"issueId": item["id"], "releaseId": release["id"]}},
                "issueToReleaseCreate",
            )
            print(f"link   {ident(item)} -> v{args.version}")
        print(ensure_comment(project, item, f"v{args.version} で配置\n{args.notes}"))
    maybe_tag(project, args)
    return 0


def week_bounds(start: dt.date) -> tuple[dt.date, dt.date]:
    monday = start - dt.timedelta(days=start.weekday())
    return monday, monday + dt.timedelta(days=6)


def overlapping_cycle(project: Project, start: dt.date, end: dt.date) -> dict[str, Any] | None:
    """The week's cycle is whichever existing cycle covers any of its days, whatever it is called."""
    for cycle in project.cycles():
        first, last = (cycle.get("startsAt") or "")[:10], (cycle.get("endsAt") or "")[:10]
        if first and last and first <= end.isoformat() and last >= start.isoformat():
            return cycle
    return None


def cmd_cycle_open(project: Project, args: argparse.Namespace) -> int:
    start, end = week_bounds(dt.date.fromisoformat(args.start) if args.start else dt.datetime.now().astimezone().date())
    name = f"{start.isoformat()} 週"
    cycle = overlapping_cycle(project, start, end)
    if cycle:
        name = cycle.get("name") or f"#{cycle.get('number')}"
        print(f"exists cycle {name} {(cycle.get('startsAt') or '')[:10]}..{(cycle.get('endsAt') or '')[:10]}")
    else:
        payload = {
            "teamId": project.team_id,
            "name": name,
            "startsAt": f"{start.isoformat()}T00:00:00.000Z",
            "endsAt": f"{(end + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z",
        }
        cycle = write(M_CYCLE_CREATE, {"input": payload}, "cycleCreate")["cycle"]
        print(f"create cycle {name} {start}..{end}")

    milestone = lowest_open_version_milestone(project)
    if not milestone:
        print("skip   no version milestone has open work")
        return 0
    for item in open_items(project, milestone):
        if (item.get("state") or {}).get("name") not in OPEN_STATE_NAMES:
            continue
        if (item.get("cycle") or {}).get("id") == cycle["id"]:
            print(f"skip   {ident(item)} already in {name}")
        else:
            update(item, {"cycleId": cycle["id"]})
            print(f"cycle  {ident(item)} -> {name} ({milestone})")
    return 0


def cmd_cycle_status(project: Project, args: argparse.Namespace) -> int:
    cycles = project.cycles()
    if not cycles:
        print(f"no cycle in team {project.team_key}")
        return 0
    for cycle in sorted(cycles, key=lambda c: c.get("startsAt") or ""):
        first, last = (cycle.get("startsAt") or "")[:10], (cycle.get("endsAt") or "")[:10]
        label = cycle.get("name") or f"#{cycle.get('number')}"
        print(f"cycle  {label} {first}..{last} [{'active' if cycle.get('isActive') else 'other'}]")
        for item in sorted(project.items(), key=lambda i: i.get("number") or 0):
            if (item.get("cycle") or {}).get("id") == cycle["id"]:
                print(f"  {ident(item):<8} {(item.get('state') or {}).get('name', ''):<12} {item['title']}")
    return 0


def notification_line(row: dict[str, Any]) -> str:
    issue = row.get("issue") or {}
    comment = row.get("comment") or {}
    who = name_of(comment.get("user") or row.get("actor"))
    text = " ".join((comment.get("body") or row.get("title") or "").split())[:120]
    return f"{issue.get('identifier') or '-'} | {who} | {row.get('createdAt')} | {row.get('type')} | {text}"


def cmd_inbox(config: dict[str, Any], args: argparse.Namespace) -> int:
    """The app's own unread notifications (mentions, assignments, replies), marked read once listed."""
    rows = collect(Q_NOTIFICATIONS, {}, "notifications")
    unread = [r for r in rows if not r.get("readAt") and not r.get("archivedAt")]
    hits = [r for r in unread if args.all_types or r.get("type") not in INBOX_NOISE]
    for row in sorted(hits, key=lambda r: r.get("createdAt") or ""):
        print(notification_line(row))
    print(f"{len(hits)} unread ({len(unread) - len(hits)} more of type {', '.join(INBOX_NOISE)} not shown)")
    if args.peek:
        return 0
    now = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for row in hits:
        write(M_NOTIFICATION_READ, {"id": row["id"], "readAt": now}, "notificationUpdate")
    if hits:
        print(f"marked {len(hits)} read")
    return 0


def open_pendings(text: str) -> list[tuple[str, str]]:
    """The STATE.md pending lines with no later done/ruled-out line closing them."""
    pendings: list[tuple[str, str]] = []
    closed_ids: set[str] = set()
    closed_texts: list[str] = []
    for line in text.splitlines():
        match = PENDING_RE.match(line.strip())
        if match:
            pendings.append((match.group(2) or "", match.group(3).strip()))
            continue
        match = CLOSE_RE.match(line.strip())
        if match:
            if match.group(1):
                closed_ids.add(match.group(1))
            closed_texts.append(match.group(2).strip())
    out = []
    for pid, body in pendings:
        if pid and pid in closed_ids:
            continue
        if not pid and any(closed.startswith(body[:30]) for closed in closed_texts):
            continue
        out.append((pid, body))
    return out


def matching_item(project: Project, body: str) -> dict[str, Any] | None:
    """A pending is filed when it names its issue, or when a title shares its wording either way round."""
    text = " ".join(body.split()).lower()
    for number in re.findall(rf"{project.team_key}-(\d+)", body, re.IGNORECASE):
        found = next((i for i in project.items() if i.get("number") == int(number)), None)
        if found:
            return found
    for item in project.items():
        title = " ".join((item.get("title") or "").split()).lower()
        if not title:
            continue
        if title in text or text[:24] in title:
            return item
    return None


def cmd_sync_state(project: Project, args: argparse.Namespace) -> int:
    state_file = Path(project.settings["state_file"])
    pendings = open_pendings(state_file.read_text(encoding="utf-8"))
    missing = 0
    for pid, body in pendings:
        item = matching_item(project, body)
        tag = pid or "pending"
        if item:
            print(f"ok     {tag} -> {ident(item)} {item['title']}")
        else:
            missing += 1
            print(f"FILE   {tag}: {body}")
    print(f"{len(pendings)} open pending(s), {missing} with no Linear issue (nothing was created)")
    return 0


# --------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project", default=argparse.SUPPRESS, help="configured project name; default: the one holding the cwd"
    )
    parser = argparse.ArgumentParser(
        prog="linear_ops", description=cast(str, __doc__).splitlines()[0], parents=[common]
    )
    parser.add_argument("--config", help="path to linear_ops.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def sub(name: str, help_text: str) -> argparse.ArgumentParser:
        return subparsers.add_parser(name, help=help_text, parents=[common])

    new = sub("new", "create an issue delegated to Claude (not assigned), with milestone and labels")
    new.add_argument("title")
    new.add_argument("--milestone")
    new.add_argument("--label", action="append", default=[])
    new.add_argument("--priority", choices=tuple(PRIORITIES), default="none")
    new.add_argument("--state", default="Todo")
    new.add_argument("--desc")
    new.add_argument("--desc-file")
    new.add_argument("--parent")
    new.set_defaults(func=cmd_new)

    mention_help = "prefix the comment with the user's profile URL, which Linear turns into a notifying @mention"

    progress = sub("progress", "comment on an issue as Claude")
    progress.add_argument("item")
    progress.add_argument("comment", nargs="?")
    progress.add_argument("--text")
    progress.add_argument("--report-file", help="comment body (markdown) from a file")
    progress.add_argument("--mention", action=argparse.BooleanOptionalAction, default=False, help=mention_help)
    progress.set_defaults(func=cmd_progress)

    brief = sub("brief", "print (or write) a self-contained agent brief for an issue")
    brief.add_argument("item")
    brief.add_argument("--out", help="write the brief to this file instead of printing it")
    brief.set_defaults(func=cmd_brief)

    done = sub("done", "comment and move an issue to Done")
    done.add_argument("item")
    done.add_argument("comment", nargs="?")
    done.add_argument("--text")
    done.add_argument("--mention", action=argparse.BooleanOptionalAction, default=False, help=mention_help)
    done.set_defaults(func=cmd_done)

    cancel = sub("cancel", "close an issue as Canceled with the reason as a comment (never deletes)")
    cancel.add_argument("item")
    cancel.add_argument("--reason", required=True)
    cancel.set_defaults(func=cmd_cancel)

    handoff = sub("handoff", "comment what the user must do, assign them, keep Claude as the delegate")
    handoff.add_argument("item")
    handoff.add_argument("comment", nargs="?")
    handoff.add_argument("--text")
    handoff.add_argument("--mention", action=argparse.BooleanOptionalAction, default=False, help=mention_help)
    handoff.set_defaults(func=cmd_handoff)

    inbox = sub("inbox", "the app's unread notifications (mentions, assignments, replies); marks them read")
    inbox.add_argument("--peek", action="store_true", help="list only; leave everything unread")
    inbox.add_argument("--all-types", action="store_true", help=f"also list {', '.join(INBOX_NOISE)}")
    inbox.set_defaults(func=cmd_inbox, needs_project=False)

    status = sub("status", "the project's issues, or one milestone's")
    status.add_argument("--milestone")
    status.set_defaults(func=cmd_status)

    check = sub("release-check", "list a milestone's issues that are not closed; exit 1 if any")
    check.add_argument("milestone")
    check.set_defaults(func=cmd_release_check)

    release = sub("release", "record a deploy as a Linear Release in a pipeline, linking and commenting the issues")
    release.add_argument("pipeline")
    release.add_argument("--version", required=True)
    release.add_argument("--sha", required=True)
    release.add_argument("--notes", required=True)
    release.add_argument("--issues", help="comma-separated identifiers, e.g. ERG-32,ERG-34")
    release.add_argument("--milestone", help="also release every issue of this milestone, refusing while any is open")
    release.add_argument("--date")
    release.add_argument("--tag", action="store_true", help="git tag vX.Y.Z in the configured repo once it is clean")
    release.set_defaults(func=cmd_release)

    cycle_open = sub("cycle-open", "open this week's cycle and fill it from the next version milestone")
    cycle_open.add_argument("--start")
    cycle_open.set_defaults(func=cmd_cycle_open)

    cycle_status = sub("cycle-status", "the team's cycles and this project's issues in them")
    cycle_status.set_defaults(func=cmd_cycle_status)

    sync = sub("sync-state", "open STATE.md pendings with no Linear issue (creates nothing)")
    sync.set_defaults(func=cmd_sync_state)

    linear_ops_ext.register(subparsers, sys.modules[__name__])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "comment", None) and not getattr(args, "text", None):
        args.text = args.comment
    try:
        config = load_config(Path(args.config) if args.config else None)
        if not getattr(args, "needs_project", True):
            return args.func(config, args)
        project = Project(config, pick_project(config, getattr(args, "project", None)))
        if args.command == "handoff" and not args.text:
            raise OpsError("handoff needs the step for the user (positional or --text)")
        return args.func(project, args)
    except (OpsError, linear_client.LinearError) as exc:
        print(f"NG {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
