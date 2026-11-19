import { afterEach, beforeEach, describe, expect, it, setSystemTime } from "bun:test";
import { brief, full, type LinearClient, LinearError, SCOPES } from "../src/linear.js";
import { ISSUE, LinearStub, makeClient, PROJECT_FULL } from "./fixtures.js";

const realFetch = globalThis.fetch;

let stub: LinearStub;
let client: LinearClient;

beforeEach(() => {
  stub = new LinearStub();
  globalThis.fetch = stub.fetch as unknown as typeof fetch;
  client = makeClient();
});

afterEach(() => {
  globalThis.fetch = realFetch;
  setSystemTime();
});

describe("token", () => {
  it("asks for the app's fixed scope with the credentials in the form body", async () => {
    await client.listTeams();
    const grant = stub.calls[0];
    expect(grant).toBeDefined();
    expect(grant!.form!.get("grant_type")).toBe("client_credentials");
    expect(grant!.form!.get("client_id")).toBe("the-id");
    expect(grant!.form!.get("client_secret")).toBe("the-secret");
    expect(grant!.form!.get("scope")).toBe(SCOPES);
    expect(SCOPES).toBe("read,write,app:assignable,app:mentionable");
    expect(stub.last().headers.Authorization).toBe("Bearer token-1");
  });

  it("reuses the token until it nears expiry", async () => {
    setSystemTime(new Date("2026-09-23T00:00:00Z"));
    stub.expiresIn = 3600;
    await client.graphql("query { teams(first: 250) { nodes { id } } }");
    await client.graphql("query { teams(first: 250) { nodes { id } } }");
    expect(stub.tokenCalls).toBe(1);
    setSystemTime(new Date("2026-09-23T00:59:30Z"));
    await client.graphql("query { teams(first: 250) { nodes { id } } }");
    expect(stub.tokenCalls).toBe(2);
    expect(stub.last().headers.Authorization).toBe("Bearer token-2");
  });

  it("refetches the token once on a 401 and retries the call", async () => {
    await client.listTeams();
    client.resetCache();
    stub.unauthorizedNext = 1;
    const teams = await client.listTeams();
    expect(teams.map((t) => t.key)).toEqual(["APP", "XX", "PEER"]);
    expect(stub.tokenCalls).toBe(2);
  });

  it("gives up after a second 401 instead of looping", async () => {
    stub.unauthorizedNext = 2;
    await expect(client.listTeams()).rejects.toThrow("HTTP 401");
    expect(stub.tokenCalls).toBe(2);
  });

  it("reports a refused grant with the reason Linear gave", async () => {
    globalThis.fetch = (async () =>
      new Response('{"error":"invalid_client"}', { status: 401 })) as unknown as typeof fetch;
    await expect(client.listTeams()).rejects.toThrow("Linear refused the client_credentials grant (HTTP 401)");
  });

  it("turns GraphQL errors into a LinearError", async () => {
    globalThis.fetch = (async (url: string) =>
      url.includes("oauth")
        ? new Response(JSON.stringify({ access_token: "t", expires_in: 100 }))
        : new Response(JSON.stringify({ errors: [{ message: "boom" }] }), {
            status: 400,
          })) as unknown as typeof fetch;
    await expect(client.listTeams()).rejects.toThrow(LinearError);
  });

  it("keeps the rate-limit headers Linear sent last", async () => {
    await client.listTeams();
    expect(client.rateLimit()).toMatchObject({
      "x-ratelimit-requests-limit": "5000",
      "x-ratelimit-requests-remaining": "4999",
    });
  });
});

