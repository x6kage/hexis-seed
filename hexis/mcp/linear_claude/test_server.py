"""Unit tests for the linear-claude MCP server: credential parsing, name resolution, formatting.

No network: `server.graphql` is replaced by a stub that answers from canned GraphQL responses.

    python test_server.py
"""

from __future__ import annotations

import unittest
from typing import cast
from unittest import mock

import server

client = server.client

TEAMS = [
    {"id": "team-uuid-app", "key": "APP", "name": "Product", "description": None, "private": False},
    {"id": "team-uuid-xx", "key": "XX", "name": "owner", "description": None, "private": False},
]
PROJECTS = [
    {
        "id": "proj-uuid-1",
        "name": "Product",
        "slugId": "product-699e",
        "url": "https://linear.app/example/project/product",
        "status": {"name": "Backlog", "type": "planned"},
        "lead": None,
        "teams": {"nodes": [{"id": "team-uuid-app", "key": "APP", "name": "Product"}]},
    },
    {
        "id": "proj-uuid-2",
        "name": "Sandbox",
        "slugId": "sandbox-0001",
        "url": "https://linear.app/example/project/sandbox",
        "status": {"name": "Planned", "type": "planned"},
        "lead": None,
        "teams": {"nodes": [{"id": "team-uuid-xx", "key": "XX", "name": "owner"}]},
    },
]
STATES = [
    {"id": "state-backlog", "name": "Backlog", "type": "backlog", "position": 0.0, "description": None},
    {"id": "state-progress", "name": "In Progress", "type": "started", "position": 1.0, "description": None},
    {"id": "state-done", "name": "Done", "type": "completed", "position": 2.0, "description": None},
]
USERS = [
    {
        "id": "user-claude",
        "name": "Claude",
        "displayName": "claude",
        "email": "claude@oauthapp.linear.app",
        "active": True,
        "app": True,
        "url": "https://linear.app/example/profiles/claude",
    },
    {
        "id": "user-owner",
        "name": "owner",
        "displayName": "owner",
        "email": "owner@example.com",
        "active": True,
        "app": False,
        "url": "https://linear.app/example/profiles/owner",
    },
]
ISSUE = {
    "id": "issue-uuid-17",
    "identifier": "APP-17",
    "title": "0.23.0 deploy",
    "url": "https://linear.app/example/issue/APP-17",
    "priority": 2,
    "priorityLabel": "High",
    "createdAt": "2026-09-20T10:00:00.000Z",
    "updatedAt": "2026-09-21T00:48:53.948Z",
    "state": {"name": "Done", "type": "completed"},
    "assignee": {"name": "owner", "email": "owner@example.com"},
    "team": {"key": "APP", "name": "Product"},
    "project": {"name": "Product"},
    "description": "body text",
    "number": 17,
    "estimate": None,
    "dueDate": None,
    "branchName": "owner/app-17",
    "startedAt": None,
    "completedAt": "2026-09-21T00:00:00.000Z",
    "canceledAt": None,
    "creator": {"name": "owner", "email": "owner@example.com"},
    "parent": None,
    "labels": {"nodes": [{"name": "tooling"}]},
}
PROJECT_STATUSES = [
    {"id": "status-backlog", "name": "Backlog", "type": "backlog", "position": 0.0},
    {"id": "status-progress", "name": "In Progress", "type": "started", "position": 1.0},
    {"id": "status-done", "name": "Completed", "type": "completed", "position": 2.0},
]
PROJECT_FULL = {
    "id": "proj-uuid-2",
    "name": "Sandbox",
    "slugId": "sandbox-0001",
    "url": "https://linear.app/example/project/sandbox",
    "description": "one line summary",
    "content": "# body\nmarkdown",
    "priority": 2,
    "priorityLabel": "High",
    "startDate": "2026-09-21",
    "targetDate": "2026-09-30",
    "createdAt": "2026-09-21T00:00:00.000Z",
    "updatedAt": "2026-09-21T01:00:00.000Z",
    "archivedAt": None,
    "status": {"id": "status-progress", "name": "In Progress", "type": "started"},
    "lead": {"id": "user-owner", "name": "owner", "email": "owner@example.com"},
    "teams": {"nodes": [{"id": "team-uuid-xx", "key": "XX", "name": "owner"}]},
}
LABELS = [
    {
        "id": "label-tooling",
        "name": "tooling",
        "color": "#4cb782",
        "description": None,
        "isGroup": False,
        "parent": None,
        "team": None,
    },
    {
        "id": "label-bug",
        "name": "bug",
        "color": "#eb5757",
        "description": None,
        "isGroup": False,
        "parent": None,
        "team": {"id": "team-uuid-app", "key": "APP", "name": "Product"},
    },
]
CYCLES = [
    {
        "id": "cycle-2",
        "number": 2.0,
        "name": "Cycle 2",
        "description": None,
        "startsAt": "2026-09-22T00:00:00.000Z",
        "endsAt": "2026-10-06T00:00:00.000Z",
        "completedAt": None,
        "progress": 0.0,
        "isActive": False,
        "isNext": True,
        "isPrevious": False,
        "isFuture": True,
        "isPast": False,
        "team": {"id": "team-uuid-xx", "key": "XX", "name": "owner"},
    },
    {
        "id": "cycle-1",
        "number": 1.0,
        "name": "Cycle 1",
        "description": None,
        "startsAt": "2026-09-08T00:00:00.000Z",
        "endsAt": "2026-09-22T00:00:00.000Z",
        "completedAt": None,
        "progress": 0.5,
        "isActive": True,
        "isNext": False,
        "isPrevious": False,
        "isFuture": False,
        "isPast": False,
        "team": {"id": "team-uuid-xx", "key": "XX", "name": "owner"},
    },
]
MILESTONES = [
    {
        "id": "milestone-2",
        "name": "Beta",
        "description": None,
        "targetDate": "2026-10-15",
        "sortOrder": 2.0,
        "progress": 0.0,
        "status": "unstarted",
        "project": {"id": "proj-uuid-2", "name": "Sandbox"},
    },
    {
        "id": "milestone-1",
        "name": "Alpha",
        "description": "first cut",
        "targetDate": "2026-10-01",
        "sortOrder": 1.0,
        "progress": 0.25,
        "status": "next",
        "project": {"id": "proj-uuid-2", "name": "Sandbox"},
    },
]
COMMENTS = [
    {
        "id": "comment-2",
        "body": "second",
        "url": "https://linear.app/example/issue/APP-17#comment-2",
        "createdAt": "2026-09-21T02:00:00.000Z",
        "updatedAt": "2026-09-21T02:00:00.000Z",
        "editedAt": None,
        "user": {"id": "user-owner", "name": "owner", "email": "owner@example.com"},
        "parent": None,
    },
    {
        "id": "comment-1",
        "body": "first",
        "url": "https://linear.app/example/issue/APP-17#comment-1",
        "createdAt": "2026-09-21T01:00:00.000Z",
        "updatedAt": "2026-09-21T01:00:00.000Z",
        "editedAt": None,
        "user": {"id": "user-claude", "name": "Claude", "email": "claude@oauthapp.linear.app"},
        "parent": None,
    },
]
DOCUMENT = {
    "id": "doc-uuid-1",
    "title": "Design notes",
    "slugId": "design-notes-abcd",
    "url": "https://linear.app/example/document/design-notes-abcd",
    "icon": None,
    "color": None,
    "content": "# design\nbody",
    "createdAt": "2026-09-21T00:00:00.000Z",
    "updatedAt": "2026-09-21T01:00:00.000Z",
    "creator": {"name": "Claude"},
    "project": {"id": "proj-uuid-2", "name": "Sandbox"},
    "team": None,
}
USER_FULL = {
    "id": "user-claude",
    "name": "Claude",
    "displayName": "claude",
    "email": "claude@oauthapp.linear.app",
    "active": True,
    "admin": False,
    "guest": False,
    "app": True,
    "isMe": True,
    "url": "https://linear.app/example/profiles/claude",
    "timezone": "Asia/Tokyo",
    "title": None,
    "description": None,
    "createdAt": "2026-09-21T00:00:00.000Z",
}


