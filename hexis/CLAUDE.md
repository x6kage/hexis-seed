# Instructions for Claude

## Who I am
- (Installer: fill in who you are and any governance base or workspace convention the sessions should follow.)

## Language
- Owner preference (default; change it to yours): reply in Japanese. Keep technical terms, identifiers, commands, and quoted source text in their original language.
- Replies to me are written in the polite register, consistently, whatever register I write in, and a reply never
  ends in an offhand "which one?" / "shall I go ahead?". Rules and records are
  English and never spell out Japanese wording, not even romanised; they describe my instructions, never my manner.
- The reader decides the language. What only sessions and agents read is English: memory files (MEMORY.md index lines, OWNER.md, PROGRESS.md, STATE.md), `knowledge/`, `process/`, `decisions/`, `inbox/`, agent and skill definitions, inter-agent artifacts, commit messages, and working records under `outputs/` (analyses, experiment logs, data). Why: Japanese costs about one token per character where English costs far less for the same content, and an English restatement with identifiers kept verbatim leaves less room for a second reading. What I read is in my reply language: replies, the desktop app's next-step box (wrap_up recap, ask and button labels), `docs/`, the docs-hub documents, Linear titles and comments, and any report, inventory or comparison written for me to read or sort - wherever it is stored. `hooks/md-check.py` refuses Japanese prose in the English places.

## Models
- Main session: **Fable 5.2** (`claude-fable-5-2`, 1M, effort max; `model` in settings.json), with **Opus 5.5** (`claude-opus-5-5`) as the agent tier for judgement work. Under a Fable main the Fable audit is the main's own final pass (rules/agents.md "Audit"). Subagent tiers: **Opus 5.5**, **Sonnet 5.5** (`claude-sonnet-5-5`), **Haiku 5.5** (`claude-haiku-5-5`). The `fable` / `opus` / `sonnet` / `haiku` aliases are pinned to these IDs in settings.json (`env.ANTHROPIC_DEFAULT_*_MODEL`); never route a subagent to an older generation (Opus 4.x, Sonnet 4.x). Fable 5.1 and Opus 5 (`claude-opus-5`) are not used anywhere - they survive only as pricing rows so that older transcripts still cost out correctly.
- Refusal fallback: on - `switchModelsOnFlag` is not set in settings.json, so a safeguard-flagged turn is answered by the server-chosen Opus 4.8 instead of pausing the session: going on with Opus 4.8 beats a stop, because the safeguards flag work that is not cyber under the AUP too often. The session then stays on Opus 4.8 until the model is picked again. Subagent routing stays on the pinned IDs above in either case.

## Layout of ~/.claude
- `rules/` one topic per file; every `rules/*.md` is loaded automatically by the harness, so it needs no `@` import line. `CLAUDE.md` imports the knowledge and process indexes below; `knowledge/machine.md`, when present, is read when needed (the tool-shell pitfalls are the skill `hexis-shell`, pushed on the first heredoc or multi-line command). `knowledge/` cross-project facts (index imported below). `process/` step-by-step procedures. `decisions/` dated records of why. `docs/` documents I read. `agents/` model-pinned subagents. `hooks/` scripts wired in settings.json. `workflows/` saved workflow scripts. `skills/` Claude Code user skills. `evals/` test prompts for rules and skills. `outputs/` working records that belong to no repo. `inbox/` findings not yet applicable, each with an expiry.
- `projects/<dir>/memory/` is per-project and invisible from other directories, so anything cross-project goes to `knowledge/`. Read `knowledge/` before deriving a machine or environment fact from scratch, and add to it (plus INDEX.md) when you verify a new one.
- Records - `projects/<dir>/memory/PROGRESS.md` (Now / Open / Next, rewritten), `inbox/` with an expiry, STATE.md frozen where PROGRESS exists, decisions and lessons applied to `knowledge/`, `decisions/` or the rules - arrive with the session-start injection and the skill `hexis-records` (pushed on the first record write); full text in `skills/hexis-records/reference.md`.
- A UserPromptSubmit hook (`hooks/cost-meter.py`, calculator in `scripts/session-cost.py`) prices this session from its own transcript on every prompt and injects one line - total, main vs agents, last turn, context, average per request: quote that average in every cost line instead of guessing. It never asks for a handoff: auto-compaction is accepted, while a handoff chops the work and the rebuild repeats it; the main context is kept small by sending reading and bulk work to workflows and agents.
- This tree is its own git repo: commit here on your own after changing rules, knowledge, agents, or hooks (the one exception to the commit rule in rules/code.md). No attribution lines.

@knowledge/INDEX.md
@process/INDEX.md
