"""Offline tests for linear_ops: every Linear call goes through a fake `gql`, nothing touches the network."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast

TMP = tempfile.mkdtemp()
SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("linear_ops", SCRIPTS / "linear_ops.py")
assert spec and spec.loader
linear_ops = importlib.util.module_from_spec(spec)
sys.modules["linear_ops"] = linear_ops
spec.loader.exec_module(linear_ops)

TEAM = "team-erg"
PROJECT = "proj-hexis"
CLAUDE = "user-claude"
USER = "user-owner"
PROFILE = "https://linear.app/example/profiles/owner"
CONFIG = {
    "workspace": "example",
    "claude": {"id": CLAUDE, "name": "Claude"},
    "user": {"id": USER, "name": "owner", "profile_url": PROFILE},
    "teams": {"ERG": TEAM, "PEER": "team-arc"},
    "write_teams": ["ERG"],
    "projects": {
        "Hexis": {"team": "ERG", "root": str(Path(TMP, "home")), "state_file": "", "repo": ""},
        "Peer": {"team": "PEER", "root": str(Path(TMP, "nowhere"))},
    },
}
STATES = [
    {"id": "s-todo", "name": "Todo", "type": "unstarted"},
    {"id": "s-prog", "name": "In Progress", "type": "started"},
    {"id": "s-done", "name": "Done", "type": "completed"},
    {"id": "s-cancel", "name": "Canceled", "type": "canceled"},
]
STATE_BY_ID = {s["id"]: s for s in STATES}
LABELS = [
    {"id": "l-ops", "name": "運用", "team": None},
    {"id": "l-arc", "name": "arc-only", "team": {"id": "team-arc"}},
]
MILESTONES = [{"id": "m-24", "name": "v0.24", "sortOrder": 1}, {"id": "m-ops", "name": "運用", "sortOrder": 2}]
USERS = {
    CLAUDE: {"id": CLAUDE, "name": "Claude", "displayName": "claude"},
    USER: {"id": USER, "name": "Owner", "displayName": "owner"},
}
PIPELINE = {
    "id": "pipe-1",
    "name": "Product",
    "slugId": "product",
    "url": "u",
    "stages": {
        "nodes": [
            {"id": "st-plan", "name": "Planned", "type": "planned"},
            {"id": "st-rel", "name": "Released", "type": "completed"},
        ]
    },
}


def issue(
    number: int, title: str, state: str = "s-todo", milestone: str | None = None, delegate: str | None = CLAUDE
) -> dict[str, Any]:
    return {
        "id": f"i-{number}",
        "identifier": f"ERG-{number}",
        "number": number,
        "title": title,
        "description": "",
        "priority": 0,
        "createdAt": "2026-09-23T00:00:00.000Z",
        "state": STATE_BY_ID[state],
        "assignee": None,
        "delegate": USERS[delegate] if delegate else None,
        "team": {"id": TEAM, "key": "ERG"},
        "project": {"id": PROJECT, "name": "Hexis"},
        "projectMilestone": next(
            ({"id": m["id"], "name": m["name"]} for m in MILESTONES if m["id"] == milestone), None
        ),
        "cycle": None,
        "parent": None,
        "labels": {"nodes": []},
    }


class FakeLinear:
    """Stands in for `linear_client.graphql`, answering by the operation name every query carries."""

    def __init__(self, issues: list[dict[str, Any]], notifications: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues
        self.notifications = notifications or []
        self.comments: dict[str, list[dict[str, Any]]] = {}
        self.releases: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ops(self, name: str) -> list[dict[str, Any]]:
        return [v for op, v in self.calls if op == name]

    def by_uuid(self, uuid: str) -> dict[str, Any]:
        return next(i for i in self.issues if i["id"] == uuid)

    def apply(self, row: dict[str, Any], data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key == "stateId":
                row["state"] = STATE_BY_ID[value]
            elif key == "assigneeId":
                # Linear accepts the app as assignee and leaves it null.
                row["assignee"] = USERS[value] if value and value != CLAUDE else None
            elif key == "delegateId":
                row["delegate"] = USERS[value] if value else None
            elif key == "projectMilestoneId":
                row["projectMilestone"] = next(
                    {"id": m["id"], "name": m["name"]} for m in MILESTONES if m["id"] == value
                )
            elif key in ("labelIds", "addedLabelIds"):
                current = [] if key == "labelIds" else row["labels"]["nodes"]
                row["labels"] = {
                    "nodes": current + [{"id": l["id"], "name": l["name"]} for l in LABELS if l["id"] in value]
                }
            elif key == "cycleId":
                row["cycle"] = {"id": value}
            elif key in ("title", "description", "priority"):
                row[key] = value

    def __call__(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        op = cast(re.Match, re.match(r"\s*(?:query|mutation)\s+(\w+)", query)).group(1)
        v = variables or {}
        self.calls.append((op, v))
        if op == "Issue":
            return {"issue": next((i for i in self.issues if i["identifier"] == v["id"]), None)}
        if op == "Issues":
            return {"issues": {"nodes": list(self.issues), "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        if op == "IssueComments":
            return {"issue": {"comments": {"nodes": self.comments.get(v["id"], [])}}}
        if op == "TeamStates":
            return {"workflowStates": {"nodes": STATES}}
        if op == "Projects":
            return {
                "projects": {
                    "nodes": [{"id": PROJECT, "name": "Hexis", "slugId": "x", "url": "", "teams": {"nodes": []}}]
                }
            }
        if op == "Milestones":
            return {"projectMilestones": {"nodes": MILESTONES}}
        if op == "Labels":
            return {"issueLabels": {"nodes": LABELS}}
        if op == "Cycles":
            return {"cycles": {"nodes": []}}
        if op == "Notifications":
            return {
                "notifications": {"nodes": self.notifications, "pageInfo": {"hasNextPage": False, "endCursor": None}}
            }
        if op == "NotificationRead":
            next(n for n in self.notifications if n["id"] == v["id"])["readAt"] = v["readAt"]
            return {"notificationUpdate": {"success": True}}
        if op == "IssueCreate":
            data = v["input"]
            row = issue(99, data["title"], data["stateId"], delegate=None)
            self.apply(row, {k: val for k, val in data.items() if k not in ("title", "stateId")})
            self.issues.append(row)
            return {"issueCreate": {"success": True, "issue": row}}
        if op == "IssueUpdate":
            row = self.by_uuid(v["id"])
            self.apply(row, v["input"])
            return {"issueUpdate": {"success": True, "issue": row}}
        if op == "CommentCreate":
            comment = {
                "id": f"c-{len(self.calls)}",
                "body": v["input"]["body"],
                "createdAt": "2026-09-23T01:00:00.000Z",
                "user": USERS[CLAUDE],
            }
            self.comments.setdefault(v["input"]["issueId"], []).append(comment)
            return {"commentCreate": {"success": True, "comment": {"id": comment["id"], "url": ""}}}
        if op == "Pipelines":
            return {"releasePipelines": {"nodes": [PIPELINE]}}
        if op == "Releases":
            return {"releases": {"nodes": [r for r in self.releases if r["version"] == v["version"]]}}
        if op == "ReleaseCreate":
            data = v["input"]
            release = {
                "id": "rel-1",
                "name": data["name"],
                "version": data["version"],
                "commitSha": data["commitSha"],
                "url": "r",
                "stage": {"id": data["stageId"], "type": "completed"},
                "issues": {"nodes": []},
            }
            self.releases.append(release)
            return {
                "releaseCreate": {"success": True, "release": {k: val for k, val in release.items() if k != "issues"}}
            }
        if op == "ReleaseUpdate":
            release = next(r for r in self.releases if r["id"] == v["id"])
            release.update({k: val for k, val in v["input"].items() if k == "commitSha"})
            return {
                "releaseUpdate": {"success": True, "release": {k: val for k, val in release.items() if k != "issues"}}
            }
        if op == "IssueToRelease":
            release = next(r for r in self.releases if r["id"] == v["input"]["releaseId"])
            release["issues"]["nodes"].append({"id": v["input"]["issueId"]})
            return {"issueToReleaseCreate": {"success": True}}
        raise AssertionError(f"unexpected operation {op} {v}")


def run(
    fake: FakeLinear, argv: list[str], project: str | None = "Hexis", config: dict[str, Any] | None = None
) -> tuple[int, str]:
    setattr(linear_ops, "gql", fake)  # noqa: B010 - linear_ops is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
    path = Path(TMP) / "linear_ops.json"
    path.write_text(json.dumps(config or CONFIG), encoding="utf-8")
    buffer = io.StringIO()
    head = ["--config", str(path)] + (["--project", project] if project else [])
    with redirect_stdout(buffer):
        code = linear_ops.main(head + argv)
    return code, buffer.getvalue()


class ArgumentTests(unittest.TestCase):
    def test_project_is_accepted_after_the_subcommand(self) -> None:
        args = linear_ops.build_parser().parse_args(
            ["new", "t", "--project", "Hexis", "--milestone", "運用", "--parent", "ERG-3"]
        )
        self.assertEqual((args.project, args.milestone, args.parent, args.state), ("Hexis", "運用", "ERG-3", "Todo"))

    def test_unknown_priority_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            linear_ops.build_parser().parse_args(["new", "t", "--priority", "blocker"])

    def test_the_deepest_root_wins(self) -> None:
        home = Path(TMP, "home")
        cfg = {"projects": {"Home": {"root": str(home)}, "Nr": {"root": str(home / "nr-fork")}}}
        self.assertEqual(linear_ops.pick_project(cfg, None, home / "nr-fork" / "src"), "Nr")
        self.assertEqual(linear_ops.pick_project(cfg, None, home / ".claude"), "Home")

    def test_the_local_file_is_merged_over_the_shared_one_and_tilde_is_expanded(self) -> None:
        shared = Path(TMP, "linear_ops.json")
        shared.write_text(
            json.dumps({"projects": {"A": {"team": "ERG", "root": "~/a"}, "B": {"team": "ERG"}}}), encoding="utf-8"
        )
        Path(TMP, "linear_ops.local.json").write_text(
            json.dumps({"projects": {"B": {"root": str(Path(TMP, "b"))}}}), encoding="utf-8"
        )
        cfg = linear_ops.load_config(shared)
        for project in cfg["projects"].values():  # state_file is derived from root; tested apart
            project.pop("state_file", None)
        self.assertEqual(cfg["projects"]["A"], {"team": "ERG", "root": str(Path.home() / "a")})
        self.assertEqual(cfg["projects"]["B"], {"team": "ERG", "root": str(Path(TMP, "b"))})

    def test_state_file_is_derived_from_the_root(self) -> None:
        shared = Path(TMP, "derive", "linear_ops.json")
        shared.parent.mkdir(exist_ok=True)
        shared.write_text(
            json.dumps({"projects": {"A": {"team": "ERG", "root": str(Path(TMP, "x_y.z"))}}}), encoding="utf-8"
        )
        cfg = linear_ops.load_config(shared)
        key = linear_ops.project_key(str(Path(TMP, "x_y.z")))
        self.assertEqual(
            cfg["projects"]["A"]["state_file"], str(Path.home() / ".claude" / "projects" / key / "memory" / "STATE.md")
        )
        self.assertEqual(linear_ops.project_key("C:\\Users\\owner\\.claude"), "C--Users-owner--claude")

    def test_a_team_outside_write_teams_is_refused(self) -> None:
        code, _ = run(FakeLinear([]), ["status"], project="Peer")
        self.assertEqual(code, 2)

    def test_an_issue_of_another_team_is_refused(self) -> None:
        fake = FakeLinear([])
        code, _ = run(fake, ["progress", "PEER-1", "x"])
        self.assertEqual(code, 2)
        self.assertFalse(fake.ops("CommentCreate"))


class NewTests(unittest.TestCase):
    def test_new_is_delegated_to_claude_and_not_assigned(self) -> None:
        fake = FakeLinear([])
        code, out = run(
            fake, ["new", "ルールを書き換える", "--milestone", "運用", "--label", "運用", "--priority", "high"]
        )
        self.assertEqual(code, 0)
        created = fake.ops("IssueCreate")[0]["input"]
        self.assertEqual(created["delegateId"], CLAUDE)
        self.assertNotIn("assigneeId", created)
        self.assertEqual(created["priority"], 2)
        self.assertEqual(created["projectMilestoneId"], "m-ops")
        self.assertEqual(created["labelIds"], ["l-ops"])
        self.assertEqual(created["projectId"], PROJECT)
        self.assertIn("create ERG-99 ルールを書き換える", out)
        self.assertFalse(fake.ops("IssueUpdate"))

    def test_new_twice_creates_once_and_repairs_a_missing_delegate(self) -> None:
        fake = FakeLinear([issue(5, "既存", delegate=None)])
        code, out = run(fake, ["new", "既存", "--milestone", "運用"])
        self.assertEqual(code, 0)
        self.assertFalse(fake.ops("IssueCreate"))
        self.assertIn("exists ERG-5", out)
        self.assertEqual(fake.ops("IssueUpdate")[0]["input"], {"delegateId": CLAUDE})
        self.assertIn("milestone ERG-5 -> 運用", out)

    def test_new_never_moves_an_existing_milestone(self) -> None:
        fake = FakeLinear([issue(5, "既存", milestone="m-24")])
        _, out = run(fake, ["new", "既存", "--milestone", "運用"])
        self.assertIn("keep   ERG-5 milestone v0.24", out)
        self.assertFalse(fake.ops("IssueUpdate"))


class CommentTests(unittest.TestCase):
    def test_progress_posts_once(self) -> None:
        fake = FakeLinear([issue(5, "x")])
        run(fake, ["progress", "ERG-5", "--text", "テスト 12 件 green"])
        run(fake, ["progress", "ERG-5", "テスト 12 件 green"])
        self.assertEqual(len(fake.ops("CommentCreate")), 1)
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "テスト 12 件 green")

    def test_progress_report_file_is_markdown_as_is(self) -> None:
        report = Path(TMP) / "report.md"
        report.write_text("## Done\n```\n12 passed\n```\n", encoding="utf-8")
        fake = FakeLinear([issue(5, "x")])
        run(fake, ["progress", "ERG-5", "--report-file", str(report)])
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "## Done\n```\n12 passed\n```\n")

    def test_progress_needs_text(self) -> None:
        code, _ = run(FakeLinear([issue(5, "x")]), ["progress", "ERG-5"])
        self.assertEqual(code, 2)

    def test_done_comments_then_moves_to_done_once(self) -> None:
        fake = FakeLinear([issue(5, "x", state="s-prog")])
        run(fake, ["done", "ERG-5", "--text", "完了"])
        _, out = run(fake, ["done", "ERG-5", "--text", "完了"])
        self.assertEqual(len(fake.ops("CommentCreate")), 1)
        self.assertEqual([u["input"] for u in fake.ops("IssueUpdate")], [{"stateId": "s-done"}])
        self.assertIn("already Done", out)

    def test_a_mention_rewritten_by_linear_still_counts_as_the_same_comment(self) -> None:
        fake = FakeLinear([issue(5, "x")])
        fake.comments["i-5"] = [{"id": "c", "body": "@owner 確認してください", "createdAt": "", "user": USERS[CLAUDE]}]
        _, out = run(fake, ["progress", "ERG-5", "確認してください", "--mention"])
        self.assertIn("comment already there", out)


class CancelTests(unittest.TestCase):
    def test_cancel_comments_the_reason_and_never_deletes(self) -> None:
        fake = FakeLinear([issue(5, "x")])
        code, _out = run(fake, ["cancel", "ERG-5", "--reason", "ツールの動作確認"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "キャンセル: ツールの動作確認")
        self.assertEqual(fake.ops("IssueUpdate")[0]["input"], {"stateId": "s-cancel"})
        self.assertFalse([op for op, _ in fake.calls if "Delete" in op or "Archive" in op])
        self.assertIn("i-5", [i["id"] for i in fake.issues])
        run(fake, ["cancel", "ERG-5", "--reason", "ツールの動作確認"])
        self.assertEqual(len(fake.ops("CommentCreate")), 1)
        self.assertEqual(len(fake.ops("IssueUpdate")), 1)

    def test_cancel_needs_a_reason(self) -> None:
        with self.assertRaises(SystemExit):
            linear_ops.build_parser().parse_args(["cancel", "ERG-5"])

    def test_no_delete_mutation_exists_in_the_module(self) -> None:
        source = (SCRIPTS / "linear_ops.py").read_text(encoding="utf-8")
        self.assertNotIn("issueDelete", source)
        self.assertNotIn("issueArchive", source)


class HandoffTests(unittest.TestCase):
    def test_handoff_assigns_the_human_keeps_the_delegate_and_mentions(self) -> None:
        fake = FakeLinear([issue(5, "ゲーム内で確認", state="s-prog")])
        code, out = run(fake, ["handoff", "ERG-5", "ゲームを起動して確認してください", "--mention"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], f"{PROFILE} ゲームを起動して確認してください")
        self.assertEqual(fake.ops("IssueUpdate")[0]["input"], {"assigneeId": USER})
        row = fake.by_uuid("i-5")
        self.assertEqual((row["assignee"]["id"], row["delegate"]["id"]), (USER, CLAUDE))
        self.assertIn("assign ERG-5 -> owner, delegate claude", out)

    def test_handoff_does_not_mention_by_default(self) -> None:
        # The assignment already notifies the user; a default mention would notify twice (Hexis).
        fake = FakeLinear([issue(5, "x")])
        run(fake, ["handoff", "ERG-5", "確認"])
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "確認")

    def test_handoff_twice_changes_nothing_the_second_time(self) -> None:
        fake = FakeLinear([issue(5, "x")])
        run(fake, ["handoff", "ERG-5", "確認"])
        _, out = run(fake, ["handoff", "ERG-5", "確認"])
        self.assertEqual(len(fake.ops("CommentCreate")), 1)
        self.assertEqual(len(fake.ops("IssueUpdate")), 1)
        self.assertIn("already assigned to owner", out)

    def test_handoff_restores_a_missing_delegate_in_the_same_update(self) -> None:
        fake = FakeLinear([issue(5, "x", delegate=None)])
        run(fake, ["handoff", "ERG-5", "確認", "--no-mention"])
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "確認")
        self.assertEqual(fake.ops("IssueUpdate")[0]["input"], {"assigneeId": USER, "delegateId": CLAUDE})

    def test_handoff_fails_loudly_when_linear_drops_the_delegate(self) -> None:
        fake = FakeLinear([issue(5, "x")])
        original = fake.apply

        def drop(row: dict[str, Any], data: dict[str, Any]) -> None:
            original(row, data)
            if "assigneeId" in data:
                row["delegate"] = None

        fake.apply = drop
        code, _ = run(fake, ["handoff", "ERG-5", "確認"])
        self.assertEqual(code, 2)


def notification(nid: str, kind: str, read: str | None = None) -> dict[str, Any]:
    return {
        "id": nid,
        "type": kind,
        "createdAt": f"2026-09-23T0{len(nid)}:00:00.000Z",
        "readAt": read,
        "archivedAt": None,
        "title": "t",
        "actor": USERS[USER],
        "issue": {"identifier": "ERG-5", "title": "x"},
        "comment": {"id": "c1", "body": "@claude 見て", "user": USERS[USER]} if "Mention" in kind else None,
    }


class InboxTests(unittest.TestCase):
    def test_inbox_lists_unread_mentions_and_marks_them_read(self) -> None:
        fake = FakeLinear(
            [],
            [
                notification("n1", "issueCommentMention"),
                notification("n22", "issueAssignedToYou"),
                notification("n3", "issueAddedToView"),
                notification("n4", "issueNewComment", read="2026-09-22"),
            ],
        )
        code, out = run(fake, ["inbox"], project=None)
        self.assertEqual(code, 0)
        self.assertIn("ERG-5 | owner | 2026-09-23T02:00:00.000Z | issueCommentMention | @claude 見て", out)
        self.assertIn("issueAssignedToYou", out)
        self.assertNotIn("issueAddedToView |", out)
        self.assertEqual(sorted(v["id"] for v in fake.ops("NotificationRead")), ["n1", "n22"])
        _, out = run(fake, ["inbox"], project=None)
        self.assertIn("0 unread", out)

    def test_inbox_peek_marks_nothing(self) -> None:
        fake = FakeLinear([], [notification("n1", "issueCommentMention")])
        _, out = run(fake, ["inbox", "--peek"], project=None)
        self.assertIn("1 unread", out)
        self.assertFalse(fake.ops("NotificationRead"))


class ReleaseTests(unittest.TestCase):
    def history(self) -> tuple[Path, dict[str, Any]]:
        path = Path(TMP) / "VERSION_HISTORY.md"
        path.write_text("# h\n\n## 0.24.2 (2026-09-20) — old\n", encoding="utf-8")
        config = json.loads(json.dumps(CONFIG))
        config["projects"]["Hexis"]["version_history"] = str(path)
        return path, config

    def test_release_creates_a_completed_release_links_and_comments_once(self) -> None:
        path, config = self.history()
        fake = FakeLinear([issue(5, "a", state="s-done"), issue(6, "b", state="s-done")])
        argv = [
            "release",
            "Product",
            "--version",
            "0.24.3",
            "--sha",
            "4b3ace0f",
            "--notes",
            "修正",
            "--issues",
            "ERG-5,ERG-6",
            "--date",
            "2026-09-23",
        ]
        code, out = run(fake, argv, config=config)
        self.assertEqual(code, 0)
        created = fake.ops("ReleaseCreate")[0]["input"]
        self.assertEqual(
            (created["pipelineId"], created["version"], created["commitSha"], created["stageId"], created["name"]),
            ("pipe-1", "0.24.3", "4b3ace0f", "st-rel", "v0.24.3"),
        )
        self.assertEqual(sorted(v["input"]["issueId"] for v in fake.ops("IssueToRelease")), ["i-5", "i-6"])
        self.assertEqual(len(fake.ops("CommentCreate")), 2)
        self.assertEqual(fake.ops("CommentCreate")[0]["input"]["body"], "v0.24.3 で配置\n修正")
        self.assertTrue(
            path.read_text(encoding="utf-8").startswith("# h\n\n## 0.24.3 (2026-09-23) — 修正 — SHA 4b3ace0f\n")
        )
        code, out = run(fake, argv, config=config)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.ops("ReleaseCreate")), 1)
        self.assertEqual(len(fake.ops("IssueToRelease")), 2)
        self.assertEqual(len(fake.ops("CommentCreate")), 2)
        self.assertFalse(fake.ops("ReleaseUpdate"))
        self.assertIn("skip   release Product v0.24.3 exists", out)
        self.assertEqual(path.read_text(encoding="utf-8").count("## 0.24.3"), 1)

    def test_release_with_a_milestone_refuses_while_an_issue_is_open(self) -> None:
        fake = FakeLinear(
            [issue(5, "a", state="s-done", milestone="m-24"), issue(6, "b", state="s-prog", milestone="m-24")]
        )
        code, out = run(
            fake,
            [
                "release",
                "Product",
                "--version",
                "0.24.3",
                "--sha",
                "4b3ace0f",
                "--notes",
                "n",
                "--milestone",
                "v0.24",
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("open   ERG-6 [In Progress] b", out)
        self.assertFalse(fake.ops("ReleaseCreate"))

    def test_release_with_a_done_milestone_takes_its_issues(self) -> None:
        fake = FakeLinear([issue(5, "a", state="s-done", milestone="m-24"), issue(7, "c", state="s-done")])
        code, _ = run(
            fake,
            [
                "release",
                "Product",
                "--version",
                "0.24.3",
                "--sha",
                "4b3ace0f",
                "--notes",
                "n",
                "--milestone",
                "v0.24",
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual([v["input"]["issueId"] for v in fake.ops("IssueToRelease")], ["i-5"])

    def test_release_fills_a_missing_sha_on_an_existing_release(self) -> None:
        fake = FakeLinear([issue(5, "a", state="s-done")])
        fake.releases.append(
            {
                "id": "rel-0",
                "name": "v0.24.3",
                "version": "0.24.3",
                "commitSha": None,
                "url": "r",
                "stage": {"id": "st-rel", "type": "completed"},
                "issues": {"nodes": [{"id": "i-5"}]},
            }
        )
        _, out = run(
            fake,
            ["release", "Product", "--version", "0.24.3", "--sha", "4b3ace0f", "--notes", "n", "--issues", "ERG-5"],
        )
        self.assertEqual(fake.ops("ReleaseUpdate")[0]["input"], {"commitSha": "4b3ace0f"})
        self.assertFalse(fake.ops("IssueToRelease"))
        self.assertIn("skip   ERG-5 already in v0.24.3", out)

    def test_release_validates_version_sha_and_issues(self) -> None:
        fake = FakeLinear([])
        self.assertEqual(
            run(
                fake,
                ["release", "Product", "--version", "0.24", "--sha", "4b3ace0f", "--notes", "n", "--issues", "ERG-5"],
            )[0],
            2,
        )
        self.assertEqual(
            run(
                fake,
                ["release", "Product", "--version", "0.24.3", "--sha", "xyz", "--notes", "n", "--issues", "ERG-5"],
            )[0],
            2,
        )
        self.assertEqual(
            run(fake, ["release", "Product", "--version", "0.24.3", "--sha", "4b3ace0f", "--notes", "n"])[0], 2
        )


class BriefStatusSyncTests(unittest.TestCase):
    def test_brief_has_fields_description_comments_and_footer(self) -> None:
        row = issue(5, "実装する", milestone="m-ops")
        row["description"] = "## 要件\n- a"
        fake = FakeLinear([row])
        fake.comments["i-5"] = [
            {"id": "c", "body": "進んだ", "createdAt": "2026-09-23T01:00:00.000Z", "user": USERS[USER]}
        ]
        _, out = run(fake, ["brief", "ERG-5"])
        for needle in (
            "# ERG-5: 実装する",
            "milestone: 運用",
            "delegate: claude",
            "## 要件\n- a",
            "## 進捗 (owner, 2026-09-23)",
            "linear_ops.py progress ERG-5",
        ):
            self.assertIn(needle, out)

    def test_status_filters_by_milestone(self) -> None:
        fake = FakeLinear([issue(5, "a", milestone="m-24"), issue(6, "b")])
        _, out = run(fake, ["status", "--milestone", "v0.24"])
        self.assertIn("ERG-5", out)
        self.assertNotIn("ERG-6", out)

    def test_sync_state_reports_only_the_unfiled_pending(self) -> None:
        state = Path(TMP) / "STATE.md"
        state.write_text(
            "- 2026-09-23 10:00 pending[p1]: see ERG-5 for this\n"
            "- 2026-09-23 10:01 pending[p2]: something with no issue\n"
            "- 2026-09-23 10:02 pending[p3]: closed one\n"
            "- 2026-09-23 10:03 done[p3]: closed\n",
            encoding="utf-8",
        )
        config = json.loads(json.dumps(CONFIG))
        config["projects"]["Hexis"]["state_file"] = str(state)
        _, out = run(FakeLinear([issue(5, "a")]), ["sync-state"], config=config)
        self.assertIn("ok     p1 -> ERG-5", out)
        self.assertIn("FILE   p2: something with no issue", out)
        self.assertNotIn("p3", out)
        self.assertIn("2 open pending(s), 1 with no Linear issue", out)


if __name__ == "__main__":
    unittest.main()
