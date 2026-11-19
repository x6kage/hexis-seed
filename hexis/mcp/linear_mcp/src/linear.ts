/**
 * Linear GraphQL client that writes as one OAuth app's actor.
 *
 * Authentication is a `client_credentials` grant against `/oauth/token` with the app's Client ID
 * and Secret in the form body; the token Linear returns is an app actor token, so every issue,
 * update and comment is attributed to the app itself. `SCOPES` must stay identical everywhere the
 * grant is requested (here and in `scripts/linear_client.py`): a grant with a different scope
 * revokes the app's existing tokens.
 *
 * One instance per identity; it holds the token and every lookup cache, so a warm Vercel
 * invocation reuses both and a cold start rebuilds them.
 *
 * Names, arguments and output shapes follow the Python spec `mcp/linear_claude/server.py`.
 * Differences: every write is limited to the identity's own teams (reads are not), and
 * `save_release` also leaves the deploy comment on each issue it links, as `linear_ops.py release`
 * does; the local-file parts of that command (VERSION_HISTORY.md, git tag) stay in the CLI.
 */

export class LinearError extends Error {}

export const API_URL = "https://api.linear.app/graphql";
export const TOKEN_URL = "https://api.linear.app/oauth/token";
export const SCOPES = "read,write,app:assignable,app:mentionable";
export const USER_AGENT = "linear-mcp/1.0";
export const PAGE_SIZE = 100;

const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const IDENTIFIER_RE = /^([A-Za-z][A-Za-z0-9]*)-([0-9]+)$/;
const MENTION_RE = /(?:https:\/\/linear\.app\/[^/\s]+\/profiles\/[^\s)\]]+|@\S+)/g;

export const PRIORITY_LABELS: Record<number, string> = {
  0: "No priority",
  1: "Urgent",
  2: "High",
  3: "Medium",
  4: "Low",
};
const INBOX_NOISE = ["issueAddedToView", "issueSubscribed"];

export type Json = any;
type Record_ = Record<string, Json>;

export interface LinearConfig {
  clientId: string;
  clientSecret: string;
  /** How the identity is named in messages, e.g. "Claude". */
  label: string;
  /** Team keys this identity may write to; reads are unrestricted. */
  writeTeams: string[];
  /** Who `handoff` assigns when no user is given (env LINEAR_HANDOFF_USER); "owner" when unset. */
  handoffUser?: string;
}

export function isUuid(value: string): boolean {
  return UUID_RE.test(String(value).trim());
}

function describe(record: Record_, keys: readonly string[]): string {
  return keys
    .filter((k) => record[k])
    .map((k) => String(record[k]))
    .join("/");
}

function field(record: Record_, key: string): string {
  const value = record[key];
  return value == null ? "" : String(value).toLowerCase();
}

/** Resolve a human reference against a list of records: exact match first, then substring. */
export function pick(candidates: Record_[], ref: string, keys: readonly string[], kind: string): Record_ {
  const wanted = String(ref).trim().toLowerCase();
  const exact = candidates.filter((c) => keys.some((k) => field(c, k) === wanted));
  if (exact.length === 1) return exact[0]!; // length === 1 just checked
  if (exact.length > 1) {
    throw new LinearError(`${kind} '${ref}' is ambiguous: ${exact.map((c) => describe(c, keys)).join(", ")}`);
  }
  const partial = candidates.filter((c) => keys.some((k) => field(c, k).includes(wanted)));
  if (partial.length === 1) return partial[0]!; // length === 1 just checked
  if (partial.length > 1) {
    throw new LinearError(`${kind} '${ref}' is ambiguous: ${partial.map((c) => describe(c, keys)).join(", ")}`);
  }
  throw new LinearError(`No ${kind} matches '${ref}'. Known: ${candidates.map((c) => describe(c, keys)).join(", ")}`);
}

function normalizeComment(body: string | null | undefined): string {
  return (body ?? "").replace(MENTION_RE, " ").split(/\s+/).filter(Boolean).join(" ");
}

function clampLimit(limit: number): number {
  return Math.max(1, Math.min(Math.trunc(limit), 250));
}

// --------------------------------------------------------------------------- queries

const VIEWER_Q = "query { viewer { id name displayName email admin } }";
const ORG_Q = "query { organization { id name urlKey } }";
const APP_Q = "query($clientId: String!) { applicationInfo(clientId: $clientId) { id name developer imageUrl } }";
const TEAMS_Q = "query { teams(first: 250) { nodes { id key name description private } } }";
const PROJECTS_Q = `query($filter: ProjectFilter) {
  projects(first: 250, filter: $filter) {
    nodes { id name slugId url status { name type } lead { name } teams(first: 25) { nodes { id key name } } }
  }
}`;
const STATES_Q = `query($teamId: ID!) {
  workflowStates(first: 100, filter: { team: { id: { eq: $teamId } } }) {
    nodes { id name type position description }
  }
}`;
const USERS_Q = "query { users(first: 250) { nodes { id name displayName email active app url } } }";
const ISSUE_TEAM_Q = "query($id: String!) { issue(id: $id) { team { id key } } }";

const ISSUE_BRIEF_FIELDS = `id identifier title url priority priorityLabel createdAt updatedAt
    state { name type } assignee { name email } delegate { name email } team { key name } project { name }`;
const ISSUE_FULL_FIELDS =
  ISSUE_BRIEF_FIELDS +
  ` description number estimate dueDate branchName startedAt completedAt canceledAt
    creator { name email } parent { identifier title } labels(first: 50) { nodes { name } }`;
const ISSUE_UPDATE_M =
  "mutation($id: String!, $input: IssueUpdateInput!) " +
  `{ issueUpdate(id: $id, input: $input) { success issue { ${ISSUE_BRIEF_FIELDS} } } }`;

const PROJECT_FIELDS = `id name slugId url description content priority priorityLabel startDate targetDate
    createdAt updatedAt archivedAt status { id name type } lead { id name email }
    teams(first: 50) { nodes { id key name } }`;
const PROJECT_Q = `query($id: String!) { project(id: $id) { ${PROJECT_FIELDS} } }`;
const PROJECT_TEAMS_Q = "query($id: String!) { project(id: $id) { teams(first: 50) { nodes { id key name } } } }";
const PROJECT_GUARD_Q = "query($id: String!) { project(id: $id) { teams(first: 50) { nodes { id key name } } name } }";
const PROJECT_STATUSES_Q = "query { projectStatuses(first: 100) { nodes { id name type position } } }";
const LABEL_FIELDS = "id name color description isGroup parent { id name } team { id key name }";
const LABELS_Q = `query($filter: IssueLabelFilter) { issueLabels(first: 250, filter: $filter) { nodes { ${LABEL_FIELDS} } } }`;
const CYCLE_FIELDS = `id number name description startsAt endsAt completedAt progress
    isActive isNext isPrevious isFuture isPast team { id key name }`;
const CYCLES_Q = `query($filter: CycleFilter) { cycles(first: 100, filter: $filter) { nodes { ${CYCLE_FIELDS} } } }`;
const MILESTONE_FIELDS = "id name description targetDate sortOrder progress status project { id name }";
const MILESTONES_Q = `query($filter: ProjectMilestoneFilter) { projectMilestones(first: 100, filter: $filter) { nodes { ${MILESTONE_FIELDS} } } }`;
const MILESTONE_PROJECT_Q = "query($id: String!) { projectMilestone(id: $id) { project { id } } }";
const COMMENT_FIELDS = "id body url createdAt updatedAt editedAt user { id name email } parent { id }";
const COMMENTS_Q = `query($filter: CommentFilter) { comments(first: 100, filter: $filter) { nodes { ${COMMENT_FIELDS} } } }`;
const DOCUMENT_FIELDS = `id title slugId url icon color content createdAt updatedAt
    creator { name } project { id name } team { id key name }`;
