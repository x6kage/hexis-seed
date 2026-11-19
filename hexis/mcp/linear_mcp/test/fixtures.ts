/**
 * Canned Linear GraphQL responses, ported from the Python spec's `test_server.py`, plus a `fetch`
 * stub that answers from them and records every call.
 */

import { API_URL, LinearClient, TOKEN_URL } from "../src/linear.js";

export const TEAMS = [
  { id: "team-uuid-app", key: "APP", name: "Product", description: null, private: false },
  { id: "team-uuid-xx", key: "XX", name: "owner", description: null, private: false },
  { id: "team-uuid-peer", key: "PEER", name: "Peer", description: null, private: false },
];

export const PROJECTS = [
  {
    id: "proj-uuid-1",
    name: "Product",
    slugId: "product-699e",
    url: "https://linear.app/example/project/product",
    status: { name: "Backlog", type: "planned" },
    lead: null,
    teams: { nodes: [{ id: "team-uuid-app", key: "APP", name: "Product" }] },
  },
  {
    id: "proj-uuid-2",
    name: "Sandbox",
    slugId: "sandbox-0001",
    url: "https://linear.app/example/project/sandbox",
    status: { name: "Planned", type: "planned" },
    lead: null,
    teams: { nodes: [{ id: "team-uuid-xx", key: "XX", name: "owner" }] },
  },
];

export const STATES = [
  { id: "state-backlog", name: "Backlog", type: "backlog", position: 0.0, description: null },
  { id: "state-progress", name: "In Progress", type: "started", position: 1.0, description: null },
  { id: "state-done", name: "Done", type: "completed", position: 2.0, description: null },
  { id: "state-canceled", name: "Canceled", type: "canceled", position: 3.0, description: null },
];

export const USERS = [
  {
    id: "user-claude",
    name: "Claude",
    displayName: "claude",
    email: "claude@oauthapp.linear.app",
    active: true,
    app: true,
    url: "https://linear.app/example/profiles/claude",
  },
  {
    id: "user-owner",
    name: "owner",
    displayName: "owner",
    email: "owner@example.com",
    active: true,
    app: false,
    url: "https://linear.app/example/profiles/owner",
  },
];

export const ISSUE = {
  id: "issue-uuid-17",
  identifier: "APP-17",
  title: "0.23.0 deploy",
  url: "https://linear.app/example/issue/APP-17",
  priority: 2,
  priorityLabel: "High",
  createdAt: "2026-09-20T10:00:00.000Z",
  updatedAt: "2026-09-21T00:48:53.948Z",
  state: { name: "Done", type: "completed" },
  assignee: { name: "owner", email: "owner@example.com" },
  team: { key: "APP", name: "Product" },
  project: { name: "Product" },
  description: "body text",
  number: 17,
  estimate: null,
  dueDate: null,
  branchName: "owner/app-17",
  startedAt: null,
  completedAt: "2026-09-21T00:00:00.000Z",
  canceledAt: null,
  creator: { name: "owner", email: "owner@example.com" },
  parent: null,
  labels: { nodes: [{ name: "tooling" }] },
};

/** Which team each known issue belongs to, by identifier and by UUID. */
export const ISSUE_TEAMS: Record<string, { uuid: string; team: { id: string; key: string } }> = {
  "APP-17": { uuid: "issue-uuid-17", team: { id: "team-uuid-app", key: "APP" } },
  "PEER-5": { uuid: "issue-uuid-arc5", team: { id: "team-uuid-peer", key: "PEER" } },
};

export const PROJECT_STATUSES = [
  { id: "status-backlog", name: "Backlog", type: "backlog", position: 0.0 },
  { id: "status-progress", name: "In Progress", type: "started", position: 1.0 },
  { id: "status-done", name: "Completed", type: "completed", position: 2.0 },
];

