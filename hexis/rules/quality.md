# Quality gate and token discipline

Applies to every project.

## Evidence before code
- A bug report gets a **verdict**, not activity: reproduce or read the actual evidence (logs, state
  files, a diff of the artefact, the source data) before naming a cause. If the cause is not proven,
  say "unproven" and name the one cheap check that would settle it.
- A bug verdict needs the program's intended behaviour first: intended behaviour triaged as a bug is a wrong verdict.
  Read its own spec - docs, help pages, in-app help topics, dated design comments in the code, the
  issue tracker - and every finding cites the spec line it breaks and the matching issue, or says none exists.
  Behaviour the spec calls intended is not a bug; behaviour the spec leaves open goes to the user as a question. A
  review or triage brief names those sources.
- Never hand the user a workaround for an unproven cause. Being wrong twice on the same symptom is a
  process failure, not bad luck: the second time, stop and collect evidence exhaustively first.
- Cheap checks first, in this order: existing logs and state files, a read-only probe of the data,
  a targeted test, then code. Reading a 300-line file is cheaper than one wrong deploy.
- **The user's in-game check comes last, after the data is exhausted.** It costs the user far more
  than reading the exe, extracted tables, program-written saves and logs. Ask for one only when that
  data cannot settle the question, and say in the request what was searched and why it cannot.

## Verify before stating; two misses, then go outside
- Every factual claim carries its evidence (path:line or command output) or the word "unverified". "X does not
  exist / is unreadable / is offline" never follows a single local search.
- "This model or design has no part X" follows only from looking: every view of the reference art the project holds
  (front, back, side, close-ups) and the model rendered with each occluding part hidden. A search of asset or mesh
  names finds names, not parts: a part can lie on the back in the concept turnaround or under another mesh while a
  name search "proves" there is none, and an invented part replaces it.
- After two local searches miss, look outside before answering: the web and vendor docs, his backups, the other
  OS side (WSL distros via `\\wsl.localhost\...`, Windows via `/mnt/c`), and other tools' histories (Cursor).
- Money or a live system: one change at a time, measured against the base, kept only if it beats it, reverted if not.

- Where the project has extracted the reference's own data (game meshes, bones, VFX emitters and textures, tables),
  positions, shapes and colours come from that data and recordings only check it; eyeballing a frame is the fallback
  when the data was searched and holds nothing, and that search is listed. Projected bone heads and frame guesses
  are not the data.
  How a thing behaves (when a blade extends, what an effect does in each state) is read from the user's own
  recordings and clips first, the web second, and never inferred from one idle frame.

## Nothing is "unmodelled"
- Where the source data is available (extracted tables, motion values, exe), "contributes 0 / not
  evaluated / not modelled" is never a final answer. Build the row, or run the analysis that gets
  the number, and label the assumptions inside the data. A gap you cannot close gets the list of
  what you searched and what would settle it.

## Ported and referenced things keep their identity
- Anything ported from a reference (a trainer, a CE table, an upstream tool) keeps the reference's
  own name and grouping. Never invent a new name or category for it. The reference artefact is
  kept in the project (see the project's CLAUDE.md) and is the source of truth for names.

## Briefs and done (applies to every project)
- A brief states the user's goal, how the user will use the result, and the observed problem with its evidence. It
  never prescribes a mechanism, formula or guard the main session has not measured: the agent measures first,
  chooses, and says why (a guard prescribed by analogy to another endpoint can make an unrelated action demand that
  endpoint's token).
- Done means demonstrated on the running system the way the user uses it - the real service on its real port with
  real data: click it, screenshot it, read the live metric. Tests, typecheck, a build or an emulating proxy alone are
  not done; what could not be demonstrated is reported as not done.
- A web page is done only after it was looked at on phone widths (360, 375, 393, 430 px) in every interactive state
  (each tab, toggle, language, copied/hover state), not only at the design file's own widths (a pixel match with the
  design export at 390 and 1440 can still ship tabs that jump when a label changes on a phone). A design export
  (Claude Design or any generated prototype) is a vibe-coded sketch: take its look, copy and tokens, never its markup
  or CSS as the specification. Matching it is necessary, not sufficient.
- **A breakage fix never restyles** - it never turns natural-width buttons into full-width ones, a wrapping nav into
  a grid or a wrapping footer into a scroll line, and never shrinks the section padding.
  The design's look stays exactly as designed at every width. Where it breaks (a right group lands left after a
  wrap, a trailing mark drops to its own line, two things touch, something moves when a state changes), make the
  smallest change that removes that one defect and leaves everything else pixel-identical, then list each change.
  Any other visual change is a design decision: propose it, with a before/after, and do nothing until the user says
  yes ("No interpretation on the user's behalf" below). A brief to an agent names the allowed fixes as a closed list.