NOTIFICATIONS = [
    {
        "id": "n-mention",
        "type": "issueCommentMention",
        "createdAt": "2026-09-23T07:00:00.000Z",
        "readAt": None,
        "archivedAt": None,
        "title": "APP-17",
        "actor": {"name": "owner", "displayName": "owner"},
        "issue": {"identifier": "APP-17", "title": "0.23.0 deploy"},
        "comment": {"id": "c-9", "body": "@claude please look", "user": {"name": "owner", "displayName": "owner"}},
    },
    {
        "id": "n-view",
        "type": "issueAddedToView",
        "createdAt": "2026-09-23T06:00:00.000Z",
        "readAt": None,
        "archivedAt": None,
        "title": "x",
        "actor": None,
    },
    {
        "id": "n-old",
        "type": "issueNewComment",
        "createdAt": "2026-09-22T06:00:00.000Z",
        "readAt": "2026-09-22T07:00:00.000Z",
        "archivedAt": None,
        "title": "y",
        "actor": None,
    },
]
PIPELINES = [
    {
        "id": "pipe-1",
        "name": "Product",
        "slugId": "product",
        "type": "scheduled",
        "url": "https://linear.app/example/pipeline/product/releases",
        "stages": {
            "nodes": [
                {"id": "stage-planned", "name": "Planned", "type": "planned"},
                {"id": "stage-released", "name": "Released", "type": "completed"},
            ]
        },
    }
]
RELEASE_ROW = {
    "id": "release-1",
    "name": "v0.24.3",
    "version": "0.24.3",
    "commitSha": "4b3ace0f",
    "description": "notes",
    "url": "https://linear.app/example/release/1",
    "completedAt": None,
    "stage": {"id": "stage-released", "name": "Released", "type": "completed"},
    "pipeline": {"name": "Product"},
}
RELEASES: list = []


