# Model pricing (verified 2026-09-20, platform.claude.com/docs/en/about-claude/pricing)

USD per million tokens. Cache read = hits and refreshes; cache write = 5-minute / 1-hour.

| Model | input | cache write 5m / 1h | cache read | output |
|---|---|---|---|---|
| Claude Fable 5.2 (`claude-fable-5-2`, verified 2026-11-10) | $8 | $10 / $16 | $0.20 | $40 |
| Claude Fable 5.1 (`claude-fable-5-1`) | $10 | $12.50 / $20 | $0.25 | $50 |
| Claude Opus 5.5 (`claude-opus-5-5`) | $4 | $5 / $8 | $0.20 | $20 |
| Claude Opus 5 (`claude-opus-5`) | $5 | $6.25 / $10 | $0.50 | $25 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`, released 2026-09-28, verified 2026-09-29) | $2 | $2.50 / $4 | $0.20 | $10 |
| Claude Sonnet 5 (`claude-sonnet-5`) | $2 | $2.50 / $4 | $0.20 | $10 |
| Claude Haiku 5.5 (`claude-haiku-5-5`, prompt up to 100k, verified 2026-10-16) | $0.10 | $0.125 / $0.20 | $0.01 | $0.50 |
| Claude Haiku 5.5 (`haiku-5-5>100k`: prompt over 100k, verified 2026-10-16) | $0.50 | $0.625 / $1 | $0.05 | $2.50 |
| Claude Haiku 4.5 (`claude-haiku-4-5-20251001`, legacy since 2026-10-16) | $1 | $1.25 / $2 | $0.10 | $5 |

Batch API = half of input and output. Claude 4.7+ tokenizer produces ~30 % more tokens for the same
text than Sonnet 4.6 and earlier. Fast mode (Opus 5 / 4.8) = $10 / $50, Opus 5.5 = $8 / $40. Opus 5.5 row verified 2026-09-23: list $4 / $20 and cache read $0.20 from the bundled claude-api skill (cached 2026-06-24), the 1h cache write $8.00/M measured from one `claude -p` call (65,636 cache-creation tokens + 132 output = $0.527736), the 5m write $5 inferred from the standard 1.25x multiplier. Opus 5 row kept so older transcripts still price correctly - `scripts/session-cost.py` matches `opus-5-5` before `opus`.

Haiku 5.5 rows verified 2026-10-16 (https://platform.claude.com/docs/en/about-claude/pricing): Haiku 5.5 is priced by prompt length per request, and the pricing page states that a request's prompt length counts all of its input tokens, including cache reads and cache writes, and that each request is priced on its own, so a request over the 100k threshold pays the higher prices even when part of its prompt is a cache hit. Batch: $0.05 / $0.25 up to 100k, $0.25 / $1.25 over. `scripts/session-cost.py` books each Haiku 5.5 request whose input + cache read + cache write exceeds 100,000 under `haiku-5-5>100k` and the rest under `haiku-5-5`. A Haiku 5.5 agent launched from Claude Code on this desktop is over 100k from its first request (probe 2026-10-16: one `claude -p` call read 166,827 and wrote 25,508 cache tokens), so budget it at the over-100k row - still half of Haiku 4.5 on every term. Haiku 4.5 row kept so older transcripts still price correctly.

Fable 5.2 row verified 2026-11-10 (https://platform.claude.com/docs/en/about-claude/pricing): batch $4 / $20, fast mode $16 / $80, 1M context. Against Opus 5.5 the cache re-read rate is the same ($0.20/M) while input, cache writes and output are twice Opus 5.5's; against Fable 5.1 every term is 0.8x. The `fable` alias resolves to Fable 5.2 unless `ANTHROPIC_DEFAULT_FABLE_MODEL` is set, and the page says Fable 5.2 requires Claude Code v2.1.321 or later (https://code.claude.com/docs/en/model-config, read 2026-11-10). The 50 % Fable share holds on Ultra and for every Fable model (https://support.claude.com/en/articles/15424964, read 2026-11-10: up to 50 % of the weekly limits on Fable at no extra cost, drawn from the same pool and faster than other models; at the cap, usage credits or another model). Fable 5.2 launch offer (https://support.claude.com/en/articles/17506494): Max and Ultra get one to three Fable limit resets by subscription length from 2026-11-09; a reset gives back the usage spent on Fable models and refills the 5-hour window, is used by hand before it expires and cannot be undone. Fast mode (https://code.claude.com/docs/en/fast-mode and https://platform.claude.com/docs/en/build-with-claude/fast-mode, read 2026-11-10): the same model at up to 2.5x output tokens per second with no change to intelligence or capabilities - a speed setting independent of effort, so fast with `max` thinks as `max`, not below `high`. Fable 5.2 fast is $16 / $80 and Opus 5.5 fast $8 / $40 (twice the standard input / output). On Pro, Max and Ultra it is paid from usage credits only, outside the subscription limits, and draws from them even while the plan has allowance left; with usage credits off `/fast` reports that it requires them. The docs name Claude Code v2.1.321 for fast mode on Fable 5.2. Turning it on therefore means spending purchased credits (rules/agents.md Credits mode). Prompt caching multipliers apply on top of the fast prices (Fable 5.2 fast: cache read $0.40/M, 1h cache write $32/M), and requests at different speeds do not share cached prefixes, so toggling fast mode in a running session re-caches the whole context cold (about $15 at 460k on Fable 5.2 fast).

## How to estimate a run (rule: state this in dollars BEFORE launching anything)

    cost = requests x average context x cache-read rate
         + new tokens x cache-write rate
         + output x output rate

**Requests, not work, is the driver.** Every tool call is one API request and every request re-reads
the whole context, so a tool-using agent makes 50-120 requests and pays its context that many times.
A subagent or a workflow `agent()` starts with a **fresh, small context** - that, not its per-token
price, is the main reason to delegate: the same work done in a session that is already 300k deep
costs multiples of the same work done in a 30k one.

- `scripts/session-cost.py <transcript.jsonl> [--subagents]` prints the real number from the
  session's own transcript; `hooks/cost-meter.py` injects it on every prompt. Estimate from the
  live `avg $ per request` figure it reports, never from a guess.
- The usage page (Settings > Usage) is the truth; quote it after the run.

## Measured (session A, 2026-09-20, `scripts/session-cost.py --subagents`)

| model | requests | input | cache write 5m | cache write 1h | cache read | output | USD |
|---|---|---|---|---|---|---|---|
| fable | 74 | 1,146 | 644,308 | 85,747 | 16,889,358 | 119,916 | 20.00 |
| opus | 259 | 518 | 1,335,042 | 0 | 41,268,741 | 214,609 | 34.35 |
| sonnet | 5 | 10 | 122,589 | 0 | 278,424 | 10,929 | 0.47 |
| | 338 | | | | | | **54.82** |

338 API requests, 58.4M cache-read tokens: 95.8 % of the tokens but **45.4 % of the dollars** ($24.91: fable 16.9M x $0.25 + opus 41.3M x $0.50); cache writes $18.42 (33.6 %), output $11.47 (20.9 %). The token share is not the dollar share. The
same run counted one-record-per-content-block (`--per-record`, 638 records) comes to $114.59 - that
is the transcript writing one response as several records, not a second bill; see `hooks.md`.

Three consequences:

- **Close long sessions early.** Cost per turn grows with the context, so the last turns of a 700k
  session cost ~20x the first ones. The cost meter asks for a `handoff` at $30 or 300k of context.
- **Batch independent tool calls.** Five calls in one message is one request re-reading the context
  once; five messages is five.
- **Delegate for the fresh context, then pick the tier.** An Opus agent at 30k average context over
  60 requests is ~$1; the same 60 tool calls in a 300k Fable session are ~$5 in cache reads alone.

## When a Fable main session is cheaper than an Opus one

Fable reads context at half Opus's rate ($0.25 vs $0.50/M) but writes cache at twice it ($12.50 vs
$6.25/M) and outputs at twice it ($50 vs $25/M). Per request, with context `C`, `n` new tokens and
`o` output tokens, Fable wins when

    C > 25n + 100o

Measured per-request shapes: the Fable turns of session A ran n = 9.9k, o = 1.6k -> crossover
~410k against an actual 228k context; its Opus turns n = 5.2k, o = 0.8k -> ~210k against 159k. Exclude the session's FIRST
write from n, whichever bucket it lands in: it is the one-off session-start write and amortising it
over every request pushes the crossover ~30k too high. Do not exclude "the 1h bucket" - which TTL a
session writes into is a property of the client, not of the request. Session A (CLI) wrote
1h once and 5m thereafter; session B (desktop, 2026-09-21) wrote **every** request into the
1h bucket and never touched 5m, so a rule keyed on the bucket silently reads n = 0 there.

The same thing per token, which is the useful way to think about it: a token read into cache once is
written once and then re-read on every later request. Over `k` later requests it costs $12.50 + $0.25k
on Fable against $6.25 + $0.50k on Opus, so **anything you read and keep working over for more than
~25 further requests is cheaper on Fable**. That is exactly the shape of an audit - load the diff and
the files once, then reason over them for dozens of tool calls - and it is the opposite of the shape
of a thinking-heavy turn, where Fable's $50/M output is a straight 2x penalty (one output token costs
what 100 re-reads of a context token cost). Fable audits at medium effort over material already in
context; it is the wrong model for max-effort derivation from a small context.

### Delegation is won or lost on redundant reads, not on the tier

Measured on one implementation session (2026-09-21): agents $37 over ~330 requests = $0.112 per
request, against $0.150-0.165 for a Fable main session at 190-250k. Per request the agents were
cheaper - but that is not the comparison. An agent starts fresh and re-reads what the main session
already holds, so it needs MORE requests for the same work. Fable alone is cheaper whenever it
finishes in under $44 / $0.165 = ~267 requests against the agents' 330: **delegation loses as soon
as re-discovery costs more than ~20 % extra requests.** With a long brief that hands over direction
instead of facts, a 157-tool-use implementer clears that easily, which is what the session observed.

So the deciding number is how many of an agent's tool calls re-fetch something the caller already
had. Paste the facts a scout found into the brief, keep one agent near 60 tool calls, and never
launch one that must rebuild context the main session is sitting on. An agent whose own context
passes the crossover (~208k) has additionally lost the fresh-context advantage that was the reason
to delegate; the perf implementer reached 187k.

Do not settle this kind of question by multiplying the two per-request rates by the same request
count - that silently assumes the main session would have needed the agent's re-reads too.

### Switching model mid-session almost never pays for itself

The crossover above is a marginal test: it says which model is cheaper *per request from here*. It
ignores the switch itself. A model switch starts on a cold cache - cache entries are keyed to the
model - so the whole context is written once more at the NEW model's write rate. Going to Fable that
is $12.50/M, against a saving of at most $0.25/M per later request, so the payback is

    payback (requests) = C x 12.50 / (C x 0.25 - 6.25n - 50o/2)

whose floor as `C` grows is **50 requests**, and which at realistic shapes is 150+ (300k, n = 5k,
o = 0.8k -> 158) or never inside a 1M window. The conclusion is not "Fable is bad": it is that
**the model is chosen when a session starts, while the cache is cold anyway**, not switched into
later. Going the other way (a shallow Fable session to Opus) does pay - ~24 requests at 100k - because
Opus's write rate is half.

If a session is to be switched anyway, switch it before it loads the material it is about to work
over, not after: the one-off is proportional to the context at the moment of the switch.

Assumption behind all of this: a switch invalidates the prompt cache. Verify it from the transcript
after any switch - the first request on the new model should show `cache_creation` of roughly the
whole context and `cache_read` near zero.

`hooks/cost-meter.py` computes the crossover every turn from the session's own measured n and o (not
from the figures above) and, once the running family has 20 requests and is off the crossover by more
than 25 %, adds one line naming the cheaper main model and the `/model` command to switch to it.

The handoff line takes precedence, but its thresholds are deliberately loose - $50 and 500k, raised
from $30 / 300k on 2026-09-20 - because chopping a session mid-audit throws away context that is
still being used and the new session pays to rebuild it. Hand off when the context is mostly spent
material you will not read again, not at a fixed size.

## Cold re-caches are the bill on a large context (measured 2026-09-21, session B)

A big context is cheap while its cache is warm (Fable reads 190k for $0.05 per request). It is expensive
every time it is written cold, and that happens in exactly three cases: session start, an idle gap past
the cache TTL (1h in the desktop app), and a model switch - measured: 28 s after `/model opus` the first
Opus request wrote 110,650 tokens with cache_read 0 ($1.11), and the switch back wrote 155,007 ($3.10).
Two 70-minute idle gaps re-wrote 115,457 ($2.31) and 142,395 ($1.42). By category the main transcript
at $18.84 was: cold re-caches 51 %, incremental writes 22 %, output 14 %, context reads 12 %.
So the lever on a 1M session is not its size but its cold starts: no idle gaps over an hour, no model
switches, and a handoff only at the compact window.
The meter counts them (`Cold re-caches: N = $X`, COLD_MIN 20k with cache_read 0).

## JP vs EN token ratio (measured 2026-09-21, `claude -p` on Haiku 4.5)

Five paired samples, same content in both languages (identifiers, paths, commands and code left
untouched). `usage.input_tokens` is **not** usable for this: anything past a few tokens is cached, so
a long user prompt lands in `cache_creation_input_tokens` and `input_tokens` stays at 10. The
measurement is `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` minus the same
total for the tail-only baseline prompt (37,518 here). That constant portion jitters by ~390 tokens
run to run, so each cell is the **median of 3** runs; single runs are unreliable.

| sample | kind | chars EN | chars JP | tokens EN | tokens JP | JP/EN | chars/tok EN | chars/tok JP |
|---|---|---|---|---|---|---|---|---|
| s01 | rules prose (`rules/agents.md`, 40 lines) | 5,017 | 3,010 | 1,327 | 2,218 | 1.67 | 3.78 | 1.36 |
| s02 | memory log lines (`STATE.md` x12) | 2,446 | 1,936 | 800 | 1,186 | 1.48 | 3.06 | 1.63 |
| s03 | casual user chat message | 752 | 341 | 178 | 282 | 1.58 | 4.22 | 1.21 |
| s04 | assistant reply + fenced code block | 1,180 | 590 | 289 | 437 | 1.51 | 4.08 | 1.35 |
| s05 | python hook, comments/docstrings only | 1,429 | 1,307 | 491 | 570 | 1.16 | 2.91 | 2.29 |

- **Overall 4,693 / 3,085 = 1.52x.** Prose only (s01-s04) **1.59x**; code with only the comments
  translated (s05) **1.16x**.
- Per character: EN prose ~3.6-4.2 chars/token, JP prose ~1.2-1.4 chars/token, so the same *number
  of characters* in JP costs ~2.5x. Japanese says the same thing in ~60 % of the characters, which
  is what brings the same-content ratio down to ~1.6x.
- s02 is the low prose case (1.48x) because timestamps, hashes and paths are identical in both.

### Cost implication

Same content, EN 2,000 chars = 2000/3.62 = **552 tokens**; JP = 552 x 1.589 = **877 tokens**.
Re-read (cache read) on 100 requests:

- Fable $0.25/M: EN 552 x 100 / 1e6 x 0.25 = **$0.0138**; JP 877 x 100 / 1e6 x 0.25 = **$0.0219**.
- Opus $0.50/M: EN **$0.0276**; JP **$0.0439**. One 5m cache write on top: Fable $12.50/M = $0.0069
  vs $0.0110; Opus $6.25/M = $0.0035 vs $0.0055.

Output, same content, EN 1,000 chars = 1000/4.08 = **245 tokens**; JP = 245 x 1.512 = **370 tokens**.
Fable output $50/M: EN **$0.0123** vs JP **$0.0185** per reply - ~$0.62 extra per 100 replies.

So the language choice is worth ~$0.01 per instruction file per 100 requests and ~$0.006 per reply:
negligible per item, ~1.5x on whatever share of the bill is Japanese text. This is why `~/.claude`
keeps `rules/`, `knowledge/`, `process/` and memory files in English (those are re-read every
request) while replies to the user are Japanese (output only, and the shorter of the two in
characters).

Reproduce: `PYTHONIOENCODING=utf-8 python jp_en_tokens.py --runs 3` in `~/.claude/evals/jp-en-tokens/`
(script + `sNN_{en,jp}.txt` samples there). Per measurement:

    "$CLAUDE_CODE_EXECPATH" -p --model claude-haiku-4-5-20251001 --output-format json \
        --setting-sources "" < prompt.txt

with `CLAUDE_CODE_CHILD_SESSION` unset and the prompt on stdin.

## Consumer plans (claude.com/pricing, read 2026-11-03)
- Free $0 (Sonnet/Haiku, no Claude Code); Pro $20/month ($17 annual: Opus, Claude Code, Projects, Research; Fable paid with usage credits); Max $100/month (5x Pro usage, Fable included up to half the weekly limit, $100/month API credits); Ultra $200/month, new (everything in Max, no 5-hour limit for verified accounts, 10x Pro weekly usage, Fable 50% of weekly limits, $200/month API credits). The page states nothing about transitions for existing subscribers and no longer lists a 20x tier.