- The report carries the evidence (what was read, live numbers, request and response), not claims.
- Before writing that the user has no record or experience of something, read his own materials: his skill sheet
  (OWNER.md says where) is his record of real work and the material his designs were built from, and the records
  of any peer environment come next. Hexis records alone never establish "no record".
- Everything on the owner's own lists (his stack, his skills, what he entered into a design) is his and in use,
  including tools Claude agents do not use in his projects. A proposal on what to show on his pages judges only
  what the reader needs and how it presents (necessity, appeal, order, duplication); it never asks or audits whether
  he used something, and never cuts for a missing record.
- A scope the user named ("all", 全部, every algorithm) is covered literally. A brief or an analysis may rank and
  flag, never shrink the user's set; a narrower first pass is proposed to the user, not substituted, and a
  coverage inventory (every table, file or item, none left over) comes first.
- Every image or video the briefing session passes to the user it has opened itself and compared with the reference
  first; a worker's report is not the check.
- Before briefing work on an asset (a scene, an effect, an alert, an icon), run `python scripts/user-asks.py
  <keywords>` for its names and carry every remark of his on it that is not yet built, from every session and from
  before any compaction; the brief's own window of recent prompts misses older ones. A visual spec reaches the worker
  in his own words (original language) beside the restatement, so a paraphrase cannot merge or drop parts of it.
- **No interpretation on the user's behalf (explicitly forbidden by the user; the one rule for open points, briefs
  and stated bases; it holds on every model, against gap-filling and against misreadings).** A point is settled by
  his words or the reference he gave; a measurement settles
  only what the system dictates (a mechanism, a number the data fixes); a departure from his words or the reference
  is never a silent choice.
  (a) Where they do not settle a point, neither the worker nor the briefing session chooses: the point goes to him as
  a question in plain text with the options and a recommendation - what to do, why, what evidence would change it -
  and stays unbuilt until he answers, while everything that does not depend on it goes on (asking never halts the
  rest of the work, and never as a fixed-option AskUserQuestion list). Every open point in a document or
  analysis for him ends the same way; "the user decides" or "not decided here" alone is never written. An uncertain
  reading of the request itself is asked the same way (rules/output.md).
  (b) A brief carries only settled points as decided items - nothing he has not approved - and marks every open
  point "do not decide; return the options with a recommendation"; the worker leaves that part unbuilt. Every brief
  says this to the worker.
  (c) Every result shown to him states, per decision, what it rests on: the reference frame, his words, or a
  measurement, since he never sees the reasoning chain. A decision without a stated basis is not made.
- A question about intent ("do you mean to build it that way?") is answered, never acted on as a change request;
  the work stays as it is until he says to change it.
- "Make it correct" means one correct result, not a menu. When the right form follows from the reference data and
  the constraints the user has stated, produce that one result and show it; variants are for points his words leave
  genuinely open, and even then at most two.
  The exception is a continuous parameter he judges by eye (an angle, a roll, an amount): that is swept in 3-5 steps
  across its usable range on ONE comparison sheet with the numbers, never a single extreme or only the two ends. He
  picks from the sheet.
- A brief carries what the user asked for and nothing he only thought aloud about. An aside ("maybe just don't show it",
  "or think about the game area") is not relayed as a task, an option to propose or a question to put to him.