class StubGraphQL:
    """Answers the module's queries from the canned data above, recording every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query, variables=None, _retried=False):
        variables = variables or {}
        self.calls.append((query, variables))
        if "viewer {" in query:
            return {"viewer": dict(USERS[0], admin=False)}
        if "teams(first: 250)" in query:
            return {"teams": {"nodes": TEAMS}}
        if "projects(first: 250" in query:
            nodes = PROJECTS
            team_filter = (variables.get("filter") or {}).get("accessibleTeams")
            if team_filter:
                wanted = team_filter["some"]["id"]["eq"]
                nodes = [p for p in PROJECTS if any(t["id"] == wanted for t in p["teams"]["nodes"])]
            return {"projects": {"nodes": nodes}}
        if "workflowStates(first: 100" in query:
            return {"workflowStates": {"nodes": STATES}}
        if "users(first: 250)" in query:
            return {"users": {"nodes": USERS}}
        if "issues(first: 2" in query:
            return {"issues": {"nodes": [{"id": "issue-uuid-17"}] if variables.get("number") == 17 else []}}
        if "issues(first: $first" in query:
            return {"issues": {"nodes": [ISSUE]}}
        if "issue(id: $id) { team" in query:
            return {"issue": {"team": {"id": "team-uuid-app"}}}
        if "issue(id: $id)" in query:
            return {"issue": ISSUE}
        if "issueCreate" in query:
            return {"issueCreate": {"success": True, "issue": ISSUE}}
        if "issueUpdate" in query:
            return {"issueUpdate": {"success": True, "issue": ISSUE}}
        if "commentCreate" in query:
            return {
                "commentCreate": {
                    "success": True,
                    "comment": {
                        "id": "comment-uuid",
                        "url": "https://linear.app/example/issue/APP-17#comment-1",
                        "createdAt": "2026-09-21T00:48:53.948Z",
                        "user": {"name": "Claude"},
                    },
                }
            }
        if "projectStatuses(first: 100" in query:
            return {"projectStatuses": {"nodes": PROJECT_STATUSES}}
        if "issueLabels(first: 250" in query:
            return {"issueLabels": {"nodes": LABELS}}
        if "cycles(first: 100" in query:
            return {"cycles": {"nodes": CYCLES}}
        if "projectMilestones(first: 100" in query:
            return {"projectMilestones": {"nodes": MILESTONES}}
        if "notifications(first:" in query:
            return {"notifications": {"nodes": NOTIFICATIONS, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        if "notificationUpdate" in query:
            return {"notificationUpdate": {"success": True}}
        if "releasePipelines(first: 50)" in query:
            return {"releasePipelines": {"nodes": PIPELINES}}
        if "releases(first: 100" in query:
            wanted = (variables.get("filter") or {}).get("version", {}).get("eq")
            by_id = (variables.get("filter") or {}).get("id", {}).get("eq")
            nodes = [
                r
                for r in RELEASES
                if (wanted is None or r["version"] == wanted) and (by_id is None or r["id"] == by_id)
            ]
            return {"releases": {"nodes": nodes}}
        if "releaseCreate" in query:
            release = dict(RELEASE_ROW, id="release-new", version=variables["input"]["version"], issues={"nodes": []})
            RELEASES.append(release)
            return {"releaseCreate": {"success": True, "release": {"id": "release-new"}}}
        if "releaseUpdate" in query:
            return {"releaseUpdate": {"success": True}}
        if "issueToReleaseCreate" in query:
            release = next(r for r in RELEASES if r["id"] == variables["input"]["releaseId"])
            release["issues"]["nodes"].append({"id": variables["input"]["issueId"], "identifier": "APP-17"})
            return {"issueToReleaseCreate": {"success": True}}
        if "comments(first: 100" in query:
            return {"comments": {"nodes": COMMENTS}}
        if "documents(first: 2" in query:
            return {"documents": {"nodes": [{"id": "doc-uuid-1", "title": "Design notes"}]}}
        if "documents(first: 100" in query:
            return {"documents": {"nodes": [DOCUMENT]}}
        if "document(id: $id)" in query:
            return {"document": DOCUMENT}
        if "user(id: $id)" in query:
            return {"user": USER_FULL}
        if "searchIssues(term:" in query:
            return {"searchIssues": {"nodes": [ISSUE]}}
        if "project(id: $id) { teams" in query:
            return {"project": {"teams": {"nodes": [{"id": "team-uuid-xx", "key": "XX", "name": "owner"}]}}}
        if "project(id: $id)" in query:
            return {"project": PROJECT_FULL}
        if "projectCreate" in query:
            return {"projectCreate": {"success": True, "project": PROJECT_FULL}}
        if "projectUpdate" in query:
            return {"projectUpdate": {"success": True, "project": PROJECT_FULL}}
        if "projectDelete" in query:
            return {
                "projectDelete": {
                    "success": True,
                    "entity": {"id": "proj-uuid-2", "name": "Sandbox", "archivedAt": "2026-09-21T03:00:00.000Z"},
                }
            }
        if "issueLabelCreate" in query:
            return {"issueLabelCreate": {"success": True, "issueLabel": LABELS[1]}}
        if "issueLabelUpdate" in query:
            return {"issueLabelUpdate": {"success": True, "issueLabel": LABELS[1]}}
        if "projectMilestoneCreate" in query:
            return {"projectMilestoneCreate": {"success": True, "projectMilestone": MILESTONES[1]}}
        if "projectMilestoneUpdate" in query:
            return {"projectMilestoneUpdate": {"success": True, "projectMilestone": MILESTONES[1]}}
        if "documentCreate" in query:
            return {"documentCreate": {"success": True, "document": DOCUMENT}}
        if "documentUpdate" in query:
            return {"documentUpdate": {"success": True, "document": DOCUMENT}}
        if "issueRelationCreate" in query:
            return {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {
                        "id": "relation-uuid",
                        "type": variables["input"]["type"],
                        "issue": {"identifier": "APP-17"},
                        "relatedIssue": {"identifier": "APP-17"},
                    },
                }
            }
        if "issueArchive" in query:
            return {
                "issueArchive": {
                    "success": True,
                    "entity": {
                        "id": "issue-uuid-17",
                        "identifier": "APP-17",
                        "title": "0.23.0 deploy",
                        "archivedAt": "2026-09-21T03:00:00.000Z",
                    },
                }
            }
        if "issueDelete" in query:
            return {
                "issueDelete": {
                    "success": True,
                    "entity": {"id": "issue-uuid-17", "identifier": "APP-17", "title": "0.23.0 deploy"},
                }
            }
        raise AssertionError(f"unexpected query: {query}")

    def last_input(self) -> dict:
        return self.calls[-1][1].get("input", {})


class FakeFile:
    def __init__(self, text: str | None):
        self.text = text

    def is_file(self) -> bool:
        return self.text is not None

    def read_text(self, encoding: str = "utf-8") -> str:
        return cast(str, self.text)  # only called after is_file(), which is true only when text is not None

    def __str__(self) -> str:
        return "<fake secrets file>"


class CredentialTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        client.reset_token()

    def test_oauth_file_two_lines_no_trailing_newline(self):
        with (
            mock.patch.dict(client.os.environ, {}, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile("client-id-value\nclient-secret-value")),
        ):
            self.assertEqual(client.oauth_credentials(), ("client-id-value", "client-secret-value"))

    def test_oauth_file_crlf_and_blank_lines(self):
        with (
            mock.patch.dict(client.os.environ, {}, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile("\r\nclient-id-value\r\n\r\nclient-secret-value\r\n")),
        ):
            self.assertEqual(client.oauth_credentials(), ("client-id-value", "client-secret-value"))

    def test_oauth_file_with_one_value_is_an_error(self):
        with (
            mock.patch.dict(client.os.environ, {}, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile("only-one-value\n")),
        ):
            with self.assertRaises(client.LinearError) as caught:
                client.oauth_credentials()
            self.assertIn("Client Secret on line 2", str(caught.exception))

    def test_environment_beats_the_file(self):
        env = {client.CLIENT_ID_ENV: "env-id", client.CLIENT_SECRET_ENV: "env-secret"}
        with (
            mock.patch.dict(client.os.environ, env, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile("file-id\nfile-secret")),
        ):
            self.assertEqual(client.oauth_credentials(), ("env-id", "env-secret"))

    def test_api_key_is_the_fallback_when_no_oauth(self):
        with (
            mock.patch.dict(client.os.environ, {}, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile(None)),
            mock.patch.object(client, "KEY_FILE", FakeFile("lin_api_personalkey\n")),
        ):
            self.assertEqual(client.auth_mode(), "api_key")
            self.assertEqual(client.auth_header(), "lin_api_personalkey")

    def test_no_credentials_names_both_routes(self):
        with (
            mock.patch.dict(client.os.environ, {}, clear=True),
            mock.patch.object(client, "OAUTH_FILE", FakeFile(None)),
            mock.patch.object(client, "KEY_FILE", FakeFile(None)),
        ):
            with self.assertRaises(client.LinearError) as caught:
                client.auth_mode()
            message = str(caught.exception)
            self.assertIn("Client ID", message)
            self.assertIn("Personal API key", message)

    def test_token_is_reused_until_it_nears_expiry(self):
        with (
            mock.patch.dict(
                client.os.environ,
                {client.CLIENT_ID_ENV: "id", client.CLIENT_SECRET_ENV: "secret"},
                clear=True,
            ),
            mock.patch.object(client, "fetch_token", return_value="fresh") as fetch,
        ):
            self.assertEqual(client.access_token(), "fresh")
            self.assertEqual(fetch.call_count, 1)
            client._token.update({"value": "cached", "expires_at": client.time.monotonic() + 600})
            self.assertEqual(client.access_token(), "cached")
            self.assertEqual(fetch.call_count, 1)
            client._token["expires_at"] = client.time.monotonic() - 1
            self.assertEqual(client.access_token(), "fresh")
            self.assertEqual(fetch.call_count, 2)


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_team_by_key_name_and_uuid(self):
        self.assertEqual(server.resolve_team("APP"), "team-uuid-app")
        self.assertEqual(server.resolve_team("product"), "team-uuid-app")
        self.assertEqual(
            server.resolve_team("00000000-0000-4000-8000-0000000000aa"), "00000000-0000-4000-8000-0000000000aa"
        )

    def test_unknown_team_lists_the_known_ones(self):
        with self.assertRaises(server.LinearError) as caught:
            server.resolve_team("nope")
        self.assertIn("APP/Product", str(caught.exception))

    def test_project_scoped_to_team(self):
        self.assertEqual(server.resolve_project("Product"), "proj-uuid-1")
        self.assertEqual(server.resolve_project("Sandbox", "team-uuid-xx"), "proj-uuid-2")

    def test_state_by_name_is_case_insensitive(self):
        self.assertEqual(server.resolve_state("team-uuid-app", "in progress"), "state-progress")
        self.assertEqual(server.resolve_state("team-uuid-app", "completed"), "state-done")

    def test_user_by_email_name_and_me(self):
        self.assertEqual(server.resolve_user("owner@example.com"), "user-owner")
        self.assertEqual(server.resolve_user("Claude"), "user-claude")
        self.assertEqual(server.resolve_user("me"), "user-claude")

    def test_issue_identifier_resolves_through_number_and_team_key(self):
        self.assertEqual(server.resolve_issue_id("app-17"), "issue-uuid-17")
        query, variables = self.stub.calls[-1]
        self.assertEqual(variables, {"key": "APP", "number": 17})
        self.assertIn("number: { eq: $number }", query)

    def test_unknown_issue_identifier_is_reported(self):
        with self.assertRaises(server.LinearError):
            server.resolve_issue_id("APP-999")

    def test_garbage_issue_reference_is_rejected_without_a_query(self):
        with self.assertRaises(server.LinearError):
            server.resolve_issue_id("not an issue")
        self.assertEqual(self.stub.calls, [])


class FormattingTests(unittest.TestCase):
    def test_brief_flattens_the_nested_nodes(self):
        self.assertEqual(
            server.brief(ISSUE),
            {
                "id": "APP-17",
                "uuid": "issue-uuid-17",
                "title": "0.23.0 deploy",
                "status": "Done",
                "priority": "High",
                "assignee": "owner",
                "delegate": None,
                "team": "APP",
                "project": "Product",
                "url": "https://linear.app/example/issue/APP-17",
                "updatedAt": "2026-09-21T00:48:53.948Z",
            },
        )

    def test_brief_survives_null_relations(self):
        bare = dict(ISSUE, state=None, assignee=None, team=None, project=None, priorityLabel=None, priority=0)
        out = server.brief(bare)
        self.assertIsNone(out["status"])
        self.assertIsNone(out["assignee"])
        self.assertEqual(out["priority"], "No priority")

    def test_full_adds_description_and_labels(self):
        out = server.full(ISSUE)
        self.assertEqual(out["description"], "body text")
        self.assertEqual(out["labels"], ["tooling"])
        self.assertEqual(out["creator"], "owner")
        self.assertIsNone(out["parent"])


class ToolTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_issues_builds_the_filter(self):
        server.list_issues(project="Product", team="APP", state="In Progress", assignee="owner", query="mip", limit=10)
        _, variables = self.stub.calls[-1]
        self.assertEqual(
            variables["filter"],
            {
                "team": {"id": {"eq": "team-uuid-app"}},
                "project": {"id": {"eq": "proj-uuid-1"}},
                "state": {"name": {"eqIgnoreCase": "In Progress"}},
                "assignee": {"id": {"eq": "user-owner"}},
                "searchableContent": {"contains": "mip"},
            },
        )
        self.assertEqual(variables["first"], 10)

    def test_list_issues_unassigned_and_limit_clamp(self):
        server.list_issues(assignee="unassigned", limit=5000)
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["filter"], {"assignee": {"null": True}})
        self.assertEqual(variables["first"], 250)

    def test_save_issue_creates_with_resolved_ids(self):
        server.save_issue(team="APP", title="new one", project="Product", state="Done", priority=1, assignee="owner")
        query, _ = self.stub.calls[-1]
        self.assertIn("issueCreate", query)
        self.assertEqual(
            self.stub.last_input(),
            {
                "title": "new one",
                "priority": 1,
                "projectId": "proj-uuid-1",
                "stateId": "state-done",
                "assigneeId": "user-owner",
                "delegateId": "user-claude",
                "teamId": "team-uuid-app",
            },
        )

    def test_save_issue_without_team_refuses_to_create(self):
        with self.assertRaises(server.LinearError):
            server.save_issue(title="orphan")

    def test_save_issue_without_title_refuses_to_create(self):
        with self.assertRaises(server.LinearError):
            server.save_issue(team="APP")

    def test_save_issue_updates_and_derives_the_team_for_the_state(self):
        server.save_issue(id="APP-17", state="In Progress")
        query, variables = self.stub.calls[-1]
        self.assertIn("issueUpdate", query)
        self.assertEqual(variables["id"], "issue-uuid-17")
        self.assertEqual(variables["input"], {"stateId": "state-progress"})

    def test_empty_update_is_refused(self):
        with self.assertRaises(server.LinearError):
            server.save_issue(id="APP-17")

    def test_add_comment_posts_the_resolved_uuid(self):
        out = server.add_comment("APP-17", "hello")
        self.assertEqual(self.stub.last_input(), {"issueId": "issue-uuid-17", "body": "hello"})
        self.assertEqual(out["author"], "Claude")

    def test_list_projects_filters_by_team(self):
        self.assertEqual([p["name"] for p in server.list_projects(team="XX")], ["Sandbox"])

    def test_list_issue_statuses_is_ordered_by_position(self):
        self.assertEqual([s["name"] for s in server.list_issue_statuses("APP")], ["Backlog", "In Progress", "Done"])


class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_project_creates_with_resolved_ids(self):
        out = server.save_project(
            name="zz-selftest",
            summary="one line",
            description="# body",
            state="In Progress",
            priority=2,
            lead="owner",
            setTeams=["XX"],
            startDate="2026-09-21",
            targetDate="2026-09-30",
        )
        query, _ = self.stub.calls[-1]
        self.assertIn("projectCreate", query)
        self.assertEqual(
            self.stub.last_input(),
            {
                "name": "zz-selftest",
                "description": "one line",
                "content": "# body",
                "priority": 2,
                "leadId": "user-owner",
                "statusId": "status-progress",
                "startDate": "2026-09-21",
                "targetDate": "2026-09-30",
                "teamIds": ["team-uuid-xx"],
            },
        )
        self.assertEqual(out["summary"], PROJECT_FULL["description"])
        self.assertEqual(out["teams"], ["XX"])

    def test_save_project_create_needs_a_team(self):
        with self.assertRaises(server.LinearError):
            server.save_project(name="teamless")

    def test_save_project_update_merges_added_teams(self):
        server.save_project(id="Sandbox", summary="updated", addTeams=["APP"])
        query, variables = self.stub.calls[-1]
        self.assertIn("projectUpdate", query)
        self.assertEqual(variables["id"], "proj-uuid-2")
        self.assertEqual(variables["input"], {"description": "updated", "teamIds": ["team-uuid-xx", "team-uuid-app"]})

    def test_save_project_set_teams_replaces(self):
        server.save_project(id="Sandbox", setTeams=["APP"])
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["input"], {"teamIds": ["team-uuid-app"]})

    def test_empty_project_update_is_refused(self):
        with self.assertRaises(server.LinearError):
            server.save_project(id="Sandbox")

    def test_get_project_maps_content_and_description(self):
        out = server.get_project("Sandbox")
        self.assertEqual(out["id"], "proj-uuid-2")
        self.assertEqual(out["summary"], "one line summary")
        self.assertEqual(out["description"], "# body\nmarkdown")
        self.assertEqual(out["status"], "In Progress")
        self.assertEqual(out["lead"], "owner")

    def test_archive_project_uses_project_delete(self):
        out = server.archive_project("Sandbox")
        query, variables = self.stub.calls[-1]
        self.assertIn("projectDelete", query)
        self.assertNotIn("projectArchive", query)
        self.assertEqual(variables, {"id": "proj-uuid-2"})
        self.assertEqual(out["archivedAt"], "2026-09-21T03:00:00.000Z")


class LabelCycleMilestoneTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_issue_labels_without_team_sends_no_filter(self):
        out = server.list_issue_labels()
        _, variables = self.stub.calls[-1]
        self.assertIsNone(variables["filter"])
        self.assertEqual([lbl["name"] for lbl in out], ["tooling", "bug"])
        self.assertEqual(out[1]["team"], "APP")

    def test_list_issue_labels_team_filter_keeps_workspace_labels(self):
        server.list_issue_labels(team="APP")
        _, variables = self.stub.calls[-1]
        self.assertEqual(
            variables["filter"],
            {"or": [{"team": {"id": {"eq": "team-uuid-app"}}}, {"team": {"null": True}}]},
        )

    def test_save_issue_label_creates_with_team_and_color(self):
        out = server.save_issue_label(name="zz-selftest", color="#4cb782", team="APP")
        query, _ = self.stub.calls[-1]
        self.assertIn("issueLabelCreate", query)
        self.assertEqual(self.stub.last_input(), {"name": "zz-selftest", "color": "#4cb782", "teamId": "team-uuid-app"})
        self.assertEqual(out["id"], "label-bug")

    def test_save_issue_label_updates_by_name(self):
        server.save_issue_label(id="bug", color="#111111")
        query, variables = self.stub.calls[-1]
        self.assertIn("issueLabelUpdate", query)
        self.assertEqual(variables["id"], "label-bug")
        self.assertEqual(variables["input"], {"color": "#111111"})

    def test_save_issue_label_create_needs_a_name(self):
        with self.assertRaises(server.LinearError):
            server.save_issue_label(color="#111111")

    def test_list_cycles_is_ordered_by_number(self):
        out = server.list_cycles("XX")
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["filter"], {"team": {"id": {"eq": "team-uuid-xx"}}})
        self.assertEqual([c["number"] for c in out], [1.0, 2.0])
        self.assertEqual([c["state"] for c in out], ["active", "next"])

    def test_resolve_cycle_by_alias_number_and_name(self):
        self.assertEqual(server.resolve_cycle("team-uuid-xx", "current"), "cycle-1")
        self.assertEqual(server.resolve_cycle("team-uuid-xx", "next"), "cycle-2")
        self.assertEqual(server.resolve_cycle("team-uuid-xx", "2"), "cycle-2")
        self.assertEqual(server.resolve_cycle("team-uuid-xx", "Cycle 1"), "cycle-1")

    def test_list_milestones_is_ordered_by_sort_order(self):
        out = server.list_milestones("Sandbox")
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["filter"], {"project": {"id": {"eq": "proj-uuid-2"}}})
        self.assertEqual([m["name"] for m in out], ["Alpha", "Beta"])

    def test_save_milestone_creates_under_the_project(self):
        out = server.save_milestone(project="Sandbox", name="Alpha", targetDate="2026-10-01")
        query, _ = self.stub.calls[-1]
        self.assertIn("projectMilestoneCreate", query)
        self.assertEqual(
            self.stub.last_input(), {"name": "Alpha", "targetDate": "2026-10-01", "projectId": "proj-uuid-2"}
        )
        self.assertEqual(out["project"], "Sandbox")

    def test_save_milestone_updates_by_name_within_the_project(self):
        server.save_milestone(id="Alpha", project="Sandbox", targetDate="2026-10-02")
        query, variables = self.stub.calls[-1]
        self.assertIn("projectMilestoneUpdate", query)
        self.assertEqual(variables["id"], "milestone-1")
        self.assertEqual(variables["input"], {"targetDate": "2026-10-02", "projectId": "proj-uuid-2"})

    def test_save_milestone_create_needs_a_project(self):
        with self.assertRaises(server.LinearError):
            server.save_milestone(name="orphan")


class UserCommentDocumentTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_users_filters_locally(self):
        self.assertEqual([u["name"] for u in server.list_users()], ["Claude", "owner"])
        self.assertEqual([u["name"] for u in server.list_users(query="example")], ["owner"])
        self.assertEqual(server.list_users(query="nobody"), [])

    def test_get_user_me_resolves_through_viewer(self):
        out = server.get_user("me")
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables, {"id": "user-claude"})
        self.assertEqual(out["email"], "claude@oauthapp.linear.app")
        self.assertTrue(out["app"])

    def test_list_comments_is_oldest_first(self):
        out = server.list_comments("APP-17")
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["filter"], {"issue": {"id": {"eq": "issue-uuid-17"}}})
        self.assertEqual([c["body"] for c in out], ["first", "second"])
        self.assertEqual(out[0]["author"], "Claude")

    def test_list_documents_filters_by_project_and_drops_the_body(self):
        out = server.list_documents(project="Sandbox")
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["filter"], {"project": {"id": {"eq": "proj-uuid-2"}}})
        self.assertNotIn("content", out[0])
        self.assertEqual(out[0]["title"], "Design notes")

    def test_get_document_resolves_a_title_and_returns_the_body(self):
        out = server.get_document("Design notes")
        self.assertEqual(out["content"], "# design\nbody")
        resolve_query, resolve_variables = self.stub.calls[-2]
        self.assertIn("documents(first: 2", resolve_query)
        self.assertEqual(resolve_variables, {"ref": "Design notes"})

    def test_save_document_creates_with_the_project_id(self):
        server.save_document(title="Design notes", content="# design", project="Sandbox")
        query, _ = self.stub.calls[-1]
        self.assertIn("documentCreate", query)
        self.assertEqual(
            self.stub.last_input(), {"title": "Design notes", "content": "# design", "projectId": "proj-uuid-2"}
        )

    def test_save_document_updates_by_slug(self):
        server.save_document(id="design-notes-abcd", content="# new")
        query, variables = self.stub.calls[-1]
        self.assertIn("documentUpdate", query)
        self.assertEqual(variables["id"], "doc-uuid-1")
        self.assertEqual(variables["input"], {"content": "# new"})

    def test_save_document_create_needs_a_title(self):
        with self.assertRaises(server.LinearError):
            server.save_document(content="body only")


class IssueExtensionTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_takes_labels_due_date_estimate_and_cycle(self):
        server.save_issue(
            team="APP",
            title="new one",
            labels=["tooling"],
            addLabels=["bug"],
            dueDate="2026-10-01",
            estimate=3,
            cycle="current",
        )
        query, _ = self.stub.calls[-1]
        self.assertIn("issueCreate", query)
        self.assertEqual(
            self.stub.last_input(),
            {
                "title": "new one",
                "dueDate": "2026-10-01",
                "estimate": 3,
                "cycleId": "cycle-1",
                "labelIds": ["label-tooling", "label-bug"],
                "delegateId": "user-claude",
                "teamId": "team-uuid-app",
            },
        )

    def test_team_scoping_hides_another_teams_label(self):
        with self.assertRaises(server.LinearError):
            server.save_issue(team="XX", title="new one", labels=["bug"])

    def test_update_add_labels_uses_added_label_ids(self):
        server.save_issue(id="APP-17", addLabels=["bug"])
        query, variables = self.stub.calls[-1]
        self.assertIn("issueUpdate", query)
        self.assertEqual(variables["input"], {"addedLabelIds": ["label-bug"]})

    def test_update_labels_replaces_and_add_labels_folds_in(self):
        server.save_issue(id="APP-17", labels=["tooling"], addLabels=["bug"])
        _, variables = self.stub.calls[-1]
        self.assertEqual(variables["input"], {"labelIds": ["label-tooling", "label-bug"]})

    def test_relations_are_written_after_the_issue(self):
        out = server.save_issue(
            id="APP-17", title="renamed", blockedBy=["APP-17"], blocks=["APP-17"], relatedTo=["APP-17"]
        )
        self.assertEqual([r["type"] for r in out["relations"]], ["blocks", "blockedBy", "relatedTo"])
        relation_inputs = [v["input"] for q, v in self.stub.calls if "issueRelationCreate" in q]
        self.assertEqual([i["type"] for i in relation_inputs], ["blocks", "blocks", "related"])

    def test_relations_only_update_skips_the_mutation(self):
        server.save_issue(id="APP-17", relatedTo=["APP-17"])
        mutations = [q for q, _ in self.stub.calls if "issueUpdate" in q]
        self.assertEqual(mutations, [])
        self.assertIn("issueRelationCreate", self.stub.calls[-1][0])

    def test_archive_issue_returns_the_identifier(self):
        out = server.archive_issue("APP-17")
        query, variables = self.stub.calls[-1]
        self.assertIn("issueArchive", query)
        self.assertEqual(variables, {"id": "issue-uuid-17"})
        self.assertEqual(out["id"], "APP-17")

    def test_search_issues_uses_the_search_query(self):
        out = server.search_issues("deploy", team="APP", limit=5000)
        query, variables = self.stub.calls[-1]
        self.assertIn("searchIssues(term:", query)
        self.assertEqual(variables, {"term": "deploy", "first": 250, "teamId": "team-uuid-app"})
        self.assertEqual(out[0]["id"], "APP-17")


class CancelHandoffInboxReleaseTests(unittest.TestCase):
    def setUp(self):
        server.reset_cache()
        RELEASES.clear()
        self.stub = StubGraphQL()
        patcher = mock.patch.object(server, "graphql", self.stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_there_is_no_delete_tool(self):
        self.assertFalse(hasattr(server, "delete_issue"))

    def test_cancel_comments_the_reason_then_moves_to_canceled_and_never_deletes(self):
        states = STATES + [
            {"id": "state-canceled", "name": "Canceled", "type": "canceled", "position": 3.0, "description": None}
        ]
        with mock.patch.object(server, "team_states", return_value=states):
            server.cancel_issue("APP-17", "ツールの動作確認")
        queries = [q for q, _ in self.stub.calls]
        self.assertFalse(any("issueDelete" in q or "issueArchive" in q for q in queries))
        comment = next(v for q, v in self.stub.calls if "commentCreate" in q)
        self.assertEqual(comment["input"]["body"], "キャンセル: ツールの動作確認")
        self.assertEqual(self.stub.last_input(), {"stateId": "state-canceled"})

    def test_save_issue_refuses_the_app_as_assignee(self):
        with self.assertRaises(server.LinearError) as caught:
            server.save_issue(id="APP-17", assignee="Claude")
        self.assertIn("delegate", str(caught.exception))

    def test_handoff_assigns_the_human_keeps_the_delegate_and_mentions(self):
        server.handoff("APP-17", "ゲーム内で確認してください", mention=True)
        comment = next(v for q, v in self.stub.calls if "commentCreate" in q)
        self.assertTrue(comment["input"]["body"].startswith("https://linear.app/example/profiles/owner "))
        self.assertEqual(self.stub.last_input(), {"assigneeId": "user-owner", "delegateId": "user-claude"})

    def test_inbox_lists_unread_non_noise_and_marks_only_those_read(self):
        out = server.inbox()
        self.assertEqual([n["id"] for n in out], ["n-mention"])
        self.assertEqual(out[0]["author"], "owner")
        marked = [v["id"] for q, v in self.stub.calls if "notificationUpdate" in q]
        self.assertEqual(marked, ["n-mention"])

    def test_inbox_can_peek(self):
        server.inbox(markRead=False)
        self.assertFalse([q for q, _ in self.stub.calls if "notificationUpdate" in q])

    def test_save_release_creates_once_and_links_each_issue_once(self):
        out = server.save_release("Product", "0.24.3", commitSha="4b3ace0f", notes="n", issues=["APP-17"])
        create = next(v for q, v in self.stub.calls if "releaseCreate" in q)
        self.assertEqual(create["input"]["stageId"], "stage-released")
        self.assertEqual(create["input"]["pipelineId"], "pipe-1")
        self.assertEqual(out["issues"], ["APP-17"])
        self.stub.calls.clear()
        server.save_release("Product", "0.24.3", issues=["APP-17"])
        queries = [q for q, _ in self.stub.calls]
        self.assertFalse(any("releaseCreate" in q or "issueToReleaseCreate" in q for q in queries))
        self.assertTrue(any("releaseUpdate" in q for q in queries))


if __name__ == "__main__":
    unittest.main(verbosity=2)