describe("resolution", () => {
  it("resolves a team by key, name and uuid", async () => {
    expect(await client.resolveTeam("APP")).toBe("team-uuid-app");
    expect(await client.resolveTeam("product")).toBe("team-uuid-app");
    expect(await client.resolveTeam("00000000-0000-4000-8000-0000000000aa")).toBe(
      "00000000-0000-4000-8000-0000000000aa",
    );
  });

  it("lists the known teams when one does not match", async () => {
    await expect(client.resolveTeam("nope")).rejects.toThrow("APP/Product");
  });

  it("scopes a project to a team", async () => {
    expect(await client.resolveProject("Product")).toBe("proj-uuid-1");
    expect(await client.resolveProject("Sandbox", "team-uuid-xx")).toBe("proj-uuid-2");
  });

  it("matches a state by name or type, case-insensitively", async () => {
    expect(await client.resolveState("team-uuid-app", "in progress")).toBe("state-progress");
    expect(await client.resolveState("team-uuid-app", "completed")).toBe("state-done");
  });

  it("resolves a user by email, name and 'me'", async () => {
    expect(await client.resolveUser("owner@example.com")).toBe("user-owner");
    expect(await client.resolveUser("Claude")).toBe("user-claude");
    expect(await client.resolveUser("me")).toBe("user-claude");
  });

  it("resolves an identifier through its team key and number", async () => {
    expect(await client.resolveIssueId("app-17")).toBe("issue-uuid-17");
    expect(stub.last().variables).toEqual({ key: "APP", number: 17 });
    expect(stub.last().query).toContain("number: { eq: $number }");
  });

  it("reports an unknown identifier", async () => {
    await expect(client.resolveIssueId("APP-999")).rejects.toThrow(LinearError);
  });

  it("rejects a garbage reference without a query", async () => {
    await expect(client.resolveIssueId("not an issue")).rejects.toThrow(LinearError);
    expect(stub.calls).toEqual([]);
  });
});

describe("formatting", () => {
  it("flattens the nested nodes", () => {
    expect(brief(ISSUE)).toEqual({
      id: "APP-17",
      uuid: "issue-uuid-17",
      title: "0.23.0 deploy",
      status: "Done",
      priority: "High",
      assignee: "owner",
      delegate: null,
      team: "APP",
      project: "Product",
      url: "https://linear.app/example/issue/APP-17",
      updatedAt: "2026-09-21T00:48:53.948Z",
    });
  });

  it("survives null relations", () => {
    const out = brief({
      ...ISSUE,
      state: null,
      assignee: null,
      team: null,
      project: null,
      priorityLabel: null,
      priority: 0,
    });
    expect(out.status).toBeNull();
    expect(out.assignee).toBeNull();
    expect(out.priority).toBe("No priority");
  });

  it("adds the description and labels in full", () => {
    const out = full(ISSUE);
    expect(out.description).toBe("body text");
    expect(out.labels).toEqual(["tooling"]);
    expect(out.creator).toBe("owner");
    expect(out.parent).toBeNull();
  });
});

