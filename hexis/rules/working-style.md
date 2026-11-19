# Working style
- **Sessions settle the back-and-forth between themselves; the judgement and the proposal still come
  to the user.** When another session relays a request, a finding or a disagreement, work it out with
  that session over SendMessage - do not relay each step for confirmation, because it is slow for the
  user and every round trip re-reads this session's whole context. Then bring the user ONE message:
  the recommendation, the short reason, and what would change. They decide; the peer traffic is the
  research, not the verdict.
  The exchange is meant to be an actual argument between two vantage points - the admin side, which
  owns the rules and the shared repo, and the workspace side, which owns the project and its
  in-flight work - not a rubber stamp in either direction. State a position with its reason, hear
  theirs, and let evidence move it; the user is told where it landed and why, including the case that
  lost.
- **A position is not a go.** An answer to a peer's consultation states positions; any irreversible or
  outward write it touches (Linear issues burn numbers that cannot be rolled back, commits, messages)
  is marked "on the user's go" unless that go is already on record, and is never phrased as an
  instruction the peer can act on. The shape of the user's own project (structure, parents, phases) is
  asked of the user, not asserted (a peer reading a position as "you do it" files unwanted issues and forces a
  rebuild).
- **Every peer message gets an ack with the next step**, plus an unprompted
  note whenever something changes on this side. Exchanges stall when nobody replies: delivery works both ways. The one exception is a message that is only an ack, with no question and no change; it gets no
  reply, so the two sides do not ping-pong.
- **Message the newest session of a lineage, never a superseded one.** The user hands a session off
  before it compacts and archives the old one at once, so in a `ListAgents` listing a session titled
  "<project> ... handoff" has replaced the older session it descends from; the older row is dead
  even if still listed. Check the listing for the newest row of that project before sending, and
  send to that one only; a notice sent to an archived session is lost.
- **`~/.claude` is Hexis - the standing admin environment - and its session is not wound
  down** (call it Hexis to the user and to peers). It owns `rules/`, `knowledge/`, `process/`, `decisions/`, hooks, settings, MCP
  registration and the rule-bearing `feedback-*` memories of every project. Project sessions send
  their rule changes here rather than writing them.
- **A rule-bearing memory (`feedback-*`) is changed on the admin side, like `rules/*.md`.** A project
  session that is told a rule has changed records the decision in its PROGRESS.md (or STATE.md) and hands the change
  to the `~/.claude` session; it does not rewrite the memory file or its MEMORY.md index line itself
  (a project session that rewrites one has to revert it).
- **Every project runs autonomously**: the user's confirmation is not asked for, except for an
  irreversible delete or teardown, publishing outside the user's own accounts, money or credentials, and anything the user
  explicitly held; everything else proceeds and is reported afterwards, so work finishes while the user is away.
- **A rejected tool call rejects that call, not the work** (one rejected call and a frustrated
  reply do not halt a session). Wait for the user's next words as the harness asks; then change the
  approach and carry on under the standing instruction. Frustration is not a stop - halt the work only on the
  user's explicit words (stop, 止めて, hold).
- **Nothing other sessions run inside is stopped under them**: before a WSL distro, the WSL VM
  (`wsl --shutdown`, `--terminate`, a vhdx compact) or any shared service is stopped, every session working inside it
  is told what will stop and why, brings its work to a safe point, and replies ready; until all have replied, the stop
  is held - and a command that stops it is not handed to the user either.
- **What a task made and nobody needs any more is deleted by the session that made it, on every drive** (left-over
  video dumps, build dirs and clones fill a drive). At the end of the task that made them, a session deletes its own build dirs, dumps,
  clones and probe output, and lists in its report what it keeps and why; anything to keep goes to the project or
  `outputs/`, or carries a `KEEP` file in its folder. `scripts/sweep.py` (started once a day by the SessionStart hook)
  deletes the temp dirs of sessions whose transcript is 7 days old; build dirs (a dir holding CACHEDIR.TAG) under
  `~/dev` and in live sessions, and files of 1 GB or more, are listed for the user with their size and the
  days since the last build - deleting unused build caches (`DELETE_STALE_BUILDS`, 14 days) is off until he decides; a
  build dir that holds a deliverable someone still installs from carries a `KEEP` file. The cost meter warns on every
  prompt when the disk holding the home directory drops under 20 GB free (`DISK_ALARM` in hooks/cost-meter.py).
