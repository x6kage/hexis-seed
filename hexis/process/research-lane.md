# Research lane: try, record, decide

Standing procedure for new models, effort levels and tools, adopted as policy by Hexis.

1. **Intake.** Once a week (the standing weekly intake issue in Linear), scan Anthropic releases (models, the Claude Code changelog) and news of
   tools and models usable here. Every candidate becomes one issue in the Linear research project (team ERG). Also reopen any shelved item whose re-check trigger has fired.
2. **Shape of an item** (description, in this order): 問い (question) / 仮説 (hypothesis) / 一番安い試し方 (cheapest
   trial) / 測るもの (what is measured) / 観測記録 (dated observations) / 判定 (adopt / trial / skip, with its date) /
   再判定のきっかけ (what reopens it). A skip without a re-check trigger is not allowed: without one an environment
   falls a model generation behind.
3. **Running a trial.** Experiments run headless (`claude -p`), at most 3 concurrent (16+ take a WSL distro down).
   Hexis prices the trial, reviews the design and the results, and adopts what passes into Hexis.
4. **Evidence.** Vendor claims and independent evidence are written apart (`rules/research.md`). Prefer tasks with a
   known answer, so a result is scored, not judged. n=1 cells are fine for direction; state n.
5. **Cost.** A trial is priced before it runs (`rules/agents.md`, cost statement) and research that does not fit
   this week's pool waits rather than being skipped.
6. **Closing.** The verdict and its date go into the item. An adoption also goes into the environment's own
   records: `decisions/` for why, and `rules/` or `knowledge/` for what changes.
