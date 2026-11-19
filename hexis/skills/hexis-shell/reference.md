# Bash tool: heredocs and quoting

- `unexpected EOF while looking for matching `''` from the Bash tool is a harness failure, not a
  typo to fix: the same command text succeeds thousands of times and fails ~1 % (77 of ~9,000
  multi-line heredocs, 2.1.260-2.1.275, every failure a multi-line `<<'EOF'` body). The reported
  line is meaningless. **Never re-send the command.** Switch to the Write tool for the content
  (then `python file.py` / `cat file`), in the same turn. Retrying the identical heredoc up to 18
  times is what the token waste was (measured).
- Anything over ~50 lines, or a Python patch script with `'''` strings, goes through Write from the
  start; heredocs are for short snippets.
- One heredoc delimiter per command: a `cat > x <<'EOF'` inside a `python - <<'EOF'` body ends the
  outer heredoc at the inner `EOF`.
- No bare backtick inside a bash double-quoted string (PowerShell `` `n ``, `` `$ `` one-liners
  fail with `eval: line 1: unexpected EOF`): write the .ps1 with Write and run `pwsh -File`.
