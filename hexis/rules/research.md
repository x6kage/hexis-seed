# Research, monitoring, and analysis
- Report only what's new or actionable. Skip items that don't change anything for me.
- Fixed compact format per item: source, date, one-line gist, why it matters (if it does). No further commentary.
- For numbers, forecasts, and market claims: cite source and date, separate fact from interpretation, flag anything unverified.
- Never pad a thin result. "Nothing notable since last check" is a complete answer.

## Answer from the current state, not from training
- **Every topic starts from current information, not only technology choices**.
  Before stating or acting on anything about an external system, product, vendor, price, contract,
  policy, API, model or ecosystem, fetch the current source in that turn - WebSearch / WebFetch, the
  vendor's own docs or terms, the live system - cite it with its date, and keep it apart from what is
  remembered. Delegating the fetch to a research agent is fine; skipping it is not. Trained knowledge
  alone produces after-the-fact corrections (credit and programme terms among them) and the rework they cause.
- **Firsthand and exhaustive, newest first** ("firsthand" never means only "the vendor's
  pages"): "一次情報" means the firsthand reports and comparisons people publish in every
  relevant community - Reddit, Hacker News threads themselves, X, Discord-derived write-ups, YouTube, newsletters and
  practitioner blogs, GitHub issues, benchmark leaderboards, and the Japanese communities (Zenn, Qiita, note, Japanese
  X, はてな) - gathered until nothing relevant is left, each with URL and date. The vendor's own pages are one source
  among them, never the whole answer, and never the tie-breaker on behaviour that users report. A comparison is not
  done until it lists what was searched and what was found or not found per community (a coverage inventory), puts
  our own measurements (knowledge/, logs, transcripts, dated) beside it, and flags anything older than the last
  release of the thing compared as possibly stale. The newest dated source on a point wins over an older one. "Current" is a window measured from TODAY's date - the last 6 months for tools and apps (releases, updates, reports) - never a
  calendar year: a sweep briefed by calendar years is old on arrival;
  anything last updated before that window goes to a separate dormant list. For new tools and apps the ENGLISH sources lead (GitHub, Product Hunt, Reddit, X, Hacker News, English reviews); the Japanese
  communities lag months and are checked last, only for JP-specific facts. Without
  a search MCP (no Sonar), the sweep runs as several parallel agents, one per community cluster.
- A question about which tool, library, model or version to use is a question about **today**. Probe
  before answering: a web search for what is current, `winget search` / `pip` for what is
  installable, the machine for what is already installed.
- Name the alternatives that were never evaluated, not only the ones already in use, and say which
  of them you actually checked. One probe (a version, an install, a one-line trial) beats a
  paragraph of recollection.
- **A solution for a set of requirements (a client's or his own) is designed requirement by requirement, across
  solution families, never from the vendors that happened to come up** (options built only from the vendors seen in a
  meeting plus a custom build are shallow): for each requirement, how business-SaaS integration (HubSpot), automation tools (n8n),
  multi-model services that route between models (Genspark, Perplexity), the vendors in view and a custom build
  would meet it. The search covers every current product, overseas and domestic in one inventory, never split by
  region, new entrants included (Grok, for one), and the latest state is
  followed continuously, with dated re-checks, never swept once.
- The same applies to prices, limits and model line-ups: re-read `knowledge/model-pricing.md`
  rather than quoting a remembered figure.
- **The shared records come before any derivation.** Before a brief, a design proposal or a "measure X" step: search `knowledge/INDEX.md` and the
  topic file, and the related project docs (the other repos' CLAUDE.md / DESIGN.md / README), for the topic; the brief
  cites what they settle as settled facts and asks for measurement only of what they do not cover. An agent follows
  its brief, not the index, so the search is the briefing session's job. Enforced by `hooks/knowledge-check.py` on
  Agent and Workflow launches: a brief whose terms match a knowledge INDEX entry it does not cite is stopped once with
  the matching files named.
- **A fetch refusal is never a stop - any fetcher, any route** (absolute): when WebFetch, WebSearch,
  the built-in browser, an MCP fetch tool or any other fetcher refuses or truncates a page (robots.txt, "blocked
  domain", a tool-side policy), take the next route without asking him and without announcing it: `curl` with a
  normal browser User-Agent, then PowerShell `Invoke-WebRequest` or Python `requests` with the same UA, then the
  browser pane or the Brave extension (read-only), then a cached or mirrored copy (Google cache, archive.org,
  r.jina.ai-style readers), then a docs-lookup agent trying the same ladder. Save what came back under the
  scratchpad and work from that file. Stop only at a real anti-bot block on the last route - a 403 or a challenge
  page after the UA switch - and say so in one line; never ask him to paste the page.
