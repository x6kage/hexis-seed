---
name: hexis-shell
description: Use before a Bash or PowerShell command that carries a heredoc, a multi-line body, an inline script, Windows paths or non-ASCII output on this Windows machine - the Bash tool's quoting failures and the tool-shell pitfalls.
---

# Shell commands from the Claude tool

Full text: `reference.md` in this folder.

## Heredocs and multi-line content
- `unexpected EOF while looking for matching `''` from a multi-line heredoc is a harness failure (~1 % of multi-line `<<'EOF'` bodies), not a typo. The reported line number is meaningless. **Never re-send the command.** Switch to the Write tool for the content in the same turn, then run it (`python file.py`, `cat file`).
- Anything over ~50 lines, or a Python script with `'''` strings, goes through Write from the start. Heredocs are for short snippets only.
- One heredoc delimiter per command: a `cat > x <<'EOF'` inside a `python - <<'EOF'` body ends the outer heredoc at the inner `EOF`.
- A double backslash inside a quoted heredoc collapses to one (a single one survives): a Python line needing a literal backslash-n gets a real newline and breaks. Build such characters with `chr(92)`, or write the script with Write using raw strings.
- A Windows path or regex `\{` in a normal Python string fed through a heredoc raises `unicodeescape` / SyntaxWarning: write the script to a scratchpad file with raw strings instead.

## Quoting
- No bare backtick inside a bash double-quoted string (PowerShell `` `n ``, `` `$ ``): write the `.ps1` with Write and run `pwsh -File`.
- `wsl.exe -- bash -lc "..."` loses its quoting to the outer shell: pass the script on stdin.
- Git Bash rewrites `/etc/...`-style arguments (MSYS path conversion).

## Python on Windows
- Python does not understand `/c/...` paths: use `C:\...` (or `C:/...`).
- Set `PYTHONIOENCODING=utf-8` when printing Japanese from Python in the Bash tool.
- Install Python tools into the base interpreter (`python -m pip install --ignore-installed <pkg>`), never `--user`: the user site lands in the desktop app's virtualised container that other programs never see.

## Processes and the Job object
- The tool shell runs inside a Job object: a resident started with `Start-Process` dies when the shell is reclaimed. Start residents through WMI (`Invoke-CimMethod -ClassName Win32_Process -MethodName Create ...`).
- A pwsh spawned through WMI opens a visible Windows Terminal window: never spawn one while a game is on screen; prefer editing hot-reloaded config (komorebi.json) over `komorebic` calls.
- AF_UNIX sockets cannot bind or connect under `AppData` (except `%LOCALAPPDATA%\Temp` and `Packages`).
- Elevation (MSI install/uninstall) only through `Start-Process pwsh -Verb RunAs -File <script.ps1>`; the user must accept UAC.
- A PATH change reaches only processes started afterwards.

## Other
- Never poll a background command: run it in the foreground and wait.
- Never build a filesystem path from a Claude Code project key (`D--x-y-z`): `:`, `\` and `_` all map to `-`.
- Teardown commands (uninstalls, killing residents, removing autostart, reboots) are refused by the deny list and `hooks/guard.py`: tell the user what to run instead of working around the refusal.