export const PROJECT_FULL = {
  id: "proj-uuid-2",
  name: "Sandbox",
  slugId: "sandbox-0001",
  url: "https://linear.app/example/project/sandbox",
  description: "one line summary",
  content: "# body\nmarkdown",
  priority: 2,
  priorityLabel: "High",
  startDate: "2026-09-21",
  targetDate: "2026-09-30",
  createdAt: "2026-09-21T00:00:00.000Z",
  updatedAt: "2026-09-21T01:00:00.000Z",
  archivedAt: null,
  status: { id: "status-progress", name: "In Progress", type: "started" },
  lead: { id: "user-owner", name: "owner", email: "owner@example.com" },
  teams: { nodes: [{ id: "team-uuid-xx", key: "XX", name: "owner" }] },
};

export const LABELS = [
  {
    id: "label-tooling",
    name: "tooling",
    color: "#4cb782",
    description: null,
    isGroup: false,
    parent: null,
    team: null,
  },
  {
    id: "label-bug",
    name: "bug",
    color: "#eb5757",
    description: null,
    isGroup: false,
    parent: null,
    team: { id: "team-uuid-app", key: "APP", name: "Product" },
  },
];

export const CYCLES = [
  {
    id: "cycle-2",
    number: 2.0,
    name: "Cycle 2",
    description: null,
    startsAt: "2026-09-22T00:00:00.000Z",
    endsAt: "2026-10-06T00:00:00.000Z",
    completedAt: null,
    progress: 0.0,
    isActive: false,
    isNext: true,
    isPrevious: false,
    isFuture: true,
    isPast: false,
    team: { id: "team-uuid-xx", key: "XX", name: "owner" },
  },
  {
    id: "cycle-1",
    number: 1.0,
    name: "Cycle 1",
    description: null,
    startsAt: "2026-09-08T00:00:00.000Z",
    endsAt: "2026-09-22T00:00:00.000Z",
    completedAt: null,
    progress: 0.5,
    isActive: true,
    isNext: false,
    isPrevious: false,
    isFuture: false,
    isPast: false,
    team: { id: "team-uuid-xx", key: "XX", name: "owner" },
  },
];

export const MILESTONES = [
  {
    id: "milestone-2",
    name: "Beta",
    description: null,
    targetDate: "2026-10-15",
    sortOrder: 2.0,
    progress: 0.0,
    status: "unstarted",
    project: { id: "proj-uuid-2", name: "Sandbox" },
  },
  {
    id: "milestone-1",
    name: "Alpha",
    description: "first cut",
    targetDate: "2026-10-01",
    sortOrder: 1.0,
    progress: 0.25,
    status: "next",
    project: { id: "proj-uuid-2", name: "Sandbox" },
  },
];

export const COMMENTS = [
  {
    id: "comment-2",
    body: "second",
    url: "https://linear.app/example/issue/APP-17#comment-2",
    createdAt: "2026-09-21T02:00:00.000Z",
    updatedAt: "2026-09-21T02:00:00.000Z",
    editedAt: null,
    user: { id: "user-owner", name: "owner", email: "owner@example.com" },
    parent: null,
  },
  {
    id: "comment-1",
    body: "first",
    url: "https://linear.app/example/issue/APP-17#comment-1",
    createdAt: "2026-09-21T01:00:00.000Z",
    updatedAt: "2026-09-21T01:00:00.000Z",
    editedAt: null,
    user: { id: "user-claude", name: "Claude", email: "claude@oauthapp.linear.app" },
    parent: null,
  },
];

export const DOCUMENT = {
  id: "doc-uuid-1",
  title: "Design notes",
  slugId: "design-notes-abcd",
  url: "https://linear.app/example/document/design-notes-abcd",
  icon: null,
  color: null,
  content: "# design\nbody",
  createdAt: "2026-09-21T00:00:00.000Z",
  updatedAt: "2026-09-21T01:00:00.000Z",
  creator: { name: "Claude" },
  project: { id: "proj-uuid-2", name: "Sandbox" },
  team: null,
};