describe("issues", () => {
  it("builds the list filter", async () => {
    await client.listIssues({
      project: "Product",
      team: "APP",
      state: "In Progress",
      assignee: "owner",
      query: "mip",
      limit: 10,
    });
    expect(stub.last().variables.filter).toEqual({
      team: { id: { eq: "team-uuid-app" } },
      project: { id: { eq: "proj-uuid-1" } },
      state: { name: { eqIgnoreCase: "In Progress" } },
      assignee: { id: { eq: "user-owner" } },
      searchableContent: { contains: "mip" },
    });
    expect(stub.last().variables.first).toBe(10);
  });

  it("filters unassigned and clamps the limit", async () => {
    await client.listIssues({ assignee: "unassigned", limit: 5000 });
    expect(stub.last().variables.filter).toEqual({ assignee: { null: true } });
    expect(stub.last().variables.first).toBe(250);
  });

  it("creates with resolved ids and delegates to the calling identity", async () => {
    await client.saveIssue({
      team: "APP",
      title: "new one",
      project: "Product",
      state: "Done",
      priority: 1,
      assignee: "owner",
    });
    expect(stub.last().query).toContain("issueCreate");
    expect(stub.lastInput()).toEqual({
      title: "new one",
      priority: 1,
      projectId: "proj-uuid-1",
      stateId: "state-done",
      assigneeId: "user-owner",
      delegateId: "user-claude",
      teamId: "team-uuid-app",
    });
  });

  it("refuses to create without a team", async () => {
    await expect(client.saveIssue({ title: "orphan" })).rejects.toThrow("needs `team`");
  });

  it("refuses to create without a title", async () => {
    await expect(client.saveIssue({ team: "APP" })).rejects.toThrow("needs `title`");
  });

  it("updates and derives the team for the state", async () => {
    await client.saveIssue({ id: "APP-17", state: "In Progress" });
    expect(stub.last().query).toContain("issueUpdate");
    expect(stub.last().variables.id).toBe("issue-uuid-17");
    expect(stub.last().variables.input).toEqual({ stateId: "state-progress" });
  });

  it("refuses an empty update", async () => {
    await expect(client.saveIssue({ id: "APP-17" })).rejects.toThrow("Nothing to update");
  });

  it("comments on the resolved uuid", async () => {
    const out = await client.addComment("APP-17", "hello");
    expect(stub.lastInput()).toEqual({ issueId: "issue-uuid-17", body: "hello" });
    expect(out.author).toBe("Claude");
  });

  it("filters projects by team", async () => {
    expect((await client.listProjects("XX")).map((p) => p.name)).toEqual(["Sandbox"]);
  });

  it("orders statuses by position", async () => {
    expect((await client.listIssueStatuses("APP")).map((s) => s.name)).toEqual([
      "Backlog",
      "In Progress",
      "Done",
      "Canceled",
    ]);
  });

  it("takes labels, due date, estimate and cycle on create", async () => {
    await client.saveIssue({
      team: "APP",
      title: "new one",
      labels: ["tooling"],
      addLabels: ["bug"],
      dueDate: "2026-10-01",
      estimate: 3,
      cycle: "current",
    });
    expect(stub.last().query).toContain("issueCreate");
    expect(stub.lastInput()).toEqual({
      title: "new one",
      dueDate: "2026-10-01",
      estimate: 3,
      cycleId: "cycle-1",
      labelIds: ["label-tooling", "label-bug"],
      delegateId: "user-claude",
      teamId: "team-uuid-app",
    });
  });

  it("hides another team's label", async () => {
    await expect(client.saveIssue({ team: "XX", title: "new one", labels: ["bug"] })).rejects.toThrow(LinearError);
  });

  it("uses addedLabelIds for addLabels on update", async () => {
    await client.saveIssue({ id: "APP-17", addLabels: ["bug"] });
    expect(stub.last().query).toContain("issueUpdate");
    expect(stub.last().variables.input).toEqual({ addedLabelIds: ["label-bug"] });
  });

  it("replaces labels and folds addLabels in", async () => {
    await client.saveIssue({ id: "APP-17", labels: ["tooling"], addLabels: ["bug"] });
    expect(stub.last().variables.input).toEqual({ labelIds: ["label-tooling", "label-bug"] });
  });

  it("writes relations after the issue, blockedBy as a swapped blocks", async () => {
    const out = await client.saveIssue({
      id: "APP-17",
      title: "renamed",
      blockedBy: ["APP-17"],
      blocks: ["APP-17"],
      relatedTo: ["APP-17"],
    });
    expect(out.relations.map((r: any) => r.type)).toEqual(["blocks", "blockedBy", "relatedTo"]);
    expect(stub.matching("issueRelationCreate").map((c) => c.variables.input.type)).toEqual([
      "blocks",
      "blocks",
      "related",
    ]);
  });

  it("skips the update mutation for a relations-only update", async () => {
    await client.saveIssue({ id: "APP-17", relatedTo: ["APP-17"] });
    expect(stub.matching("issueUpdate")).toEqual([]);
    expect(stub.last().query).toContain("issueRelationCreate");
  });

  it("archives and returns the identifier", async () => {
    const out = await client.archiveIssue("APP-17");
    expect(stub.last().query).toContain("issueArchive");
    expect(stub.last().variables).toEqual({ id: "issue-uuid-17" });
    expect(out.id).toBe("APP-17");
  });

  it("searches through searchIssues", async () => {
    const out = await client.searchIssues("deploy", "APP", 5000);
    expect(stub.last().query).toContain("searchIssues(term:");
    expect(stub.last().variables).toEqual({ term: "deploy", first: 250, teamId: "team-uuid-app" });
    expect(out[0]).toBeDefined();
    expect(out[0]!.id).toBe("APP-17");
  });
});