const DOCUMENTS_Q = `query($filter: DocumentFilter) { documents(first: 100, filter: $filter) { nodes { ${DOCUMENT_FIELDS} } } }`;
const DOCUMENT_Q = `query($id: String!) { document(id: $id) { ${DOCUMENT_FIELDS} } }`;
const USER_FIELDS = "id name displayName email active admin guest app isMe url timezone title description createdAt";
const USER_Q = `query($id: String!) { user(id: $id) { ${USER_FIELDS} } }`;
const RELATION_M = `mutation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) {
    success issueRelation { id type issue { identifier } relatedIssue { identifier } }
  }
}`;
const COMMENT_CREATE_M =
  "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id } } }";
const NOTIFICATIONS_Q = `query($first: Int!, $after: String) {
  notifications(first: $first, after: $after) {
    nodes { id type createdAt readAt archivedAt title actor { name displayName }
      ... on IssueNotification { issue { identifier title } comment { id body user { name displayName } } } }
    pageInfo { hasNextPage endCursor }
  }
}`;
const NOTIFICATION_READ_M = `mutation($id: String!, $readAt: DateTime!) {
  notificationUpdate(id: $id, input: { readAt: $readAt }) { success }
}`;
const PIPELINES_Q = `query {
  releasePipelines(first: 50) { nodes { id name slugId type url stages(first: 20) { nodes { id name type } } } }
}`;
const RELEASE_FIELDS = "id name version commitSha description url completedAt stage { id name type } pipeline { name }";
const RELEASES_Q = `query($filter: ReleaseFilter) {
  releases(first: 100, filter: $filter) { nodes { ${RELEASE_FIELDS} issues(first: 100) { nodes { id identifier } } } }
}`;

// --------------------------------------------------------------------------- formatting

export function brief(issue: Record_): Record_ {
  return {
    id: issue.identifier,
    uuid: issue.id,
    title: issue.title,
    status: issue.state?.name ?? null,
    priority: issue.priorityLabel || (PRIORITY_LABELS[issue.priority] ?? null),
    assignee: issue.assignee?.name ?? null,
    delegate: issue.delegate?.name ?? null,
    team: issue.team?.key ?? null,
    project: issue.project?.name ?? null,
    url: issue.url ?? null,
    updatedAt: issue.updatedAt ?? null,
  };
}

export function full(issue: Record_): Record_ {
  return {
    ...brief(issue),
    description: issue.description ?? null,
    number: issue.number ?? null,
    estimate: issue.estimate ?? null,
    dueDate: issue.dueDate ?? null,
    branchName: issue.branchName ?? null,
    createdAt: issue.createdAt ?? null,
    startedAt: issue.startedAt ?? null,
    completedAt: issue.completedAt ?? null,
    canceledAt: issue.canceledAt ?? null,
    creator: issue.creator?.name ?? null,
    parent: issue.parent?.identifier ?? null,
    labels: (issue.labels?.nodes ?? []).map((n: Record_) => n.name),
  };
}

function projectOut(project: Record_): Record_ {
  return {
    id: project.id,
    name: project.name ?? null,
    slugId: project.slugId ?? null,
    status: project.status?.name ?? null,
    summary: project.description ?? null,
    description: project.content ?? null,
    priority: project.priorityLabel ?? null,
    lead: project.lead?.name ?? null,
    teams: (project.teams?.nodes ?? []).map((t: Record_) => t.key),
    startDate: project.startDate ?? null,
    targetDate: project.targetDate ?? null,
    archivedAt: project.archivedAt ?? null,
    url: project.url ?? null,
    updatedAt: project.updatedAt ?? null,
  };
}

function labelOut(label: Record_): Record_ {
  return {
    id: label.id,
    name: label.name ?? null,
    color: label.color ?? null,
    description: label.description ?? null,
    isGroup: label.isGroup ?? null,
    parent: label.parent?.name ?? null,
    team: label.team?.key ?? null,
  };
}

function cycleOut(cycle: Record_): Record_ {
  let state: string | null = null;
  if (cycle.isActive) state = "active";
  else if (cycle.isNext) state = "next";
  else if (cycle.isPrevious) state = "previous";
  else if (cycle.isFuture) state = "future";
  else if (cycle.isPast) state = "past";
  return {
    id: cycle.id,
    number: cycle.number ?? null,
    name: cycle.name ?? null,
    state,
    startsAt: cycle.startsAt ?? null,
    endsAt: cycle.endsAt ?? null,
    completedAt: cycle.completedAt ?? null,
    progress: cycle.progress ?? null,
    team: cycle.team?.key ?? null,
  };
}

function milestoneOut(milestone: Record_): Record_ {
  return {
    id: milestone.id,
    name: milestone.name ?? null,
    description: milestone.description ?? null,
    targetDate: milestone.targetDate ?? null,
    status: milestone.status ?? null,
    progress: milestone.progress ?? null,
    project: milestone.project?.name ?? null,
  };
}

function userOut(user: Record_): Record_ {
  return {
    id: user.id,
    name: user.name ?? null,
    displayName: user.displayName ?? null,
    email: user.email ?? null,
    active: user.active ?? null,
    admin: user.admin ?? null,
    guest: user.guest ?? null,
    app: user.app ?? null,
    isMe: user.isMe ?? null,
    title: user.title ?? null,
    timezone: user.timezone ?? null,
    url: user.url ?? null,
  };
}

function commentOut(comment: Record_): Record_ {
  return {
    id: comment.id,
    author: comment.user?.name ?? null,
    body: comment.body ?? null,
    createdAt: comment.createdAt ?? null,
    editedAt: comment.editedAt ?? null,
    parent: comment.parent?.id ?? null,
    url: comment.url ?? null,
  };
}

function documentOut(document: Record_, withContent = true): Record_ {
  const out: Record_ = {
    id: document.id,
    title: document.title ?? null,
    slugId: document.slugId ?? null,
    project: document.project?.name ?? null,
    team: document.team?.key ?? null,
    creator: document.creator?.name ?? null,
    createdAt: document.createdAt ?? null,
    updatedAt: document.updatedAt ?? null,
    url: document.url ?? null,
  };
  if (withContent) out.content = document.content ?? null;
  return out;
}

function releaseOut(release: Record_): Record_ {
  return {
    id: release.id,
    name: release.name ?? null,
    version: release.version ?? null,
    commitSha: release.commitSha ?? null,
    description: release.description ?? null,
    stage: release.stage?.name ?? null,
    pipeline: release.pipeline?.name ?? null,
    completedAt: release.completedAt ?? null,
    issues: (release.issues?.nodes ?? []).map((i: Record_) => i.identifier),
    url: release.url ?? null,
  };
}

// --------------------------------------------------------------------------- arguments

export interface SaveIssueArgs {
  id?: string;
  team?: string;
  project?: string;
  title?: string;
  description?: string;
  state?: string;
  priority?: number;
  assignee?: string;
  delegate?: string;
  milestone?: string;
  parentId?: string;
  labels?: string[];
  addLabels?: string[];
  blockedBy?: string[];
  blocks?: string[];
  relatedTo?: string[];
  dueDate?: string;
  estimate?: number;
  cycle?: string;
}