export const USER_FULL = {
  id: "user-claude",
  name: "Claude",
  displayName: "claude",
  email: "claude@oauthapp.linear.app",
  active: true,
  admin: false,
  guest: false,
  app: true,
  isMe: true,
  url: "https://linear.app/example/profiles/claude",
  timezone: "Asia/Tokyo",
  title: null,
  description: null,
  createdAt: "2026-09-21T00:00:00.000Z",
};

export const NOTIFICATIONS = [
  {
    id: "n-mention",
    type: "issueCommentMention",
    createdAt: "2026-09-23T07:00:00.000Z",
    readAt: null,
    archivedAt: null,
    title: "APP-17",
    actor: { name: "owner", displayName: "owner" },
    issue: { identifier: "APP-17", title: "0.23.0 deploy" },
    comment: { id: "c-9", body: "@claude please look", user: { name: "owner", displayName: "owner" } },
  },
  {
    id: "n-view",
    type: "issueAddedToView",
    createdAt: "2026-09-23T06:00:00.000Z",
    readAt: null,
    archivedAt: null,
    title: "x",
    actor: null,
  },
  {
    id: "n-old",
    type: "issueNewComment",
    createdAt: "2026-09-22T06:00:00.000Z",
    readAt: "2026-09-22T07:00:00.000Z",
    archivedAt: null,
    title: "y",
    actor: null,
  },
];

export const PIPELINES = [
  {
    id: "pipe-1",
    name: "Product",
    slugId: "product",
    type: "scheduled",
    url: "https://linear.app/example/pipeline/product/releases",
    stages: {
      nodes: [
        { id: "stage-planned", name: "Planned", type: "planned" },
        { id: "stage-released", name: "Released", type: "completed" },
      ],
    },
  },
];

export const RELEASE_ROW = {
  id: "release-1",
  name: "v0.24.3",
  version: "0.24.3",
  commitSha: "4b3ace0f",
  description: "notes",
  url: "https://linear.app/example/release/1",
  completedAt: null,
  stage: { id: "stage-released", name: "Released", type: "completed" },
  pipeline: { name: "Product" },
};

const PROJECT_TEAMS: Record<string, any[]> = {
  "proj-uuid-1": [{ id: "team-uuid-app", key: "APP", name: "Product" }],
  "proj-uuid-2": [{ id: "team-uuid-xx", key: "XX", name: "owner" }],
};

export interface Call {
  url: string;
  query: string;
  variables: Record<string, any>;
  headers: Record<string, string>;
  form?: URLSearchParams;
}

export class LinearStub {
  readonly calls: Call[] = [];
  readonly releases: any[] = [];
  readonly comments: any[] = COMMENTS.map((c) => ({ ...c }));
  tokenCalls = 0;
  expiresIn = 2591999;
  /** Answer the next N GraphQL calls with HTTP 401, as Linear does for a revoked token. */
  unauthorizedNext = 0;

  fetch = async (input: any, init: any = {}): Promise<Response> => {
    const url = String(input);
    const headers = (init.headers ?? {}) as Record<string, string>;
    if (url === TOKEN_URL) {
      this.tokenCalls += 1;
      const form = new URLSearchParams(init.body);
      this.calls.push({ url, query: "", variables: {}, headers, form });
      return this.json({
        access_token: `token-${this.tokenCalls}`,
        token_type: "Bearer",
        expires_in: this.expiresIn,
        scope: form.get("scope")?.split(",") ?? [],
      });
    }
    if (url !== API_URL) throw new Error(`unexpected url ${url}`);
    const { query, variables } = JSON.parse(init.body);
    this.calls.push({ url, query, variables: variables ?? {}, headers });
    if (this.unauthorizedNext > 0) {
      this.unauthorizedNext -= 1;
      return new Response(JSON.stringify({ errors: [{ message: "Authentication required" }] }), { status: 401 });
    }
    return this.json({ data: this.answer(query, variables ?? {}) });
  };

  /** GraphQL calls only, token grants excluded. */
  gql(): Call[] {
    return this.calls.filter((c) => c.url === API_URL);
  }