describe("projects", () => {
  it("creates with resolved ids", async () => {
    const out = await client.saveProject({
      name: "zz-selftest",
      summary: "one line",
      description: "# body",
      state: "In Progress",
      priority: 2,
      lead: "owner",
      setTeams: ["XX"],
      startDate: "2026-09-21",
      targetDate: "2026-09-30",
    });
    expect(stub.last().query).toContain("projectCreate");
    expect(stub.lastInput()).toEqual({
      name: "zz-selftest",
      description: "one line",
      content: "# body",
      priority: 2,
      leadId: "user-owner",
      statusId: "status-progress",
      startDate: "2026-09-21",
      targetDate: "2026-09-30",
      teamIds: ["team-uuid-xx"],
    });
    expect(out.summary).toBe(PROJECT_FULL.description);
    expect(out.teams).toEqual(["XX"]);
  });

  it("needs a team to create", async () => {
    await expect(client.saveProject({ name: "teamless" })).rejects.toThrow("at least one team");
  });

  it("merges added teams on update", async () => {
    await client.saveProject({ id: "Sandbox", summary: "updated", addTeams: ["APP"] });
    expect(stub.last().query).toContain("projectUpdate");
    expect(stub.last().variables.id).toBe("proj-uuid-2");
    expect(stub.last().variables.input).toEqual({ description: "updated", teamIds: ["team-uuid-xx", "team-uuid-app"] });
  });

  it("replaces teams with setTeams", async () => {
    await client.saveProject({ id: "Sandbox", setTeams: ["APP"] });
    expect(stub.last().variables.input).toEqual({ teamIds: ["team-uuid-app"] });
  });

  it("refuses an empty update", async () => {
    await expect(client.saveProject({ id: "Sandbox" })).rejects.toThrow("Nothing to update");
  });

  it("maps content and description on get", async () => {
    const out = await client.getProject("Sandbox");
    expect(out.id).toBe("proj-uuid-2");
    expect(out.summary).toBe("one line summary");
    expect(out.description).toBe("# body\nmarkdown");
    expect(out.status).toBe("In Progress");
    expect(out.lead).toBe("owner");
  });

  it("archives through projectDelete", async () => {
    const out = await client.archiveProject("Sandbox");
    expect(stub.last().query).toContain("projectDelete");
    expect(stub.last().query).not.toContain("projectArchive");
    expect(stub.last().variables).toEqual({ id: "proj-uuid-2" });
    expect(out.archivedAt).toBe("2026-09-21T03:00:00.000Z");
  });
});

describe("labels, cycles, milestones", () => {
  it("sends no filter for all labels", async () => {
    const out = await client.listIssueLabels();
    expect(stub.last().variables.filter).toBeNull();
    expect(out.map((l) => l.name)).toEqual(["tooling", "bug"]);
    expect(out[1]).toBeDefined();
    expect(out[1]!.team).toBe("APP");
  });

  it("keeps workspace labels in a team filter", async () => {
    await client.listIssueLabels("APP");
    expect(stub.last().variables.filter).toEqual({
      or: [{ team: { id: { eq: "team-uuid-app" } } }, { team: { null: true } }],
    });
  });

  it("creates a label with team and colour", async () => {
    const out = await client.saveIssueLabel({ name: "zz-selftest", color: "#4cb782", team: "APP" });
    expect(stub.last().query).toContain("issueLabelCreate");
    expect(stub.lastInput()).toEqual({ name: "zz-selftest", color: "#4cb782", teamId: "team-uuid-app" });
    expect(out.id).toBe("label-bug");
  });

  it("updates a label by name", async () => {
    await client.saveIssueLabel({ id: "bug", color: "#111111" });
    expect(stub.last().query).toContain("issueLabelUpdate");
    expect(stub.last().variables.id).toBe("label-bug");
    expect(stub.last().variables.input).toEqual({ color: "#111111" });
  });

  it("needs a name to create a label", async () => {
    await expect(client.saveIssueLabel({ color: "#111111" })).rejects.toThrow("needs `name`");
  });

  it("orders cycles by number", async () => {
    const out = await client.listCycles("XX");
    expect(stub.last().variables.filter).toEqual({ team: { id: { eq: "team-uuid-xx" } } });
    expect(out.map((c) => c.number)).toEqual([1, 2]);
    expect(out.map((c) => c.state)).toEqual(["active", "next"]);
  });

  it("resolves a cycle by alias, number and name", async () => {
    expect(await client.resolveCycle("team-uuid-xx", "current")).toBe("cycle-1");
    expect(await client.resolveCycle("team-uuid-xx", "next")).toBe("cycle-2");
    expect(await client.resolveCycle("team-uuid-xx", "2")).toBe("cycle-2");
    expect(await client.resolveCycle("team-uuid-xx", "Cycle 1")).toBe("cycle-1");
  });

  it("orders milestones by sort order", async () => {
    const out = await client.listMilestones("Sandbox");
    expect(stub.last().variables.filter).toEqual({ project: { id: { eq: "proj-uuid-2" } } });
    expect(out.map((m) => m.name)).toEqual(["Alpha", "Beta"]);
  });

  it("creates a milestone under the project", async () => {
    const out = await client.saveMilestone({ project: "Sandbox", name: "Alpha", targetDate: "2026-10-01" });
    expect(stub.last().query).toContain("projectMilestoneCreate");
    expect(stub.lastInput()).toEqual({ name: "Alpha", targetDate: "2026-10-01", projectId: "proj-uuid-2" });
    expect(out.project).toBe("Sandbox");
  });

  it("updates a milestone by name within the project", async () => {
    await client.saveMilestone({ id: "Alpha", project: "Sandbox", targetDate: "2026-10-02" });
    expect(stub.last().query).toContain("projectMilestoneUpdate");
    expect(stub.last().variables.id).toBe("milestone-1");
    expect(stub.last().variables.input).toEqual({ targetDate: "2026-10-02", projectId: "proj-uuid-2" });
  });

  it("needs a project to create a milestone", async () => {
    await expect(client.saveMilestone({ name: "orphan" })).rejects.toThrow("needs `project`");
  });
});