export interface ListIssuesArgs {
  project?: string;
  team?: string;
  state?: string;
  assignee?: string;
  query?: string;
  limit?: number;
}

export interface SaveProjectArgs {
  id?: string;
  name?: string;
  description?: string;
  summary?: string;
  state?: string;
  priority?: number;
  lead?: string;
  addTeams?: string[];
  setTeams?: string[];
  startDate?: string;
  targetDate?: string;
}

export interface SaveLabelArgs {
  id?: string;
  name?: string;
  color?: string;
  team?: string;
  parentId?: string;
}

export interface SaveMilestoneArgs {
  id?: string;
  project?: string;
  name?: string;
  targetDate?: string;
  description?: string;
}

export interface SaveDocumentArgs {
  id?: string;
  title?: string;
  content?: string;
  project?: string;
}

export interface SaveReleaseArgs {
  pipeline: string;
  version: string;
  commitSha?: string;
  notes?: string;
  issues?: string[];
  stage?: string;
}

// --------------------------------------------------------------------------- client

interface Cache {
  teams: Record_[] | null;
  users: Record_[] | null;
  projects: Record_[] | null;
  states: Map<string, Record_[]>;
  viewer: Record_ | false | null;
  projectStatuses: Record_[] | null;
  labels: Record_[] | null;
}

function emptyCache(): Cache {
  return {
    teams: null,
    users: null,
    projects: null,
    states: new Map(),
    viewer: null,
    projectStatuses: null,
    labels: null,
  };
}

export class LinearClient {
  private readonly config: LinearConfig;
  private token: { value: string | null; expiresAt: number; expiresIn?: number; scope?: string; fetchedAt?: number } = {
    value: null,
    expiresAt: 0,
  };
  private rate: Record<string, string> = {};
  private cache: Cache = emptyCache();

  constructor(config: LinearConfig) {
    this.config = config;
  }

  resetToken(): void {
    this.token = { value: null, expiresAt: 0 };
  }

  resetCache(): void {
    this.cache = emptyCache();
  }

  // ------------------------------------------------------------------- token

  async fetchToken(): Promise<string> {
    const form = new URLSearchParams({
      grant_type: "client_credentials",
      client_id: this.config.clientId,
      client_secret: this.config.clientSecret,
      scope: SCOPES,
    });
    let response: Response;
    try {
      response = await fetch(TOKEN_URL, {
        method: "POST",
        body: form.toString(),
        headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
      });
    } catch (error) {
      throw new LinearError(`Cannot reach ${TOKEN_URL}: ${(error as Error).message}`);
    }
    const raw = await response.text();
    if (!response.ok) {
      throw new LinearError(
        `Linear refused the client_credentials grant (HTTP ${response.status}): ${raw} ` +
          "- check the Client ID/Secret and that 'client credentials tokens' is enabled for the app.",
      );
    }
    const payload = raw ? JSON.parse(raw) : {};
    if (!payload.access_token) {
      throw new LinearError(`No access_token in the Linear token response: ${JSON.stringify(payload)}`);
    }
    const now = Date.now() / 1000;
    this.token = {
      value: payload.access_token,
      expiresIn: payload.expires_in,
      scope: payload.scope,
      fetchedAt: now,
      expiresAt: now + Number(payload.expires_in ?? 3600) - 60,
    };
    return payload.access_token;
  }

  async accessToken(): Promise<string> {
    if (this.token.value && Date.now() / 1000 < this.token.expiresAt) return this.token.value;
    return this.fetchToken();
  }

  // --------------------------------------------------------------- transport

  /** Linear sends `x-ratelimit-requests-*` and `x-ratelimit-complexity-*` on every GraphQL answer. */
  private noteRateLimit(response: Response): void {
    response.headers.forEach((value, name) => {
      if (name.toLowerCase().startsWith("x-ratelimit-")) this.rate[name.toLowerCase()] = value;
    });
  }

  rateLimit(): Record<string, string> {
    return { ...this.rate };
  }

  async graphql(query: string, variables: Record_ = {}, retried = false): Promise<Record_> {
    let response: Response;
    try {
      response = await fetch(API_URL, {
        method: "POST",
        body: JSON.stringify({ query, variables }),
        headers: {
          Authorization: `Bearer ${await this.accessToken()}`,
          "Content-Type": "application/json",
          "User-Agent": USER_AGENT,
        },
      });
    } catch (error) {
      if (error instanceof LinearError) throw error;
      throw new LinearError(`Cannot reach ${API_URL}: ${(error as Error).message}`);
    }
    this.noteRateLimit(response);
    const raw = await response.text();
    if (response.status === 401 && !retried) {
      this.resetToken();
      return this.graphql(query, variables, true);
    }
    let body: Record_ | null = null;
    try {
      body = raw ? JSON.parse(raw) : null;
    } catch {
      body = null;
    }
    if (!response.ok || !body) throw new LinearError(`Linear returned HTTP ${response.status}: ${raw}`);
    if (body.errors?.length) throw new LinearError(JSON.stringify(body.errors));
    return body.data;
  }

  async tryGraphql(query: string, variables: Record_ = {}): Promise<Record_ | null> {
    try {
      return await this.graphql(query, variables);
    } catch (error) {
      if (error instanceof LinearError) return null;
      throw error;
    }
  }

  /** Read every page of a connection whose query takes `$first: Int!` and `$after: String`. */
  async collect(query: string, variables: Record_, key: string): Promise<Record_[]> {
    const out: Record_[] = [];
    let after: string | null = null;
    for (;;) {
      const page: Record_ = (await this.graphql(query, { ...variables, first: PAGE_SIZE, after }))[key];
      out.push(...(page.nodes ?? []));
      const info = page.pageInfo ?? {};
      if (!info.hasNextPage || !info.endCursor) return out;
      after = info.endCursor;
    }
  }

  // ----------------------------------------------------------------- lookups

  async viewer(): Promise<Record_ | null> {
    if (this.cache.viewer === null) {
      const data = await this.tryGraphql(VIEWER_Q);
      this.cache.viewer = data?.viewer ?? false;
    }
    return this.cache.viewer || null;
  }

  async allTeams(): Promise<Record_[]> {
    if (this.cache.teams === null) this.cache.teams = (await this.graphql(TEAMS_Q)).teams.nodes;
    return this.cache.teams!;
  }

  async allProjects(): Promise<Record_[]> {
    if (this.cache.projects === null) {
      this.cache.projects = (await this.graphql(PROJECTS_Q, { filter: null })).projects.nodes;
    }
    return this.cache.projects!;
  }

  async allUsers(): Promise<Record_[]> {
    if (this.cache.users === null) this.cache.users = (await this.graphql(USERS_Q)).users.nodes;
    return this.cache.users!;
  }

  async teamStates(teamId: string): Promise<Record_[]> {
    if (!this.cache.states.has(teamId)) {
      this.cache.states.set(teamId, (await this.graphql(STATES_Q, { teamId })).workflowStates.nodes);
    }
    return this.cache.states.get(teamId)!;
  }

  async allProjectStatuses(): Promise<Record_[]> {
    if (this.cache.projectStatuses === null) {
      this.cache.projectStatuses = (await this.graphql(PROJECT_STATUSES_Q)).projectStatuses.nodes;
    }
    return this.cache.projectStatuses!;
  }

