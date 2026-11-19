# Docs hub: every document and script made for the user, on one page

The user's decision: the Markdown files stay the originals, and a private claude.ai artifact page
(`<docs-hub artifact URL>`) is where they are collected and read. The page is a
view built from the originals; it is never the only copy of anything.

Files: `~/.claude/outputs/docs-hub/` - `list.tsv` (one line per entry: project, kind, absolute path, and for a
script a one-sentence Japanese note on what it does and how to run it), `template.html`, `build.py`,
`originals/<project>/` (originals for entries that were first written on the page itself).

## Adding or changing an entry (any session)
1. Write or update the original where it belongs (the project's docs/, a script in its folder). A document for the
   user is Japanese.
2. Add or edit its line in `list.tsv`.
3. Pull the live page first, because other writers (the claude.ai chat side) add entries directly on it:
   Artifact `read` with `url` and `path: "index.html"`, then
   `python ~/.claude/outputs/docs-hub/build.py --import <saved index.html>`. This writes every entry that has no
   file behind it to `originals/<project>/` and appends it to `list.tsv`, then builds `docs-hub.html`.
   From WSL run it with Windows Python: `python.exe build.py --import "$(wslpath -w <saved index.html>)"`. WSL `python3`
   sees every `C:\...` path as missing, re-imports all entries as duplicates and overwrites originals.
   Before `--import`, make sure every path in `list.tsv` exists: a listed file that moved makes the import treat the live entry as file-less and write a duplicate original, and the
   build then stops on the missing path. Repoint the line first, delete any duplicate the import wrote.
4. Publish `docs-hub.html` to the same `url`. A publish refused as out of date means someone published after the
   pull: pull and import again, never `force`.

## Rules
- No secrets on the page, private or not: a file holding a key, token or credential stays off `list.tsv`
  (yasb `config.yaml` is excluded for its weather API key).
- A deleted or retired original leaves the list in the same turn.
- Keep only what the user reads or runs; agent briefs, prompts for other models, working notes and logs stay out.