describe("users, comments, documents", () => {
  it("filters users locally", async () => {
    expect((await client.listUsers()).map((u) => u.name)).toEqual(["Claude", "owner"]);
    expect((await client.listUsers("example")).map((u) => u.name)).toEqual(["owner"]);
    expect(await client.listUsers("nobody")).toEqual([]);
  });

  it("resolves 'me' through the viewer", async () => {
    const out = await client.getUser("me");
    expect(stub.last().variables).toEqual({ id: "user-claude" });
    expect(out.email).toBe("claude@oauthapp.linear.app");
    expect(out.app).toBe(true);
  });

  it("lists comments oldest first", async () => {
    const out = await client.listComments("APP-17");
    expect(stub.last().variables.filter).toEqual({ issue: { id: { eq: "issue-uuid-17" } } });
    expect(out.map((c) => c.body)).toEqual(["first", "second"]);
    expect(out[0]).toBeDefined();
    expect(out[0]!.author).toBe("Claude");
  });

  it("filters documents by project and drops the body", async () => {
    const out = await client.listDocuments("Sandbox");
    expect(stub.last().variables.filter).toEqual({ project: { id: { eq: "proj-uuid-2" } } });
    expect(out[0]).not.toHaveProperty("content");
    expect(out[0]).toBeDefined();
    expect(out[0]!.title).toBe("Design notes");
  });

  it("resolves a document title and returns the body", async () => {
    const out = await client.getDocument("Design notes");
    expect(out.content).toBe("# design\nbody");
    const calls = stub.gql();
    const secondLast = calls[calls.length - 2];
    expect(secondLast).toBeDefined();
    expect(secondLast!.query).toContain("documents(first: 2");
    expect(secondLast!.variables).toEqual({ ref: "Design notes" });
  });

  it("creates a document with the project id", async () => {
    await client.saveDocument({ title: "Design notes", content: "# design", project: "Sandbox" });
    expect(stub.last().query).toContain("documentCreate");
    expect(stub.lastInput()).toEqual({ title: "Design notes", content: "# design", projectId: "proj-uuid-2" });
  });

  it("updates a document by slug", async () => {
    await client.saveDocument({ id: "design-notes-abcd", content: "# new" });
    expect(stub.last().query).toContain("documentUpdate");
    expect(stub.last().variables.id).toBe("doc-uuid-1");
    expect(stub.last().variables.input).toEqual({ content: "# new" });
  });

  it("needs a title to create a document", async () => {
    await expect(client.saveDocument({ content: "body only" })).rejects.toThrow("needs `title`");
  });
});