- **Agents never decide on their own, and what they did is put to the user before anything moves** - a report that
  says an agent removed something on its own reasoning is not a go for the main session to move on. An implementer,
  worker, analyst or workflow agent leaves every point its brief does not
  give it unbuilt and lists it with options and a recommendation (agents/*.md carry this). When an agent's or an
  audit's result shows an own decision anyway - a removal, rename, replaced or dropped behaviour or setting, a default
  it chose - the main session puts each to him as a question in plain text (what changed, which of his words or brief
  it departs from, keep or revert, a recommendation) and does not build on it or relay it as done until he answers;
  everything else goes on; never a question list. Enforced by
  `hooks/restate-gate.py`: Jev reads every agent result once per turn and, at or above 0.5, stops the turn's first
  state-changing call once with that instruction; the resend passes.
- Only the user removes a requirement. A brief - the launch, a follow-up message, a started session - never lets
  the worker drop, skip or make optional something the user asked for ("if it does not read, drop it and say why"):
  it states the item as required, and a worker that cannot meet it stops and reports with the evidence, so the user
  decides. Enforced by the `loosened` arm of `hooks/brief-check.py` on Agent, Workflow, start_session and SendMessage.
- A brief on an asset COPIES the settled facts of that asset's knowledge paragraph (knowledge/<topic>.md) into its settled
  items, verbatim, before the task is written, and a task that contradicts one of them is not sent. Citing the file is
  not reading it.
  A provisional go (とりあえず, 一旦: ship now with what is accepted) PAUSES the open items; it never closes them. The
  brief, the hand-over and the record say "paused, continues after X", never "closed" or "no more rounds".
- Every round of a deliverable is kept as its own version; nothing is replaced in place. Each round writes new
  files named by round and variant (`<name>-r<N>[-<variant>]`), the code it came from is snapshotted beside them,
  and the file a live system uses (an OBS source, a Twitch upload) changes only when the user picks a version. In a
  folder without version control an overwrite destroys the only copy, and rebuilding it is paid again.
- Expensive multiplications of a look (every size, every scene, long loops) wait until the user has approved that look
  at one size, and until every open complaint about it is closed; before such a batch, list the open complaints on
  the asset.
- Nothing is opened on the user's live desktop (a window, an app, a browser, a test overlay) until it has been proven
  hidden or headless - it renders what it should and its close path works - and the user has said go for that run.
  The session that opens it closes it when its check ends and confirms no process of it is left; a test never leaves
  a window or process behind.
- **No synthetic input on the user's desktop, ever**: no session, agent or script calls
  `mouse_event`, `SendInput`, `SetCursorPos`, `keybd_event` or `SetForegroundWindow` on his desktop for any check. A
  check that needs a hand (drag, resize, click) is his to do or is reported as not demonstrated; a brief never asks
  a worker to "prove the window still drags" without saying that. And an input or desktop problem is never reported
  as fixed from process lists or key-state reads: it is fixed when he says so, or when a timed live sample shows
  normal input; until then the report says what was found and what still interferes.
- **An app modelled on a reference is run on his desktop only after the reference's control is understood**:
  how the reference creates, shows, hides, focuses and positions its windows, and what it does and never
  does with input, hotkeys and the game, read from its code and measured, and written to knowledge/ before the first
  run. The run then reproduces only what the reference does; a go from him is necessary, never sufficient.

## Every deploy is gated
- **Passing tests are never a stamp of quality**: no session presents a green test run, type check or build as
  showing that code quality holds or that there are no bugs - not in a reply, a report, a commit message or a brief.
  A test result is reported as what it is, what ran and what passed; whether the code is sound is the verdict of the
  gate below, never of the suite.
- **The QA gate is mandatory, with no exception** (for all of Hexis): code is audited whoever wrote
  it - an agent or the main session itself, inline fixes included - before it is presented as done, committed or
  pushed, and the `qa-gate` checklist (agents/qa-gate.md) is run on the diff by a model other than its author before
  every deploy or install, not only on a component he has complained about; its verdict is reported verbatim.
  Which agent under which main: rules/agents.md "Audit". A gate that could not run (refused, out of quota) leaves the
  work reported as not gated, never waved through. Open with him: whether the full checklist also runs at every
  "done", commit and push, and the hook that enforces it.
- Full test suite green, the version bumped once per shipped set, the notes/version history
  updated, and the verified facts written to memory **before** telling the user it is done.
- A number that moves a pinned test is re-measured and the pin explained in the test, never
  loosened to pass.
- When the user says a shipped thing is broken, the default assumption is that it is broken;
  re-verify the whole component (runtime pieces first: loader, injected DLL, live edits, item
  store) rather than defending it.

## Token discipline
- Do not fan out subagents for sequential work or for work that needs the same files re-read.
- When a subagent tier is rate-limited, drop one tier or do it yourself - never re-launch on the
  dead tier, and never let a subagent spawn a child on it.
- Read the parts of files that are needed (targeted greps and line ranges); never re-read what has
  not changed.

## A correction changes the thing it corrects
- A correction from the user is answered in the same turn by changing what it corrects: the rule,
  knowledge, process, test, hook or code whose behaviour was wrong. Writing down that a correction
  happened is not the fix - piling lessons into feedback memories and STATE lines is itself a
  structural defect: they are reloaded every session, never consolidate and
  thin each other out.
- What cannot be applied in that turn goes into `inbox/` as one short file with its date and an
  expiry. The inbox is consolidated into `knowledge/` (or dropped) and emptied; it never grows.
- No new feedback memory is written per correction.

## Continue from the handoff; never re-derive it
- When a summary, an earlier session or an earlier model has already pointed at a specific file,
  table or row, **start there**. A handoff is evidence, not a rumour. Re-running the broad audit to
  "confirm the premise" before continuing is the waste; if the handoff is wrong, that shows up in
  one targeted check, not in a fresh investigation.
- **Never ask the user to switch off a feature they just got working** in order to A/B it. And if a
  component's behaviour has already flipped completely between two observations (e.g. a probe-mode
  build vs a fully working build) while the symptom stayed identical, that component is *already*
  excluded by the evidence in hand - say so, do not request a test.
- On a vendor update, the **first** thing to read is the CONTENT of whatever actually changed: the
  row-level diff of the one changed table, the bytes of the moved function. "Only one table changed"
  is a pointer to it, never a reason to dismiss it. Inventorying everything that did *not* change
  proves nothing about the symptom.
- A symptom that starts exactly at an update is explained by what that update changed. Compare the
  changed vendor artefact with how this project's own generated artefacts express the same thing:
  a representation the vendor itself no longer uses is the defect, and it is fixed by adopting the
  vendor's current form, not by inventing a new one.
- Do not narrate elimination. The user wants the cause and the fix; a list of what is clean is only
  worth sending when it is the answer.

## "Turn the mods off" does not test a live memory edit
A tool that modifies a running program usually has **two** independent channels: files it deploys
(mods, tables, assets) and patches it writes into process memory (caves, byte patches, hooks). An
A/B that disables one says nothing about the other.

- When a symptom survives "I turned everything off", establish **what that actually turned off**
  before drawing any conclusion from it. Read the live/patch state file, not just the mod list.
- A cave that sits on a shared code path must prove the record it is about to write is the kind it
  expects. A "safety clamp" on a lookup result is not a guard - it converts a failed lookup into a
  confident write. Range-check and bail out instead.
- One-shot / diagnostic patches must not survive the session they were enabled in, and the drop has
  to run on a fresh tool start too, not only when a restart is detected.

## A save (or any state file) is judged by its invariants, not by its rows
- Before saying a state file is fine, compare it side by side with one the program itself wrote:
  every counter against the maximum it is supposed to track, every count against the instances it
  is supposed to count, every list length. Row-level validity says nothing about this.
- When the user names an action of OUR tool as the suspect, audit what that action writes and
  what it forgets to write before auditing anything else.
- Report which invariants were compared. "The rows are valid" is not "the file is fine".
