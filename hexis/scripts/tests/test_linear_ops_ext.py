"""Offline tests for the linear_ops_ext subcommands, on the fake Linear of test_linear_ops."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from test_linear_ops import PROJECT, TEAM, TMP, USER, FakeLinear, run

PROJECT_NODE = {
    "id": PROJECT,
    "name": "Hexis",
    "slugId": "x",
    "url": "",
    "teams": {"nodes": [{"id": TEAM, "key": "ERG"}]},
}
ARC_NODE = {
    "id": "proj-arc",
    "name": "Peer",
    "slugId": "y",
    "url": "",
    "teams": {"nodes": [{"id": "t", "key": "PEER"}]},
}
OPEN = {"state": {"type": {"nin": ["completed", "canceled", "duplicate"]}}}
ON_TEAM = {"team": {"id": {"eq": TEAM}}}


class FakeExt(FakeLinear):
    def __init__(self) -> None:
        super().__init__([])
        self.last_update: dict[str, Any] | None = None
        self.views: list[dict[str, Any]] = []
        self.templates: list[dict[str, Any]] = []
        self.description: str | None = None
        self.documents: list[dict[str, Any]] = []

    def __call__(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        op = query.split("(")[0].split()[1]
        v = variables or {}
        if op == "Projects":
            self.calls.append((op, v))
            return {"projects": {"nodes": [PROJECT_NODE, ARC_NODE]}}
        if op == "ProjectLastUpdate":
            self.calls.append((op, v))
            return {"project": {"lastUpdate": self.last_update}}
        if op == "ProjectUpdateCreate":
            self.calls.append((op, v))
            data = v["input"]
            self.last_update = {"body": data["body"], "health": data["health"], "url": "https://linear.app/u/1"}
            return {
                "projectUpdateCreate": {
                    "success": True,
                    "projectUpdate": {"id": "pu-1", "url": "https://linear.app/u/1"},
                }
            }
        if op == "CustomViews":
            self.calls.append((op, v))
            return {"customViews": {"nodes": self.views, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        if op == "CustomViewCreate":
            self.calls.append((op, v))
            view = {"id": "v-1", "name": v["input"]["name"], "slugId": "abc123", "shared": True, "team": {"key": "ERG"}}
            self.views.append(view)
            return {"customViewCreate": {"success": True, "customView": view}}
        if op == "Templates":
            self.calls.append((op, v))
            return {"templates": self.templates}
        if op == "TemplateCreate":
            self.calls.append((op, v))
            row = {
                "id": "tpl-1",
                "name": v["input"]["name"],
                "type": "issue",
                "team": {"id": v["input"]["teamId"], "key": "ERG"},
            }
            self.templates.append(row)
            return {"templateCreate": {"success": True, "template": row}}
        if op == "TeamDescription":
            self.calls.append((op, v))
            return {"team": {"id": v["id"], "key": "ERG", "description": self.description}}
        if op == "TeamUpdate":
            self.calls.append((op, v))
            self.description = v["input"]["description"]
            return {"teamUpdate": {"success": True, "team": {"id": v["id"], "description": self.description}}}
        if op == "TeamDocuments":
            self.calls.append((op, v))
            return {"documents": {"nodes": self.documents}}
        if op == "DocumentCreate":
            self.calls.append((op, v))
            row = {
                **v["input"],
                "id": f"doc-{len(self.documents) + 1}",
                "url": f"https://linear.app/d/{len(self.documents) + 1}",
            }
            self.documents.append(row)
            return {"documentCreate": {"success": True, "document": row}}
        if op == "DocumentUpdate":
            self.calls.append((op, v))
            row = next(d for d in self.documents if d["id"] == v["id"])
            row.update(v["input"])
            return {"documentUpdate": {"success": True, "document": row}}
        if op == "EntityExternalLinkCreate":
            self.calls.append((op, v))
            return {"entityExternalLinkCreate": {"success": True, "entityExternalLink": {**v["input"], "id": "link-1"}}}
        return super().__call__(query, variables)


def ext(fake: FakeExt, argv: list[str]) -> tuple[int, str]:
    return run(fake, argv, project=None)


class ProjectUpdateTests(unittest.TestCase):
    def test_project_update_posts_health_and_body_once(self) -> None:
        fake = FakeExt()
        code, out = ext(fake, ["project-update", "Hexis", "--health", "atRisk", "--body", "今週: 遅延"])
        self.assertEqual(code, 0)
        self.assertEqual(
            fake.ops("ProjectUpdateCreate"),
            [{"input": {"projectId": PROJECT, "health": "atRisk", "body": "今週: 遅延"}}],
        )
        self.assertIn("https://linear.app/u/1", out)
        code, out = ext(fake, ["project-update", "Hexis", "--health", "atRisk", "--body", "今週: 遅延"])
        self.assertEqual((code, len(fake.ops("ProjectUpdateCreate"))), (0, 1))
        self.assertIn("skip", out)

    def test_project_update_reads_the_body_file_and_refuses_other_teams(self) -> None:
        fake = FakeExt()
        path = Path(TMP) / "update.md"
        path.write_text("## 進捗\n\n- done\n", encoding="utf-8")
        ext(fake, ["project-update", "Hexis", "--health", "onTrack", "--body-file", str(path)])
        self.assertEqual(fake.ops("ProjectUpdateCreate")[0]["input"]["body"], "## 進捗\n\n- done\n")
        code, _ = ext(fake, ["project-update", "Peer", "--health", "onTrack", "--body", "x"])
        self.assertEqual((code, len(fake.ops("ProjectUpdateCreate"))), (2, 1))
        with self.assertRaises(SystemExit):
            ext(fake, ["project-update", "Hexis", "--health", "fine", "--body", "x"])


class ViewTests(unittest.TestCase):
    def created(self, argv: list[str]) -> tuple[FakeExt, str, dict[str, Any]]:
        fake = FakeExt()
        code, out = ext(fake, argv)
        self.assertEqual(code, 0, out)
        return fake, out, fake.ops("CustomViewCreate")[0]["input"]

    def test_waiting_on_user_is_the_human_assignee_or_the_waiting_mark_and_open(self) -> None:
        _, out, data = self.created(["view", "new", "ユーザー待ち", "--filter", "waiting-on-user"])
        waiting = {"or": [{"assignee": {"id": {"eq": USER}}}, {"description": {"contains": "待ち:"}}]}
        self.assertEqual(data["filterData"], {"and": [ON_TEAM, waiting, OPEN]})
        self.assertEqual((data["teamId"], data["shared"]), (TEAM, True))
        self.assertIn("https://linear.app/example/view/abc123", out)

    def test_in_progress_and_this_week_presets(self) -> None:
        _, _, data = self.created(["view", "new", "進行中", "--filter", "in-progress", "--description", "d"])
        self.assertEqual(data["filterData"], {"and": [ON_TEAM, {"state": {"type": {"eq": "started"}}}]})
        self.assertEqual(data["description"], "d")
        _, _, data = self.created(["view", "new", "今週", "--filter", "this-week", "--project", "Hexis"])
        self.assertEqual(data["filterData"], {"and": [ON_TEAM, {"updatedAt": {"gte": "-P7D"}}, OPEN]})
        self.assertEqual(data["projectId"], PROJECT)

    def test_raw_json_filter_and_no_second_view(self) -> None:
        raw = {"priority": {"eq": 1}}
        fake, _, data = self.created(["view", "new", "緊急", "--filter", json.dumps(raw)])
        self.assertEqual(data["filterData"], raw)
        code, out = ext(fake, ["view", "new", "緊急", "--filter", "in-progress"])
        self.assertEqual((code, len(fake.ops("CustomViewCreate"))), (0, 1))
        self.assertIn("exists", out)
        code, _ = ext(FakeExt(), ["view", "new", "x", "--filter", "nonsense"])
        self.assertEqual(code, 2)
        code, _ = ext(FakeExt(), ["view", "new", "x", "--filter", "in-progress", "--team", "PEER"])
        self.assertEqual(code, 2)

    def test_view_list(self) -> None:
        fake = FakeExt()
        fake.views = [{"id": "v", "name": "a", "slugId": "s1", "shared": False, "team": None}]
        code, out = ext(fake, ["view", "list"])
        self.assertEqual(code, 0)
        self.assertIn("personal a https://linear.app/example/view/s1", out)


class TemplateTests(unittest.TestCase):
    def test_parent_template_carries_the_brief_sections_as_stringified_json(self) -> None:
        fake = FakeExt()
        code, out = ext(fake, ["template", "new", "親課題", "--kind", "parent"])
        self.assertEqual(code, 0, out)
        data = fake.ops("TemplateCreate")[0]["input"]
        self.assertEqual((data["type"], data["teamId"], data["name"]), ("issue", TEAM, "親課題"))
        body = json.loads(data["templateData"])
        self.assertEqual(body["title"], "")
        headings = [line[3:] for line in body["description"].splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["背景", "要件", "受け入れ条件", "範囲外", "想定 tier", "見積り"])
        self.assertIn("tpl-1", out)
        code, out = ext(fake, ["template", "new", "親課題", "--kind", "parent"])
        self.assertEqual((code, len(fake.ops("TemplateCreate"))), (0, 1))

    def test_agent_run_template_and_list(self) -> None:
        fake = FakeExt()
        ext(fake, ["template", "new", "エージェント実行", "--kind", "agent-run"])
        body = json.loads(fake.ops("TemplateCreate")[0]["input"]["templateData"])
        headings = [line[3:] for line in body["description"].splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["依頼", "証拠", "結果", "判断と不確かさ"])
        code, out = ext(fake, ["template", "list"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"tpl-1 issue +ERG +no-body エージェント実行")


class TeamHomeTests(unittest.TestCase):
    def test_describe_writes_once_and_refuses_other_teams(self) -> None:
        fake = FakeExt()
        code, out = ext(fake, ["team", "describe", "ERG", "--body", "Hexis 主導の作業"])
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.ops("TeamUpdate"), [{"id": TEAM, "input": {"description": "Hexis 主導の作業"}}])
        code, out = ext(fake, ["team", "describe", "erg", "--body", "Hexis 主導の作業"])
        self.assertEqual((code, len(fake.ops("TeamUpdate"))), (0, 1))
        self.assertIn("skip", out)
        code, _ = ext(fake, ["team", "describe", "PEER", "--body", "x"])
        self.assertEqual((code, len(fake.ops("TeamUpdate"))), (2, 1))
        code, _ = ext(fake, ["team", "describe", "ERG"])
        self.assertEqual(code, 2)

    def test_doc_creates_on_the_team_then_updates_by_title(self) -> None:
        fake = FakeExt()
        path = Path(TMP) / "doc.md"
        body = "## 運用\n\n- 一件一話題\n"
        path.write_text(body, encoding="utf-8")
        code, out = ext(fake, ["team", "doc", "ERG", "ERG の運用ルール", "--body-file", str(path), "--sort", "1"])
        self.assertEqual(code, 0, out)
        self.assertEqual(
            fake.ops("DocumentCreate"),
            [{"input": {"title": "ERG の運用ルール", "content": body, "sortOrder": 1.0, "teamId": TEAM}}],
        )
        self.assertEqual(fake.ops("TeamDocuments")[0], {"filter": {"team": {"id": {"eq": TEAM}}}})
        self.assertIn("https://linear.app/d/1", out)
        code, out = ext(fake, ["team", "doc", "ERG", "ERG の運用ルール", "--body-file", str(path), "--sort", "1"])
        self.assertEqual((code, len(fake.ops("DocumentCreate")), len(fake.ops("DocumentUpdate"))), (0, 1, 0))
        self.assertIn("skip", out)
        code, out = ext(fake, ["team", "doc", "ERG", "ERG の運用ルール", "--body", "改訂"])
        self.assertEqual(
            fake.ops("DocumentUpdate"), [{"id": "doc-1", "input": {"title": "ERG の運用ルール", "content": "改訂"}}]
        )
        code, out = ext(fake, ["team", "docs", "ERG"])
        self.assertEqual(code, 0)
        self.assertIn("1.0 ERG の運用ルール https://linear.app/d/1", out)

    def test_link_goes_to_the_team_with_its_sort_order(self) -> None:
        fake = FakeExt()
        code, out = ext(
            fake, ["team", "link", "ERG", "--label", "Hexis", "--url", "https://linear.app/p", "--sort", "11"]
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(
            fake.ops("EntityExternalLinkCreate"),
            [{"input": {"teamId": TEAM, "label": "Hexis", "url": "https://linear.app/p", "sortOrder": 11.0}}],
        )
        self.assertIn("link-1", out)
        code, _ = ext(fake, ["team", "link", "PEER", "--label", "x", "--url", "https://x"])
        self.assertEqual((code, len(fake.ops("EntityExternalLinkCreate"))), (2, 1))


if __name__ == "__main__":
    unittest.main()