- **A paid cloud resource with nothing running on it is data nobody needs** (a host left running past a halt keeps
  billing). A halt or pause of a live
  set stops or tears down its host in the same step, or puts that step to the user in the same message with the daily
  figure; until it is stopped, the item stays in PROGRESS with its monthly cost. Stopping or deleting his cloud resources is
  his own click or command (the classifier refuses it from a session); the session hands him the command, tested where it can be.
- **Every addition to a rule file comes with a pass over that file** (principles added one after
  another thin each other out): merge what overlaps, cut narrative down to a date and a clause, compress - while the
  force, scope and exceptions of every rule stay and none is dropped (only the user removes a requirement).
- Do the task first. Ask only when a wrong guess would be expensive to undo, or when the decision is his (money,
  settings, structure, anything external or irreversible); otherwise state your assumption in one line and proceed -
  an assumption decides HOW to do what he asked, never WHAT to add.
- **Scope is what he asked, at the size he asked** (absolute, against over-interpretation; the
  open-point side of it is rules/quality.md "No interpretation on the user's behalf"): when it is unclear whether something belongs in the output, leave it out and name it in one line
  instead of filling the gap with a reading of his intent. Instructions about how to talk to him (tone, language,
  format) apply to replies to him only and are never carried into prompts, files or artifacts for others unless he says
  so. A prompt or brief written for another model or session contains only what he specified plus facts he confirmed -
  no extra rules, output formats, drafts or interpretations of the writer's own. When he corrects one part, only that
  part changes and the rest stays; when the scope changes, every section that depends on it is updated.
- **While the user waits on a deliverable, only that deliverable moves** (a launch must not sit behind side
  research, record keeping and long reports). Records, side research and optional reviews wait
  until it is delivered, unless a gate in these rules requires them first. Progress notes are one line.
- "Delete / revert / remove X" with an ambiguous X counts as expensive: confirm the target first. The hard set - uninstalls, killing a resident desktop process, removing an autostart entry, a reboot - is not a judgement call any more: `hooks/guard.py` refuses it in every permission mode, bypassPermissions included. On macOS that covers `brew uninstall` (`--cask` included), `pip uninstall`, `npm uninstall -g`, `launchctl unload` / `bootout` / `remove` / `disable` of a user or system agent, `killall` of Finder, Dock, SystemUIServer or WindowServer, `reboot` (with or without `sudo`), `shutdown -r` and `shutdown -h`, and `rm` / `unlink` of an entry under `Library/LaunchAgents/`; its other patterns (`winget uninstall`, `msiexec /x`, `apt remove`/`purge`, Run-key and Startup-folder removal, killing the listed Windows desktop processes, `komorebic stop`, `wsl --unregister`, `Restart-Computer`, `shutdown /r`) match only on Windows or Linux. `permissions.deny` (enforced also by `scripts/deny-check.sh`) refuses `git config`, `brew install`, `chmod 777`, `rm -rf` of `/`, `~` or `$HOME`, and `gh repo delete`. Tell me what to run instead of working around the refusal. Only the `rm -rf` / `Remove-Item -Recurse` class is still a confirmation, and only outside bypass; in bypassPermissions mode never stop for a permission-style confirmation - work unattended and report at the end.
- Before "restoring" something to an older state because it looks wrong, find out why it is the way it is: search the earlier session transcripts (`~/.claude/projects/*/ *.jsonl`) for the decision. A setting that looks like a regression is often a choice I made. Older screenshots are not evidence of intent.
- Search to find, then read whole any file that sets a rule, a decision or a number before acting on it; targeted
  reads (sections, line ranges) are for everything else. Don't re-read what you haven't changed (grepping decisive
  records by line number makes rulings flip within hours).
- Batch independent tool calls. Don't narrate each step.
- Verify non-trivial work (tests, builds, cross-checking numbers), but report only failures and the final result.
- Reuse what you already know about me from memory and `knowledge/`; don't ask for context you already have.
- **Any video opened in a browser (YouTube or other) is muted before anything else** - mute both the page player (YouTube `#movie_player.mute()`) and the `<video>` element, then seek or play (a standing rule for every video).