describe("cancel, handoff, inbox, release", () => {
  it("comments the reason, moves to Canceled and never deletes", async () => {
    await client.cancelIssue("APP-17", "ツールの動作確認");
    const queries = stub.gql().map((c) => c.query);
    expect(queries.some((q) => q.includes("issueDelete") || q.includes("issueArchive"))).toBe(false);
    const cancelComment = stub.matching("commentCreate")[0];
    expect(cancelComment).toBeDefined();
    expect(cancelComment!.variables.input.body).toBe("キャンセル: ツールの動作確認");
    expect(stub.lastInput()).toEqual({ stateId: "state-canceled" });
  });

  it("adds no second cancel comment when run twice", async () => {
    await client.cancelIssue("APP-17", "dup");
    const second = await client.cancelIssue("APP-17", "dup");
    expect(stub.matching("commentCreate").length).toBe(1);
    expect(second.comment).toBe("already there");
  });

  it("refuses the app as assignee", async () => {
    await expect(client.saveIssue({ id: "APP-17", assignee: "Claude" })).rejects.toThrow("delegate");
  });

  it("hands off: assigns the human, keeps the delegate, mentions only when asked", async () => {
    await client.handoff("APP-17", "ゲーム内で確認してください", "owner", true);
    const handoffComment = stub.matching("commentCreate")[0];
    expect(handoffComment).toBeDefined();
    expect(handoffComment!.variables.input.body.startsWith("https://linear.app/example/profiles/owner ")).toBe(true);
    expect(stub.lastInput()).toEqual({ assigneeId: "user-owner", delegateId: "user-claude" });
  });

  it("does not mention by default", async () => {
    await client.handoff("APP-17", "確認してください");
    const noMentionComment = stub.matching("commentCreate")[0];
    expect(noMentionComment).toBeDefined();
    expect(noMentionComment!.variables.input.body).toBe("確認してください");
  });

  it("lists unread non-noise notifications and marks only those read", async () => {
    const out = await client.inbox();
    expect(out.map((n) => n.id)).toEqual(["n-mention"]);
    expect(out[0]).toBeDefined();
    expect(out[0]!.author).toBe("owner");
    expect(stub.matching("notificationUpdate").map((c) => c.variables.id)).toEqual(["n-mention"]);
  });

  it("can peek at the inbox", async () => {
    await client.inbox(false);
    expect(stub.matching("notificationUpdate")).toEqual([]);
  });

  it("includes the noise with allTypes", async () => {
    const out = await client.inbox(false, true);
    expect(out.map((n) => n.id)).toEqual(["n-view", "n-mention"]);
  });

  it("creates a release once, links each issue once and comments the deploy once", async () => {
    const out = await client.saveRelease({
      pipeline: "Product",
      version: "0.24.3",
      commitSha: "4b3ace0f",
      notes: "n",
      issues: ["APP-17"],
    });
    const create = stub.matching("releaseCreate")[0];
    expect(create).toBeDefined();
    expect(create!.variables.input.stageId).toBe("stage-released");
    expect(create!.variables.input.pipelineId).toBe("pipe-1");
    expect(out.issues).toEqual(["APP-17"]);
    const deployComment = stub.matching("commentCreate")[0];
    expect(deployComment).toBeDefined();
    expect(deployComment!.variables.input.body).toBe("v0.24.3 で配置\nn");
    stub.calls.length = 0;
    await client.saveRelease({ pipeline: "Product", version: "0.24.3", notes: "n", issues: ["APP-17"] });
    const queries = stub.gql().map((c) => c.query);
    expect(queries.some((q) => q.includes("releaseCreate") || q.includes("issueToReleaseCreate"))).toBe(false);
    expect(queries.some((q) => q.includes("commentCreate"))).toBe(false);
    expect(queries.some((q) => q.includes("releaseUpdate"))).toBe(true);
  });

  it("lists pipelines with their stage names", async () => {
    expect(await client.listReleasePipelines()).toEqual([
      {
        id: "pipe-1",
        name: "Product",
        slugId: "product",
        type: "scheduled",
        stages: ["Planned", "Released"],
        url: "https://linear.app/example/pipeline/product/releases",
      },
    ]);
  });
});