  last(): Call {
    const calls = this.gql();
    const call = calls[calls.length - 1];
    if (!call) throw new Error("no graphql calls recorded");
    return call;
  }

  lastInput(): any {
    return this.last().variables.input ?? {};
  }

  matching(fragment: string): Call[] {
    return this.gql().filter((c) => c.query.includes(fragment));
  }

  private json(payload: unknown, status = 200): Response {
    return new Response(JSON.stringify(payload), {
      status,
      headers: {
        "Content-Type": "application/json",
        "x-ratelimit-requests-limit": "5000",
        "x-ratelimit-requests-remaining": "4999",
        "x-ratelimit-requests-reset": "1789992538000",
      },
    });
  }

  private answer(query: string, v: Record<string, any>): any {
    if (query.includes("viewer {")) return { viewer: { ...USERS[0], admin: false } };
    if (query.includes("applicationInfo(")) {
      return { applicationInfo: { id: "app-1", name: "Claude", developer: "owner", imageUrl: null } };
    }
    if (query.includes("organization {")) return { organization: { id: "org-1", name: "owner", urlKey: "owner" } };
    if (query.includes("teams(first: 250)")) return { teams: { nodes: TEAMS } };
    if (query.includes("projects(first: 250")) {
      let nodes = PROJECTS;
      const teamFilter = v.filter?.accessibleTeams;
      if (teamFilter) {
        const wanted = teamFilter.some.id.eq;
        nodes = PROJECTS.filter((p) => p.teams.nodes.some((t) => t.id === wanted));
      }
      return { projects: { nodes } };
    }
    if (query.includes("workflowStates(first: 100")) return { workflowStates: { nodes: STATES } };
    if (query.includes("users(first: 250)")) return { users: { nodes: USERS } };
    if (query.includes("issues(first: 2")) {
      const hit = ISSUE_TEAMS[`${v.key}-${v.number}`];
      return { issues: { nodes: hit ? [{ id: hit.uuid }] : [] } };
    }
    if (query.includes("issues(first: $first")) return { issues: { nodes: [ISSUE] } };
    if (query.includes("issue(id: $id) { team")) {
      const hit = Object.values(ISSUE_TEAMS).find((i) => i.uuid === v.id);
      return { issue: { team: hit ? hit.team : { id: "team-uuid-app", key: "APP" } } };
    }
    if (query.includes("issue(id: $id)")) return { issue: ISSUE };
    if (query.includes("issueCreate")) return { issueCreate: { success: true, issue: ISSUE } };
    if (query.includes("issueUpdate")) return { issueUpdate: { success: true, issue: ISSUE } };
    if (query.includes("commentCreate")) {
      this.comments.push({ id: "comment-uuid", body: v.input.body, createdAt: "2026-09-23T00:00:00.000Z" });
      return {
        commentCreate: {
          success: true,
          comment: {
            id: "comment-uuid",
            url: "https://linear.app/example/issue/APP-17#comment-1",
            createdAt: "2026-09-21T00:48:53.948Z",
            user: { name: "Claude" },
          },
        },
      };
    }
    if (query.includes("projectStatuses(first: 100")) return { projectStatuses: { nodes: PROJECT_STATUSES } };
    if (query.includes("issueLabels(first: 250")) return { issueLabels: { nodes: LABELS } };
    if (query.includes("cycles(first: 100")) return { cycles: { nodes: CYCLES } };
    if (query.includes("projectMilestones(first: 100")) return { projectMilestones: { nodes: MILESTONES } };
    if (query.includes("projectMilestone(id: $id)")) return { projectMilestone: { project: { id: "proj-uuid-2" } } };
    if (query.includes("notifications(first:")) {
      return { notifications: { nodes: NOTIFICATIONS, pageInfo: { hasNextPage: false, endCursor: null } } };
    }
    if (query.includes("notificationUpdate")) return { notificationUpdate: { success: true } };
    if (query.includes("releasePipelines(first: 50)")) return { releasePipelines: { nodes: PIPELINES } };
    if (query.includes("releases(first: 100")) {
      const wanted = v.filter?.version?.eq;
      const byId = v.filter?.id?.eq;
      const nodes = this.releases.filter(
        (r) => (wanted === undefined || r.version === wanted) && (byId === undefined || r.id === byId),
      );
      return { releases: { nodes } };
    }
    if (query.includes("releaseCreate")) {
      this.releases.push({ ...RELEASE_ROW, id: "release-new", version: v.input.version, issues: { nodes: [] } });
      return { releaseCreate: { success: true, release: { id: "release-new" } } };
    }
    if (query.includes("releaseUpdate")) return { releaseUpdate: { success: true } };
    if (query.includes("issueToReleaseCreate")) {
      const release = this.releases.find((r) => r.id === v.input.releaseId);
      release.issues.nodes.push({ id: v.input.issueId, identifier: "APP-17" });
      return { issueToReleaseCreate: { success: true } };
    }
    if (query.includes("comments(first: 100")) return { comments: { nodes: this.comments } };
    if (query.includes("documents(first: 2"))
      return { documents: { nodes: [{ id: "doc-uuid-1", title: "Design notes" }] } };
    if (query.includes("documents(first: 100")) return { documents: { nodes: [DOCUMENT] } };
    if (query.includes("document(id: $id)")) return { document: DOCUMENT };
    if (query.includes("user(id: $id)")) return { user: USER_FULL };
    if (query.includes("searchIssues(term:")) return { searchIssues: { nodes: [ISSUE] } };
    if (query.includes("project(id: $id) { teams")) {
      return {
        project: { teams: { nodes: PROJECT_TEAMS[v.id] ?? [{ id: "team-uuid-xx", key: "XX", name: "owner" }] } },
      };
    }
    if (query.includes("project(id: $id)")) return { project: PROJECT_FULL };
    if (query.includes("projectCreate")) return { projectCreate: { success: true, project: PROJECT_FULL } };
    if (query.includes("projectUpdate")) return { projectUpdate: { success: true, project: PROJECT_FULL } };
    if (query.includes("projectDelete")) {
      return {
        projectDelete: {
          success: true,
          entity: { id: "proj-uuid-2", name: "Sandbox", archivedAt: "2026-09-21T03:00:00.000Z" },
        },
      };
    }
    if (query.includes("issueLabelCreate")) return { issueLabelCreate: { success: true, issueLabel: LABELS[1] } };
    if (query.includes("issueLabelUpdate")) return { issueLabelUpdate: { success: true, issueLabel: LABELS[1] } };
    if (query.includes("projectMilestoneCreate")) {
      return { projectMilestoneCreate: { success: true, projectMilestone: MILESTONES[1] } };
    }
    if (query.includes("projectMilestoneUpdate")) {
      return { projectMilestoneUpdate: { success: true, projectMilestone: MILESTONES[1] } };
    }
    if (query.includes("documentCreate")) return { documentCreate: { success: true, document: DOCUMENT } };
    if (query.includes("documentUpdate")) return { documentUpdate: { success: true, document: DOCUMENT } };
    if (query.includes("issueRelationCreate")) {
      return {
        issueRelationCreate: {
          success: true,
          issueRelation: {
            id: "relation-uuid",
            type: v.input.type,
            issue: { identifier: "APP-17" },
            relatedIssue: { identifier: "APP-17" },
          },
        },
      };
    }
    if (query.includes("issueArchive")) {
      return {
        issueArchive: {
          success: true,
          entity: {
            id: "issue-uuid-17",
            identifier: "APP-17",
            title: "0.23.0 deploy",
            archivedAt: "2026-09-21T03:00:00.000Z",
          },
        },
      };
    }
    throw new Error(`unexpected query: ${query}`);
  }
}

/** A client that may write to APP and XX, the two teams the Python spec's fixtures use. */
export function makeClient(writeTeams: string[] = ["APP", "XX"], label = "Claude"): LinearClient {
  return new LinearClient({ clientId: "the-id", clientSecret: "the-secret", label, writeTeams });
}
