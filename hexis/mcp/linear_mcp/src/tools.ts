/**
 * The tools, registered on an MCP server. Names, arguments and output shapes follow the Python
 * `linear_claude` server (30 tools). Anything that reads or writes local files - VERSION_HISTORY.md,
 * git tags, STATE.md, brief --out, progress --report-file - stays in `scripts/linear_ops.py`; the
 * tools here take text instead.
 */

import type { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import type { LinearClient } from "./linear.js";

type Result = { content: Array<{ type: "text"; text: string }> };

function text(value: unknown): Result {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

export function instructionsFor(label: string, writeTeams: string[]): string {
  return (
    `Linear access under the dedicated '${label}' identity. Every issue, update and comment ` +
    "written through these tools is attributed to it, not to the signed-in user. " +
    `Writes are limited to team ${writeTeams.join(", ")}; reads cover the whole workspace. ` +
    "Teams, projects, workflow states and assignees may be given as a name, a key or a UUID. " +
    `${label} takes work as an issue's delegate, never its assignee; the human is assigned only by ` +
    "`handoff`. Issues are never deleted: `cancel_issue` closes one as Canceled with a reason."
  );
}

export const TOOL_NAMES = [
  "linear_whoami",
  "list_teams",
  "list_projects",
  "list_issue_statuses",
  "list_issues",
  "get_issue",
  "save_issue",
  "add_comment",
  "save_project",
  "get_project",
  "archive_project",
  "list_issue_labels",
  "save_issue_label",
  "list_cycles",
  "list_milestones",
  "save_milestone",
  "list_users",
  "get_user",
  "list_comments",
  "list_documents",
  "get_document",
  "save_document",
  "archive_issue",
  "cancel_issue",
  "handoff",
  "inbox",
  "list_release_pipelines",
  "list_releases",
  "save_release",
  "search_issues",
] as const;

const refs = z.array(z.string()).optional();

export function registerTools(server: McpServer, client: () => LinearClient): void {
  server.registerTool(
    "linear_whoami",
    {
      description:
        "Show which Linear identity this route writes as, which teams it may write to, how it " +
        "authenticated, and the rate-limit headers Linear last sent.",
    },
    async () => text(await client().whoami()),
  );

  server.registerTool(
    "list_teams",
    { description: "List the Linear teams this identity can see, with their key, name and id." },
    async () => text(await client().listTeams()),
  );

  server.registerTool(
    "list_projects",
    {
      description: "List Linear projects, optionally only those accessible to one team (name, key or id).",
      inputSchema: z.object({ team: z.string().optional() }),
    },
    async ({ team }) => text(await client().listProjects(team)),
  );

  server.registerTool(
    "list_issue_statuses",
    {
      description: "List one team's workflow states - the values `save_issue` accepts as `state`.",
      inputSchema: z.object({ team: z.string() }),
    },
    async ({ team }) => text(await client().listIssueStatuses(team)),
  );

  server.registerTool(
    "list_issues",
    {
      description: "List issues filtered by project, team, workflow state, assignee and/or a text query.",
      inputSchema: z.object({
        project: z.string().optional(),
        team: z.string().optional(),
        state: z.string().optional(),
        assignee: z.string().optional(),
        query: z.string().optional(),
        limit: z.number().int().optional(),
      }),
    },
    async (args) => text(await client().listIssues(args)),
  );

  server.registerTool(
    "get_issue",
    {
      description: "Get one issue in full, including its description. `id` is an identifier like 'ERG-12' or a UUID.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().getIssue(id)),
  );

  server.registerTool(
    "save_issue",
    {
      description:
        "Create an issue (no `id`; `team` and `title` required) or update the one given by `id`. " +
        "`state` is a workflow state name such as 'In Progress', `assignee` a name, email or UUID, " +
        "`priority` 0 none / 1 urgent / 2 high / 3 medium / 4 low. " +
        "This identity takes work as the `delegate`, never as the assignee: Linear accepts `assigneeId` = " +
        "an app user and leaves it null, so an app given as `assignee` is refused. A new issue is delegated " +
        "to this route's own identity unless `delegate` names someone else or is 'none'. The human is the " +
        "assignee only when the next step is theirs (see `handoff`). `milestone` is a project milestone " +
        "name or UUID; an issue carries one. `labels` replaces the issue's labels, `addLabels` only adds; " +
        "both take label names or UUIDs. `dueDate` is 'YYYY-MM-DD', `estimate` the story-point value, " +
        "`cycle` a cycle number, a cycle name, a UUID or 'current' / 'next' / 'previous'. `blockedBy`, " +
        "`blocks` and `relatedTo` take lists of issue identifiers and are written as issue relations after " +
        "the issue itself is saved; the relations created are reported under `relations` in the result. " +
        "Only issues of this identity's own teams can be created or changed.",
      inputSchema: z.object({
        id: z.string().optional(),
        team: z.string().optional(),
        project: z.string().optional(),
        title: z.string().optional(),
        description: z.string().optional(),
        state: z.string().optional(),
        priority: z.number().int().optional(),
        assignee: z.string().optional(),
        delegate: z.string().optional(),
        milestone: z.string().optional(),
        parentId: z.string().optional(),
        labels: refs,
        addLabels: refs,
        blockedBy: refs,
        blocks: refs,
        relatedTo: refs,
        dueDate: z.string().optional(),
        estimate: z.number().int().optional(),
        cycle: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveIssue(args)),
  );

  server.registerTool(
    "add_comment",
    {
      description:
        "Comment on an issue ('ERG-12' or a UUID) under this route's Linear identity. The body is " +
        "markdown text - a report that lives in a local file is passed as its contents.",
      inputSchema: z.object({ id: z.string(), body: z.string() }),
    },
    async ({ id, body }) => text(await client().addComment(id, body)),
  );

  server.registerTool(
    "save_project",
    {
      description:
        "Create a project (no `id`; `name` and at least one team required) or update the one given by `id`. " +
        "`summary` is the one-line summary under the project title (Linear's `description` field, at most " +
        "255 characters) and `description` is the markdown body (Linear's `content` field). `state` is a " +
        "project status name such as 'In Progress', or a status type (backlog / planned / started / paused / " +
        "completed / canceled). `lead` is a name, email or UUID (an app cannot be a lead); `setTeams` " +
        "replaces the project's teams and `addTeams` adds to them, each team given as a name, key or UUID. " +
        "Dates are 'YYYY-MM-DD'. A project is writable when at least one of its teams is this identity's.",
      inputSchema: z.object({
        id: z.string().optional(),
        name: z.string().optional(),
        description: z.string().optional(),
        summary: z.string().optional(),
        state: z.string().optional(),
        priority: z.number().int().optional(),
        lead: z.string().optional(),
        addTeams: refs,
        setTeams: refs,
        startDate: z.string().optional(),
        targetDate: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveProject(args)),
  );

  server.registerTool(
    "get_project",
    {
      description: "Get one project in full, including its markdown body. `id` is a project name, slug id or UUID.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().getProject(id)),
  );

  server.registerTool(
    "archive_project",
    {
      description:
        "Archive a project. Uses `projectDelete`, which trashes it; `projectArchive` is deprecated and unused.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().archiveProject(id)),
  );

  server.registerTool(
    "list_issue_labels",
    {
      description: "List issue labels: all of them, or only one team's own plus the workspace-wide ones.",
      inputSchema: z.object({ team: z.string().optional() }),
    },
    async ({ team }) => text(await client().listIssueLabels(team)),
  );

  server.registerTool(
    "save_issue_label",
    {
      description:
        "Create an issue label (no `id`; `name` required) or update the one given by `id` (a label name or " +
        "UUID). `color` is a hex string such as '#4cb782'. Without `team` the label is workspace-wide; " +
        "`team` scopes a new label to one team (Linear refuses that to an app with 403) and only narrows " +
        "the lookup on update. `parentId` puts the label inside a label group.",
      inputSchema: z.object({
        id: z.string().optional(),
        name: z.string().optional(),
        color: z.string().optional(),
        team: z.string().optional(),
        parentId: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveIssueLabel(args)),
  );

  server.registerTool(
    "list_cycles",
    {
      description: "List one team's cycles by number. `team` is a name, key or UUID.",
      inputSchema: z.object({ team: z.string() }),
    },
    async ({ team }) => text(await client().listCycles(team)),
  );

  server.registerTool(
    "list_milestones",
    {
      description: "List a project's milestones in board order. `project` is a name, slug id or UUID.",
      inputSchema: z.object({ project: z.string() }),
    },
    async ({ project }) => text(await client().listMilestones(project)),
  );

  server.registerTool(
    "save_milestone",
    {
      description:
        "Create a project milestone (no `id`; `project` and `name` required) or update the one given by " +
        "`id`. `id` is a milestone UUID or, together with `project`, its name. `targetDate` is 'YYYY-MM-DD'.",
      inputSchema: z.object({
        id: z.string().optional(),
        project: z.string().optional(),
        name: z.string().optional(),
        targetDate: z.string().optional(),
        description: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveMilestone(args)),
  );

  server.registerTool(
    "list_users",
    {
      description:
        "List the workspace's users, optionally only those whose name, display name or email contains `query`.",
      inputSchema: z.object({ query: z.string().optional() }),
    },
    async ({ query }) => text(await client().listUsers(query)),
  );

  server.registerTool(
    "get_user",
    {
      description: "Get one user in full. `id` is a name, email or UUID; 'me' is this route's own Linear identity.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().getUser(id)),
  );

  server.registerTool(
    "list_comments",
    {
      description: "List an issue's comments, oldest first. `issue` is an identifier like 'ERG-12' or a UUID.",
      inputSchema: z.object({ issue: z.string() }),
    },
    async ({ issue }) => text(await client().listComments(issue)),
  );

  server.registerTool(
    "list_documents",
    {
      description: "List documents without their bodies, optionally only one project's (name, slug id or UUID).",
      inputSchema: z.object({ project: z.string().optional() }),
    },
    async ({ project }) => text(await client().listDocuments(project)),
  );

  server.registerTool(
    "get_document",
    {
      description: "Get one document including its markdown content. `id` is a UUID, a slug id or the exact title.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().getDocument(id)),
  );

  server.registerTool(
    "save_document",
    {
      description:
        "Create a document (no `id`; `title` required) or update the one given by `id` (UUID, slug id or " +
        "title). `content` is markdown. `project` attaches the document to a project (name, slug id or UUID).",
      inputSchema: z.object({
        id: z.string().optional(),
        title: z.string().optional(),
        content: z.string().optional(),
        project: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveDocument(args)),
  );

  server.registerTool(
    "archive_issue",
    {
      description:
        "Archive an issue ('ERG-12' or a UUID). Archived issues stay searchable and can be unarchived in Linear.",
      inputSchema: z.object({ id: z.string() }),
    },
    async ({ id }) => text(await client().archiveIssue(id)),
  );

  server.registerTool(
    "cancel_issue",
    {
      description:
        "Close an issue as Canceled, with `reason` as a comment. Issues are never deleted. `id` is an " +
        "identifier like 'ERG-12' or a UUID. Running it twice adds no second comment.",
      inputSchema: z.object({ id: z.string(), reason: z.string() }),
    },
    async ({ id, reason }) => text(await client().cancelIssue(id, reason)),
  );

  server.registerTool(
    "handoff",
    {
      description:
        "Hand the next step to a human: comment `text` (with an @mention only if `mention`), make them the " +
        "assignee and keep this identity as the delegate. The assignment is what notifies them; a mention " +
        "would notify a second time. `id` is 'ERG-12' or a UUID; `user` a name, display name, email or UUID.",
      inputSchema: z.object({
        id: z.string(),
        text: z.string(),
        user: z.string().optional(),
        mention: z.boolean().optional(),
      }),
    },
    async ({ id, text: body, user, mention }) => text(await client().handoff(id, body, user, mention)),
  );

  server.registerTool(
    "inbox",
    {
      description:
        "This app's unread notifications - @mentions, assignments, delegations, replies on its issues - oldest " +
        "first. The listed ones are marked read unless `markRead` is false, so the next call returns only what " +
        "is new. `issueAddedToView` and `issueSubscribed` are skipped (and left unread) unless `allTypes` is true.",
      inputSchema: z.object({ markRead: z.boolean().optional(), allTypes: z.boolean().optional() }),
    },
    async ({ markRead, allTypes }) => text(await client().inbox(markRead, allTypes)),
  );

  server.registerTool(
    "list_release_pipelines",
    { description: "List Linear release pipelines with their stages." },
    async () => text(await client().listReleasePipelines()),
  );

  server.registerTool(
    "list_releases",
    {
      description:
        "List one pipeline's releases with their version, SHA, stage and issues. `pipeline` is a name, slug or UUID.",
      inputSchema: z.object({ pipeline: z.string() }),
    },
    async ({ pipeline }) => text(await client().listReleases(pipeline)),
  );

  server.registerTool(
    "save_release",
    {
      description:
        "Create the release `version` in `pipeline`, or update the one that already carries that version, " +
        "link `issues` (identifiers like 'ERG-12') to it and leave the deploy comment 'v<version> で配置' " +
        "plus `notes` on each. Linking or commenting twice does nothing. `stage` is a stage name or type " +
        "(planned / started / completed / canceled); a deploy that has shipped is `completed`. `notes` becomes " +
        "the release description. VERSION_HISTORY.md and the git tag are written by `linear_ops.py release`, " +
        "not here.",
      inputSchema: z.object({
        pipeline: z.string(),
        version: z.string(),
        commitSha: z.string().optional(),
        notes: z.string().optional(),
        issues: refs,
        stage: z.string().optional(),
      }),
    },
    async (args) => text(await client().saveRelease(args)),
  );

  server.registerTool(
    "search_issues",
    {
      description: "Full-text search over issues through Linear's own `searchIssues`, optionally inside one team.",
      inputSchema: z.object({ query: z.string(), team: z.string().optional(), limit: z.number().int().optional() }),
    },
    async ({ query, team, limit }) => text(await client().searchIssues(query, team, limit)),
  );
}