  async allLabels(): Promise<Record_[]> {
    if (this.cache.labels === null) {
      this.cache.labels = (await this.graphql(LABELS_Q, { filter: null })).issueLabels.nodes;
    }
    return this.cache.labels!;
  }

  // --------------------------------------------------------------- resolution

  async resolveTeam(ref: string): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    return pick(await this.allTeams(), ref, ["key", "name"], "team").id;
  }

  async resolveProject(ref: string, teamId?: string | null): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    let candidates = await this.allProjects();
    if (teamId) {
      const scoped = candidates.filter((p) => (p.teams?.nodes ?? []).some((t: Record_) => t.id === teamId));
      if (scoped.length) candidates = scoped;
    }
    return pick(candidates, ref, ["name", "slugId"], "project").id;
  }

  async resolveState(teamId: string, ref: string): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    return pick(await this.teamStates(teamId), ref, ["name", "type"], "workflow state").id;
  }

  async resolveUser(ref: string): Promise<string> {
    const wanted = ref.trim();
    if (["me", "self"].includes(wanted.toLowerCase())) {
      const me = await this.viewer();
      if (!me) throw new LinearError("'me' cannot be resolved: this token has no Linear user (app actor token).");
      return me.id;
    }
    if (isUuid(wanted)) return wanted;
    return pick(await this.allUsers(), wanted, ["email", "name", "displayName"], "user").id;
  }

  /** Accept a UUID or a human identifier such as 'ERG-12'. */
  async resolveIssueId(ref: string): Promise<string> {
    const wanted = ref.trim();
    if (isUuid(wanted)) return wanted;
    const match = IDENTIFIER_RE.exec(wanted);
    if (!match) throw new LinearError(`'${wanted}' is neither a Linear issue UUID nor an identifier like 'ERG-12'.`);
    const key = match[1]!.toUpperCase(); // both groups in IDENTIFIER_RE are mandatory, so a match has both
    const number = Number(match[2]);
    const query = `query($key: String!, $number: Float!) {
      issues(first: 2, filter: { team: { key: { eq: $key } }, number: { eq: $number } }) { nodes { id } }
    }`;
    const nodes = (await this.graphql(query, { key, number })).issues.nodes;
    if (!nodes.length) throw new LinearError(`No issue ${wanted} found (team key '${key}', number ${number}).`);
    return nodes[0].id;
  }

  async resolveProjectStatus(ref: string): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    return pick(await this.allProjectStatuses(), ref, ["name", "type"], "project status").id;
  }

  async resolveLabel(ref: string, teamId?: string | null): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    let candidates = await this.allLabels();
    if (teamId) {
      const scoped = candidates.filter((l) => l.team?.id === teamId || !l.team);
      if (scoped.length) candidates = scoped;
    }
    return pick(candidates, ref, ["name"], "label").id;
  }

  async resolveCycle(teamId: string, ref: string | number): Promise<string> {
    const wanted = String(ref).trim();
    if (isUuid(wanted)) return wanted;
    const nodes: Record_[] = (await this.graphql(CYCLES_Q, { filter: { team: { id: { eq: teamId } } } })).cycles.nodes;
    const aliases: Record<string, string> = {
      current: "isActive",
      active: "isActive",
      next: "isNext",
      previous: "isPrevious",
      last: "isPrevious",
    };
    const lower = wanted.toLowerCase();
    if (lower in aliases) {
      const flag = aliases[lower]!; // just checked `lower in aliases`
      const hit = nodes.find((n) => n[flag]);
      if (hit) return hit.id;
      throw new LinearError(`This team has no '${wanted}' cycle.`);
    }
    if (/^\d+$/.test(lower)) {
      const hit = nodes.find((n) => Math.trunc(Number(n.number)) === Number(lower));
      if (hit) return hit.id;
      throw new LinearError(`This team has no cycle number ${lower}.`);
    }
    return pick(nodes, wanted, ["name"], "cycle").id;
  }

  async resolveMilestoneId(ref: string, projectId?: string | null): Promise<string> {
    if (isUuid(ref)) return ref.trim();
    const filter = projectId ? { project: { id: { eq: projectId } } } : null;
    const nodes = (await this.graphql(MILESTONES_Q, { filter })).projectMilestones.nodes;
    return pick(nodes, ref, ["name"], "milestone").id;
  }

  async resolveDocumentId(ref: string): Promise<string> {
    const wanted = ref.trim();
    if (isUuid(wanted)) return wanted;
    const query = `query($ref: String!) {
      documents(first: 2, filter: { or: [{ slugId: { eq: $ref } }, { title: { eqIgnoreCase: $ref } }] }) {
        nodes { id title }
      }
    }`;
    const nodes: Record_[] = (await this.graphql(query, { ref: wanted })).documents.nodes;
    if (!nodes.length)
      throw new LinearError(`No document matches '${wanted}' (tried its slug id and its exact title).`);
    if (nodes.length > 1) {
      throw new LinearError(`Document '${wanted}' is ambiguous: ${nodes.map((n) => n.title).join(", ")}`);
    }
    return nodes[0]!.id; // only the length === 1 case reaches here
  }

  async allPipelines(): Promise<Record_[]> {
    return (await this.graphql(PIPELINES_Q)).releasePipelines.nodes;
  }

  async resolvePipeline(ref: string): Promise<Record_> {
    const pipelines = await this.allPipelines();
    if (isUuid(ref)) {
      const hit = pipelines.find((p) => p.id === ref.trim());
      if (!hit) throw new LinearError(`No release pipeline has the id '${ref}'.`);
      return hit;
    }
    return pick(pipelines, ref, ["name", "slugId"], "release pipeline");
  }

  // ------------------------------------------------------------ write guard

  private refuse(what: string, keys: string[]): never {
    const owner = keys.length ? `belongs to ${keys.join(", ")}` : "belongs to no team this identity can see";
    throw new LinearError(
      `${this.config.label} writes only to team ${this.config.writeTeams.join(", ")}; ${what} ${owner}. ` +
        "Reads are unrestricted.",
    );
  }

  private writable(key: string | undefined | null): boolean {
    return !!key && this.config.writeTeams.some((t) => t.toUpperCase() === key.toUpperCase());
  }

  async teamKey(teamId: string): Promise<string | undefined> {
    return (await this.allTeams()).find((t) => t.id === teamId)?.key;
  }

  async assertTeamWritable(teamId: string): Promise<void> {
    const key = await this.teamKey(teamId);
    if (!this.writable(key)) this.refuse("the new item", key ? [key] : []);
  }

  /** Returns the issue's team id, so callers that need it do not ask twice. */
  async assertIssueWritable(issueUuid: string, label?: string): Promise<string> {
    const team = (await this.graphql(ISSUE_TEAM_Q, { id: issueUuid })).issue.team;
    if (!this.writable(team.key)) this.refuse(`issue ${label ?? issueUuid}`, [team.key]);
    return team.id;
  }

  private assertTeamsWritable(what: string, teams: Record_[]): void {
    if (!teams.some((t) => this.writable(t.key)))
      this.refuse(
        what,
        teams.map((t) => t.key),
      );
  }

  /** A project is writable when at least one of its teams is, so a cross-team project stays shared. */
  async assertProjectWritable(projectId: string): Promise<void> {
    const project = (await this.graphql(PROJECT_GUARD_Q, { id: projectId })).project;
    this.assertTeamsWritable(`project ${project.name ?? projectId}`, project.teams.nodes);
  }

  // ------------------------------------------------------------------ tools

  async whoami(): Promise<Record_> {
    const out: Record_ = {
      identity: this.config.label,
      writeTeams: this.config.writeTeams,
      auth: "oauth client_credentials (app actor)",
    };
    const me = await this.viewer();
    if (me) {
      out.viewer = me;
      out.writes_as = `${me.name} <${me.email}>`;
    }
    const app = await this.tryGraphql(APP_Q, { clientId: this.config.clientId });
    if (app) {
      out.application = app.applicationInfo;
      out.writes_as ??= `app actor (${app.applicationInfo.name})`;
    }
    out.writes_as ??= `app actor (${this.config.label})`;
    const org = await this.tryGraphql(ORG_Q);
    if (org) out.organization = org.organization;
    out.teams_visible = (await this.allTeams()).length;
    out.token = {
      scope: this.token.scope ?? null,
      expiresIn: this.token.expiresIn ?? null,
      fetchedAt: this.token.fetchedAt ? new Date(this.token.fetchedAt * 1000).toISOString() : null,
    };
    out.rateLimit = this.rateLimit();
    return out;
  }

  async listTeams(): Promise<Record_[]> {
    return (await this.allTeams()).map((t) => ({ id: t.id, key: t.key, name: t.name, private: t.private }));
  }

  async listProjects(team?: string): Promise<Record_[]> {
    let nodes: Record_[];
    if (team === undefined) {
      nodes = await this.allProjects();
    } else {
      const teamId = await this.resolveTeam(team);
      nodes = (await this.graphql(PROJECTS_Q, { filter: { accessibleTeams: { some: { id: { eq: teamId } } } } }))
        .projects.nodes;
    }
    return nodes.map((p) => ({
      id: p.id,
      name: p.name,
      status: p.status?.name ?? null,
      lead: p.lead?.name ?? null,
      teams: (p.teams?.nodes ?? []).map((t: Record_) => t.key),
      url: p.url ?? null,
    }));
  }

  async listIssueStatuses(team: string): Promise<Record_[]> {
    const states = [...(await this.teamStates(await this.resolveTeam(team)))];
    return states
      .sort((a, b) => a.position - b.position)
      .map((s) => ({ id: s.id, name: s.name, type: s.type, position: s.position }));
  }

  async listIssues(args: ListIssuesArgs): Promise<Record_[]> {
    const filter: Record_ = {};
    const teamId = args.team ? await this.resolveTeam(args.team) : null;
    if (teamId) filter.team = { id: { eq: teamId } };
    if (args.project) filter.project = { id: { eq: await this.resolveProject(args.project, teamId) } };
    if (args.state) {
      filter.state = isUuid(args.state) ? { id: { eq: args.state } } : { name: { eqIgnoreCase: args.state } };
    }
    if (args.assignee) {
      const who = args.assignee.trim().toLowerCase();
      if (who === "none" || who === "unassigned") filter.assignee = { null: true };
      else if (who === "me" || who === "self") filter.assignee = { isMe: { eq: true } };
      else filter.assignee = { id: { eq: await this.resolveUser(args.assignee) } };
    }
    if (args.query) filter.searchableContent = { contains: args.query };
    const query = `query($filter: IssueFilter, $first: Int!) {
      issues(first: $first, filter: $filter, orderBy: updatedAt) { nodes { ${ISSUE_BRIEF_FIELDS} } }
    }`;
    const variables = { filter: Object.keys(filter).length ? filter : null, first: clampLimit(args.limit ?? 50) };
    return (await this.graphql(query, variables)).issues.nodes.map(brief);
  }

  async getIssue(id: string): Promise<Record_> {
    const query = `query($id: String!) { issue(id: $id) { ${ISSUE_FULL_FIELDS} } }`;
    return full((await this.graphql(query, { id: await this.resolveIssueId(id) })).issue);
  }

  async saveIssue(args: SaveIssueArgs): Promise<Record_> {
    const updating = !!args.id;
    const issueUuid = updating ? await this.resolveIssueId(args.id!) : null;
    let teamId = args.team ? await this.resolveTeam(args.team) : null;

    if (!updating) {
      if (!teamId) throw new LinearError("Creating an issue needs `team` (name, key or id).");
      if (!args.title) throw new LinearError("Creating an issue needs `title`.");
      await this.assertTeamWritable(teamId);
    } else {
      const issueTeam = await this.assertIssueWritable(issueUuid!, args.id);
      teamId ??= issueTeam;
    }

    const payload: Record_ = {};
    if (args.title !== undefined) payload.title = args.title;
    if (args.description !== undefined) payload.description = args.description;
    if (args.priority !== undefined) payload.priority = Math.trunc(args.priority);
    if (args.project !== undefined) payload.projectId = await this.resolveProject(args.project, teamId);
    if (args.state !== undefined) payload.stateId = await this.resolveState(teamId!, args.state);
    if (args.assignee !== undefined) {
      payload.assigneeId = await this.resolveUser(args.assignee);
      if ((await this.allUsers()).some((u) => u.id === payload.assigneeId && u.app)) {
        throw new LinearError(
          `'${args.assignee}' is an app user and cannot be an assignee (Linear leaves it null); pass it as \`delegate\`.`,
        );
      }
    }
    if (args.delegate !== undefined) {
      payload.delegateId = args.delegate.trim().toLowerCase() === "none" ? null : await this.resolveUser(args.delegate);
    } else if (!updating) {
      const me = await this.viewer();
      if (me) payload.delegateId = me.id;
    }
    if (args.milestone !== undefined) {
      payload.projectMilestoneId = await this.resolveMilestoneId(args.milestone, payload.projectId);
    }
    if (args.parentId !== undefined) payload.parentId = await this.resolveIssueId(args.parentId);
    if (args.dueDate !== undefined) payload.dueDate = args.dueDate;
    if (args.estimate !== undefined) payload.estimate = Math.trunc(args.estimate);
    if (args.cycle !== undefined) payload.cycleId = await this.resolveCycle(teamId!, args.cycle);
    if (args.labels !== undefined) {
      payload.labelIds = [];
      for (const label of args.labels) payload.labelIds.push(await this.resolveLabel(label, teamId));
    }
    if (args.addLabels?.length) {
      const added: string[] = [];
      for (const label of args.addLabels) added.push(await this.resolveLabel(label, teamId));
      if (updating && args.labels === undefined) {
        payload.addedLabelIds = added;
      } else {
        const current: string[] = payload.labelIds ?? [];
        payload.labelIds = [...current, ...added.filter((l) => !current.includes(l))];
      }
    }
    const wantedRelations = !!(args.blockedBy?.length || args.blocks?.length || args.relatedTo?.length);

    let result: Record_;
    if (updating) {
      if (!Object.keys(payload).length && !wantedRelations) {
        throw new LinearError(
          "Nothing to update: pass at least one of title, description, state, priority, assignee, delegate, " +
            "milestone, project, parentId, labels, addLabels, dueDate, estimate, cycle, blockedBy, blocks, relatedTo.",
        );
      }
      if (!Object.keys(payload).length) {
        const query = `query($id: String!) { issue(id: $id) { ${ISSUE_BRIEF_FIELDS} } }`;
        result = { success: true, issue: (await this.graphql(query, { id: issueUuid })).issue };
      } else {
        result = (await this.graphql(ISSUE_UPDATE_M, { id: issueUuid, input: payload })).issueUpdate;
      }
    } else {
      payload.teamId = teamId;
      const mutation =
        "mutation($input: IssueCreateInput!) " +
        `{ issueCreate(input: $input) { success issue { ${ISSUE_BRIEF_FIELDS} } } }`;
      result = (await this.graphql(mutation, { input: payload })).issueCreate;
    }
    if (!result.success) throw new LinearError("Linear reported the write as unsuccessful.");
    const out = brief(result.issue);
    if (wantedRelations) {
      out.relations = await this.createRelations(result.issue.id, args.blocks, args.blockedBy, args.relatedTo);
    }
    return out;
  }

  /** 'blockedBy' is a 'blocks' relation with the two ends swapped: Linear has no blocked_by type. */
  private async createRelations(
    issueUuid: string,
    blocks?: string[],
    blockedBy?: string[],
    relatedTo?: string[],
  ): Promise<Record_[]> {
    const out: Record_[] = [];
    const kinds: Array<[string[] | undefined, string, string, boolean]> = [
      [blocks, "blocks", "blocks", false],
      [blockedBy, "blockedBy", "blocks", true],
      [relatedTo, "relatedTo", "related", false],
    ];
    for (const [refs, label, type, inverse] of kinds) {
      for (const ref of refs ?? []) {
        const other = await this.resolveIssueId(ref);
        const [first, second] = inverse ? [other, issueUuid] : [issueUuid, other];
        const result = (await this.graphql(RELATION_M, { input: { issueId: first, relatedIssueId: second, type } }))
          .issueRelationCreate;
        if (!result.success)
          throw new LinearError(`Linear reported the ${label} relation to '${ref}' as unsuccessful.`);
        const relation = result.issueRelation;
        out.push({
          id: relation.id,
          type: label,
          issue: relation.issue?.identifier ?? null,
          relatedIssue: relation.relatedIssue?.identifier ?? null,
        });
      }
    }
    return out;
  }

  async addComment(id: string, body: string): Promise<Record_> {
    const issueUuid = await this.resolveIssueId(id);
    await this.assertIssueWritable(issueUuid, id);
    const mutation = `mutation($input: CommentCreateInput!) {
      commentCreate(input: $input) { success comment { id url createdAt user { name } } }
    }`;
    const result = (await this.graphql(mutation, { input: { issueId: issueUuid, body } })).commentCreate;
    if (!result.success) throw new LinearError("Linear reported the comment as unsuccessful.");
    const comment = result.comment;
    return {
      id: comment.id,
      url: comment.url ?? null,
      author: comment.user?.name ?? null,
      createdAt: comment.createdAt ?? null,
    };
  }

  async saveProject(args: SaveProjectArgs): Promise<Record_> {
    const updating = !!args.id;
    const projectId = updating ? await this.resolveProject(args.id!) : null;
    if (projectId) await this.assertProjectWritable(projectId);

    const payload: Record_ = {};
    if (args.name !== undefined) payload.name = args.name;
    if (args.summary !== undefined) payload.description = args.summary;
    if (args.description !== undefined) payload.content = args.description;
    if (args.priority !== undefined) payload.priority = Math.trunc(args.priority);
    if (args.lead !== undefined) payload.leadId = await this.resolveUser(args.lead);
    if (args.state !== undefined) payload.statusId = await this.resolveProjectStatus(args.state);
    if (args.startDate !== undefined) payload.startDate = args.startDate;
    if (args.targetDate !== undefined) payload.targetDate = args.targetDate;

    const setIds: string[] = [];
    for (const t of args.setTeams ?? []) setIds.push(await this.resolveTeam(t));
    const addIds: string[] = [];
    for (const t of args.addTeams ?? []) addIds.push(await this.resolveTeam(t));

    let result: Record_;
    if (updating) {
      let teamIds = [...setIds];
      if (addIds.length) {
        if (!teamIds.length) {
          const current = (await this.graphql(PROJECT_TEAMS_Q, { id: projectId })).project.teams.nodes;
          teamIds = current.map((t: Record_) => t.id);
        }
        teamIds.push(...addIds.filter((t) => !teamIds.includes(t)));
      }
      if (teamIds.length) payload.teamIds = teamIds;
      if (!Object.keys(payload).length) {
        throw new LinearError(
          "Nothing to update: pass at least one of name, summary, description, state, priority, lead, " +
            "addTeams, setTeams, startDate, targetDate.",
        );
      }
      const mutation =
        "mutation($id: String!, $input: ProjectUpdateInput!) " +
        `{ projectUpdate(id: $id, input: $input) { success project { ${PROJECT_FIELDS} } } }`;
      result = (await this.graphql(mutation, { id: projectId, input: payload })).projectUpdate;
    } else {
      if (!args.name) throw new LinearError("Creating a project needs `name`.");
      const teamIds = [...setIds, ...addIds.filter((t) => !setIds.includes(t))];
      if (!teamIds.length) {
        throw new LinearError("Creating a project needs `setTeams` (or `addTeams`) with at least one team.");
      }
      const teams = await this.allTeams();
      this.assertTeamsWritable(
        `the new project '${args.name}'`,
        teamIds.map((id) => teams.find((t) => t.id === id) ?? { id, key: id }),
      );
      payload.teamIds = teamIds;
      const mutation =
        "mutation($input: ProjectCreateInput!) " +
        `{ projectCreate(input: $input) { success project { ${PROJECT_FIELDS} } } }`;
      result = (await this.graphql(mutation, { input: payload })).projectCreate;
    }
    if (!result.success) throw new LinearError("Linear reported the write as unsuccessful.");
    this.cache.projects = null;
    return projectOut(result.project);
  }

  async getProject(id: string): Promise<Record_> {
    return projectOut((await this.graphql(PROJECT_Q, { id: await this.resolveProject(id) })).project);
  }

  /** Uses `projectDelete`, which trashes the project; `projectArchive` is deprecated. */
  async archiveProject(id: string): Promise<Record_> {
    const projectId = await this.resolveProject(id);
    await this.assertProjectWritable(projectId);
    const mutation = "mutation($id: String!) { projectDelete(id: $id) { success entity { id name archivedAt } } }";
    const result = (await this.graphql(mutation, { id: projectId })).projectDelete;
    if (!result.success) throw new LinearError("Linear reported the archive as unsuccessful.");
    this.cache.projects = null;
    const entity = result.entity ?? {};
    return { id: entity.id ?? projectId, name: entity.name ?? null, archivedAt: entity.archivedAt ?? null };
  }

  async listIssueLabels(team?: string): Promise<Record_[]> {
    if (team === undefined) return (await this.allLabels()).map(labelOut);
    const teamId = await this.resolveTeam(team);
    const filter = { or: [{ team: { id: { eq: teamId } } }, { team: { null: true } }] };
    return (await this.graphql(LABELS_Q, { filter })).issueLabels.nodes.map(labelOut);
  }

  async saveIssueLabel(args: SaveLabelArgs): Promise<Record_> {
    const updating = !!args.id;
    const teamId = args.team ? await this.resolveTeam(args.team) : null;
    const payload: Record_ = {};
    if (args.name !== undefined) payload.name = args.name;
    if (args.color !== undefined) payload.color = args.color;
    if (args.parentId !== undefined) payload.parentId = await this.resolveLabel(args.parentId, teamId);

    let result: Record_;
    if (updating) {
      if (!Object.keys(payload).length)
        throw new LinearError("Nothing to update: pass at least one of name, color, parentId.");
      const labelId = await this.resolveLabel(args.id!, teamId);
      const label = (await this.allLabels()).find((l) => l.id === labelId);
      if (label?.team && !this.writable(label.team.key)) this.refuse(`label '${label.name}'`, [label.team.key]);
      const mutation =
        "mutation($id: String!, $input: IssueLabelUpdateInput!) " +
        `{ issueLabelUpdate(id: $id, input: $input) { success issueLabel { ${LABEL_FIELDS} } } }`;
      result = (await this.graphql(mutation, { id: labelId, input: payload })).issueLabelUpdate;
    } else {
      if (!args.name) throw new LinearError("Creating a label needs `name`.");
      if (teamId) {
        await this.assertTeamWritable(teamId);
        payload.teamId = teamId;
      }
      const mutation =
        "mutation($input: IssueLabelCreateInput!) " +
        `{ issueLabelCreate(input: $input) { success issueLabel { ${LABEL_FIELDS} } } }`;
      result = (await this.graphql(mutation, { input: payload })).issueLabelCreate;
    }
    if (!result.success) throw new LinearError("Linear reported the write as unsuccessful.");
    this.cache.labels = null;
    return labelOut(result.issueLabel);
  }

  async listCycles(team: string): Promise<Record_[]> {
    const teamId = await this.resolveTeam(team);
    const nodes: Record_[] = (await this.graphql(CYCLES_Q, { filter: { team: { id: { eq: teamId } } } })).cycles.nodes;
    return [...nodes].sort((a, b) => a.number - b.number).map(cycleOut);
  }

  async listMilestones(project: string): Promise<Record_[]> {
    const projectId = await this.resolveProject(project);
    const nodes: Record_[] = (await this.graphql(MILESTONES_Q, { filter: { project: { id: { eq: projectId } } } }))
      .projectMilestones.nodes;
    return [...nodes].sort((a, b) => a.sortOrder - b.sortOrder).map(milestoneOut);
  }

  async saveMilestone(args: SaveMilestoneArgs): Promise<Record_> {
    const updating = !!args.id;
    const projectId = args.project ? await this.resolveProject(args.project) : null;
    const payload: Record_ = {};
    if (args.name !== undefined) payload.name = args.name;
    if (args.targetDate !== undefined) payload.targetDate = args.targetDate;
    if (args.description !== undefined) payload.description = args.description;

    let result: Record_;
    if (updating) {
      if (projectId !== null) payload.projectId = projectId;
      if (!Object.keys(payload).length) {
        throw new LinearError("Nothing to update: pass at least one of name, targetDate, description, project.");
      }
      const milestoneId = await this.resolveMilestoneId(args.id!, projectId);
      const owner = (await this.graphql(MILESTONE_PROJECT_Q, { id: milestoneId })).projectMilestone.project.id;
      await this.assertProjectWritable(owner);
      if (projectId && projectId !== owner) await this.assertProjectWritable(projectId);
      const mutation =
        "mutation($id: String!, $input: ProjectMilestoneUpdateInput!) " +
        `{ projectMilestoneUpdate(id: $id, input: $input) { success projectMilestone { ${MILESTONE_FIELDS} } } }`;
      result = (await this.graphql(mutation, { id: milestoneId, input: payload })).projectMilestoneUpdate;
    } else {
      if (!projectId) throw new LinearError("Creating a milestone needs `project` (name, slug id or UUID).");
      if (!args.name) throw new LinearError("Creating a milestone needs `name`.");
      await this.assertProjectWritable(projectId);
      payload.projectId = projectId;
      const mutation =
        "mutation($input: ProjectMilestoneCreateInput!) " +
        `{ projectMilestoneCreate(input: $input) { success projectMilestone { ${MILESTONE_FIELDS} } } }`;
      result = (await this.graphql(mutation, { input: payload })).projectMilestoneCreate;
    }
    if (!result.success) throw new LinearError("Linear reported the write as unsuccessful.");
    return milestoneOut(result.projectMilestone);
  }

  async listUsers(query?: string): Promise<Record_[]> {
    let nodes = await this.allUsers();
    if (query) {
      const wanted = query.trim().toLowerCase();
      nodes = nodes.filter((u) => ["name", "displayName", "email"].some((k) => field(u, k).includes(wanted)));
    }
    return nodes.map((u) => ({ id: u.id, name: u.name, displayName: u.displayName, email: u.email, active: u.active }));
  }

  async getUser(id: string): Promise<Record_> {
    return userOut((await this.graphql(USER_Q, { id: await this.resolveUser(id) })).user);
  }

  async listComments(issue: string): Promise<Record_[]> {
    const issueUuid = await this.resolveIssueId(issue);
    const nodes: Record_[] = (await this.graphql(COMMENTS_Q, { filter: { issue: { id: { eq: issueUuid } } } })).comments
      .nodes;
    return [...nodes].sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt))).map(commentOut);
  }

  async listDocuments(project?: string): Promise<Record_[]> {
    const filter = project ? { project: { id: { eq: await this.resolveProject(project) } } } : null;
    return (await this.graphql(DOCUMENTS_Q, { filter })).documents.nodes.map((d: Record_) => documentOut(d, false));
  }

  async getDocument(id: string): Promise<Record_> {
    return documentOut((await this.graphql(DOCUMENT_Q, { id: await this.resolveDocumentId(id) })).document);
  }

  async saveDocument(args: SaveDocumentArgs): Promise<Record_> {
    const updating = !!args.id;
    const payload: Record_ = {};
    if (args.title !== undefined) payload.title = args.title;
    if (args.content !== undefined) payload.content = args.content;
    if (args.project !== undefined) {
      payload.projectId = await this.resolveProject(args.project);
      await this.assertProjectWritable(payload.projectId);
    }

    let result: Record_;
    if (updating) {
      if (!Object.keys(payload).length)
        throw new LinearError("Nothing to update: pass at least one of title, content, project.");
      const documentId = await this.resolveDocumentId(args.id!);
      const current = (await this.graphql(DOCUMENT_Q, { id: documentId })).document;
      if (current.project?.id) await this.assertProjectWritable(current.project.id);
      else if (current.team && !this.writable(current.team.key))
        this.refuse(`document '${current.title}'`, [current.team.key]);
      const mutation =
        "mutation($id: String!, $input: DocumentUpdateInput!) " +
        `{ documentUpdate(id: $id, input: $input) { success document { ${DOCUMENT_FIELDS} } } }`;
      result = (await this.graphql(mutation, { id: documentId, input: payload })).documentUpdate;
    } else {
      if (!args.title) throw new LinearError("Creating a document needs `title`.");
      const mutation =
        "mutation($input: DocumentCreateInput!) " +
        `{ documentCreate(input: $input) { success document { ${DOCUMENT_FIELDS} } } }`;
      result = (await this.graphql(mutation, { input: payload })).documentCreate;
    }
    if (!result.success) throw new LinearError("Linear reported the write as unsuccessful.");
    return documentOut(result.document);
  }

  async archiveIssue(id: string): Promise<Record_> {
    const issueUuid = await this.resolveIssueId(id);
    await this.assertIssueWritable(issueUuid, id);
    const mutation =
      "mutation($id: String!) { issueArchive(id: $id) { success entity { id identifier title archivedAt } } }";
    const result = (await this.graphql(mutation, { id: issueUuid })).issueArchive;
    if (!result.success) throw new LinearError("Linear reported the archive as unsuccessful.");
    const entity = result.entity ?? {};
    return {
      id: entity.identifier ?? null,
      uuid: entity.id ?? issueUuid,
      title: entity.title ?? null,
      archivedAt: entity.archivedAt ?? null,
    };
  }

  /** Post `body` unless a comment with the same words is already on the issue; null when it was. */
  async ensureComment(issueUuid: string, body: string): Promise<Record_ | null> {
    const wanted = normalizeComment(body);
    const nodes: Record_[] = (await this.graphql(COMMENTS_Q, { filter: { issue: { id: { eq: issueUuid } } } })).comments
      .nodes;
    if (nodes.some((c) => normalizeComment(c.body) === wanted)) return null;
    const result = (await this.graphql(COMMENT_CREATE_M, { input: { issueId: issueUuid, body } })).commentCreate;
    if (!result.success) throw new LinearError("Linear reported the comment as unsuccessful.");
    return result.comment;
  }

  async cancelIssue(id: string, reason: string): Promise<Record_> {
    const issueUuid = await this.resolveIssueId(id);
    const teamId = await this.assertIssueWritable(issueUuid, id);
    const comment = await this.ensureComment(issueUuid, `キャンセル: ${reason}`);
    const input = { stateId: await this.resolveState(teamId, "Canceled") };
    const result = (await this.graphql(ISSUE_UPDATE_M, { id: issueUuid, input })).issueUpdate;
    if (!result.success) throw new LinearError("Linear reported the cancel as unsuccessful.");
    return { ...brief(result.issue), comment: comment ? comment.id : "already there" };
  }

  async handoff(id: string, text: string, user?: string, mention = false): Promise<Record_> {
    const issueUuid = await this.resolveIssueId(id);
    await this.assertIssueWritable(issueUuid, id);
    const userId = await this.resolveUser(user || this.config.handoffUser || "owner");
    const person = (await this.allUsers()).find((u) => u.id === userId) ?? {};
    const body = mention && person.url ? `${person.url} ${text}` : text;
    const comment = await this.ensureComment(issueUuid, body);
    const input: Record_ = { assigneeId: userId };
    const me = await this.viewer();
    if (me) input.delegateId = me.id;
    const result = (await this.graphql(ISSUE_UPDATE_M, { id: issueUuid, input })).issueUpdate;
    if (!result.success) throw new LinearError("Linear reported the handoff as unsuccessful.");
    return { ...brief(result.issue), comment: comment ? comment.id : "already there" };
  }

  async inbox(markRead = true, allTypes = false): Promise<Record_[]> {
    const rows = await this.collect(NOTIFICATIONS_Q, {}, "notifications");
    const hits = rows
      .filter((r) => !r.readAt && !r.archivedAt && (allTypes || !INBOX_NOISE.includes(r.type)))
      .sort((a, b) => String(a.createdAt ?? "").localeCompare(String(b.createdAt ?? "")));
    if (markRead) {
      const now = new Date().toISOString();
      for (const row of hits) await this.graphql(NOTIFICATION_READ_M, { id: row.id, readAt: now });
    }
    return hits.map((row) => {
      const comment = row.comment ?? {};
      const author = comment.user ?? row.actor ?? {};
      return {
        id: row.id,
        type: row.type ?? null,
        issue: row.issue?.identifier ?? null,
        title: row.title ?? null,
        author: author.displayName || author.name || null,
        comment: comment.body ?? null,
        commentId: comment.id ?? null,
        createdAt: row.createdAt ?? null,
      };
    });
  }

  async listReleasePipelines(): Promise<Record_[]> {
    return (await this.allPipelines()).map((p) => ({
      id: p.id,
      name: p.name,
      slugId: p.slugId,
      type: p.type,
      stages: p.stages.nodes.map((s: Record_) => s.name),
      url: p.url,
    }));
  }

  async listReleases(pipeline: string): Promise<Record_[]> {
    const pipe = await this.resolvePipeline(pipeline);
    return (await this.graphql(RELEASES_Q, { filter: { pipeline: { id: { eq: pipe.id } } } })).releases.nodes.map(
      releaseOut,
    );
  }

  async saveRelease(args: SaveReleaseArgs): Promise<Record_> {
    const pipe = await this.resolvePipeline(args.pipeline);
    const stageId = pick(pipe.stages.nodes, args.stage ?? "completed", ["name", "type"], "release stage").id;
    const issueIds: Array<[string, string]> = [];
    for (const ref of args.issues ?? []) {
      const issueUuid = await this.resolveIssueId(ref);
      await this.assertIssueWritable(issueUuid, ref);
      issueIds.push([ref, issueUuid]);
    }
    const found: Record_[] = (
      await this.graphql(RELEASES_Q, { filter: { pipeline: { id: { eq: pipe.id } }, version: { eq: args.version } } })
    ).releases.nodes;
    const fields: Record_ = { stageId };
    if (args.commitSha !== undefined) fields.commitSha = args.commitSha;
    if (args.notes !== undefined) fields.description = args.notes;
    let releaseId: string;
    let linked: Set<string>;
    let result: Record_;
    if (found.length) {
      releaseId = found[0]!.id; // found.length just checked
      linked = new Set(found[0]!.issues.nodes.map((i: Record_) => i.id));
      const mutation =
        "mutation($id: String!, $input: ReleaseUpdateInput!) { releaseUpdate(id: $id, input: $input) { success } }";
      result = (await this.graphql(mutation, { id: releaseId, input: fields })).releaseUpdate;
    } else {
      linked = new Set();
      const mutation =
        "mutation($input: ReleaseCreateInput!) { releaseCreate(input: $input) { success release { id } } }";
      Object.assign(fields, { pipelineId: pipe.id, name: `v${args.version}`, version: args.version });
      result = (await this.graphql(mutation, { input: fields })).releaseCreate;
      releaseId = result.release?.id;
    }
    if (!result.success) throw new LinearError("Linear reported the release write as unsuccessful.");
    const link = "mutation($input: IssueToReleaseCreateInput!) { issueToReleaseCreate(input: $input) { success } }";
    const commentText = args.notes ? `v${args.version} で配置\n${args.notes}` : `v${args.version} で配置`;
    for (const [, issueUuid] of issueIds) {
      if (!linked.has(issueUuid)) {
        await this.graphql(link, { input: { issueId: issueUuid, releaseId } });
        linked.add(issueUuid);
      }
      await this.ensureComment(issueUuid, commentText);
    }
    const nodes = (await this.graphql(RELEASES_Q, { filter: { id: { eq: releaseId } } })).releases.nodes;
    return releaseOut(nodes[0]);
  }

  async searchIssues(query: string, team?: string, limit = 50): Promise<Record_[]> {
    const variables = {
      term: query,
      first: clampLimit(limit),
      teamId: team ? await this.resolveTeam(team) : null,
    };
    const gql = `query($term: String!, $first: Int!, $teamId: String) {
      searchIssues(term: $term, first: $first, teamId: $teamId) { nodes { ${ISSUE_BRIEF_FIELDS} } }
    }`;
    return (await this.graphql(gql, variables)).searchIssues.nodes.map(brief);
  }
}