describe("write-team guard", () => {
  let erg: LinearClient;

  beforeEach(() => {
    erg = makeClient(["XX"]);
  });

  it("refuses to create an issue in another team", async () => {
    await expect(erg.saveIssue({ team: "APP", title: "x" })).rejects.toThrow(
      "Claude writes only to team XX; the new item belongs to APP. Reads are unrestricted.",
    );
    expect(stub.matching("issueCreate")).toEqual([]);
  });

  it("refuses to update, comment, cancel, hand off or archive another team's issue", async () => {
    await expect(erg.saveIssue({ id: "APP-17", title: "x" })).rejects.toThrow("issue APP-17 belongs to APP");
    await expect(erg.addComment("APP-17", "x")).rejects.toThrow("belongs to APP");
    await expect(erg.cancelIssue("APP-17", "x")).rejects.toThrow("belongs to APP");
    await expect(erg.handoff("APP-17", "x")).rejects.toThrow("belongs to APP");
    await expect(erg.archiveIssue("APP-17")).rejects.toThrow("belongs to APP");
    const writes = stub.gql().filter((c) => c.query.trim().startsWith("mutation"));
    expect(writes).toEqual([]);
  });

  it("refuses to link another team's issue into a release before writing anything", async () => {
    await expect(erg.saveRelease({ pipeline: "Product", version: "1.0.0", issues: ["APP-17"] })).rejects.toThrow(
      "belongs to APP",
    );
    expect(stub.gql().filter((c) => c.query.trim().startsWith("mutation"))).toEqual([]);
  });

  it("guards projects, their milestones and their documents by the project's teams", async () => {
    await expect(erg.archiveProject("Product")).rejects.toThrow("belongs to APP");
    await expect(erg.saveMilestone({ project: "Product", name: "v1" })).rejects.toThrow("belongs to APP");
    await expect(erg.saveDocument({ title: "d", project: "Product" })).rejects.toThrow("belongs to APP");
    await expect(erg.saveProject({ name: "p", setTeams: ["APP"] })).rejects.toThrow("belongs to APP");
    await erg.saveProject({ id: "Sandbox", summary: "ok" });
    expect(stub.matching("projectUpdate").length).toBe(1);
  });

  it("allows a cross-team project when one of its teams is writable", async () => {
    await erg.saveProject({ name: "shared", setTeams: ["APP", "XX"] });
    expect(stub.matching("projectCreate").length).toBe(1);
  });

  it("refuses a team label of another team but allows a workspace-wide one", async () => {
    await expect(erg.saveIssueLabel({ name: "x", team: "APP" })).rejects.toThrow("belongs to APP");
    await expect(erg.saveIssueLabel({ id: "bug", color: "#000000" })).rejects.toThrow("label 'bug' belongs to APP");
    await erg.saveIssueLabel({ name: "theme" });
    expect(stub.lastInput()).toEqual({ name: "theme" });
  });

  it("writes the peer team only from the peer identity", async () => {
    const peer = makeClient(["PEER"], "Peer");
    await peer.addComment("PEER-5", "hi");
    expect(stub.lastInput()).toEqual({ issueId: "issue-uuid-arc5", body: "hi" });
    await expect(makeClient(["ERG"]).addComment("PEER-5", "hi")).rejects.toThrow(
      "Claude writes only to team ERG; issue PEER-5 belongs to PEER.",
    );
  });

  it("leaves reads unrestricted", async () => {
    expect((await erg.getIssue("APP-17")).id).toBe("APP-17");
    expect((await erg.listComments("APP-17")).length).toBe(2);
  });
});

describe("whoami", () => {
  it("names the identity, its write teams, the app and the rate limit", async () => {
    const out = await client.whoami();
    expect(out.identity).toBe("Claude");
    expect(out.writeTeams).toEqual(["APP", "XX"]);
    expect(out.writes_as).toBe("Claude <claude@oauthapp.linear.app>");
    expect(out.application.name).toBe("Claude");
    expect(out.organization.urlKey).toBe("owner");
    expect(out.teams_visible).toBe(3);
    expect(out.token.scope).toEqual(["read", "write", "app:assignable", "app:mentionable"]);
    expect(out.rateLimit["x-ratelimit-requests-remaining"]).toBe("4999");
  });
});
