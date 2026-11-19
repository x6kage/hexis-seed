#!/bin/bash
set -eu

SRC="$(cd "$(dirname "$0")" && pwd)/hexis"
DEST="$HOME/.claude"

fail() {
  echo "error: $*" >&2
  exit 1
}

[ -f "$SRC/CLAUDE.md" ] && [ -f "$SRC/settings.json" ] || fail "$SRC does not look like the Seed's hexis/ folder"

manifest() {
  (
    cd "$1" || exit 1
    find . -type d | LC_ALL=C sort | sed 's/^/dir /'
    find . -type l | LC_ALL=C sort | while IFS= read -r link; do
      printf 'link %s -> %s\n' "$link" "$(readlink "$link")"
    done
    find . -type f -exec cksum {} + | LC_ALL=C sort -k3
  )
}

PY="$(command -v python || command -v python3 || true)"
[ -n "$PY" ] || fail "no python or python3 on PATH; the hooks need Python 3.10 or later; nothing was changed"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' ||
  fail "$PY is $("$PY" -V 2>&1); the hooks need Python 3.10 or later; nothing was changed"

inner_links() {
  (cd "$SRC" && find . -mindepth 1 | sed 's|^\./||') | while IFS= read -r rel; do
    prefix=""
    rest="$rel"
    while :; do
      part="${rest%%/*}"
      prefix="${prefix:+$prefix/}$part"
      if [ -L "$DEST/$prefix" ]; then
        echo "$DEST/$prefix"
        break
      fi
      [ "$rest" = "$part" ] && break
      rest="${rest#*/}"
    done
  done | LC_ALL=C sort -u
}

if [ -L "$DEST" ] && [ ! -d "$DEST" ]; then
  fail "$DEST is a symlink that does not point to a directory; nothing was changed"
fi

if [ -e "$DEST" ]; then
  LINKS="$(inner_links)"
  if [ -n "$LINKS" ]; then
    echo "error: these paths inside $DEST are symlinks where the Seed would write; copying would overwrite their" >&2
    echo "targets, and a backup would hold only the links. Replace them with real files or folders, then run again." >&2
    echo "Nothing was changed." >&2
    printf '%s\n' "$LINKS" | sed 's/^/  /' >&2
    exit 1
  fi
  if [ -L "$DEST" ]; then
    TARGET="$(cd -P "$DEST" && pwd -P)" || fail "cannot resolve the symlink $DEST; nothing was changed"
    echo "$DEST is a symlink to $TARGET; backing up the contents of $TARGET."
  else
    TARGET="$DEST"
  fi
  BACKUP="$HOME/.claude.backup-$(date +%Y%m%d-%H%M%S)"
  [ -e "$BACKUP" ] && fail "$BACKUP already exists; nothing was changed"
  echo "Backing up $TARGET to $BACKUP ..."
  mkdir "$BACKUP" || fail "cannot create $BACKUP; $DEST was not touched"
  cp -Rp "$TARGET"/. "$BACKUP"/ || fail "the backup into $BACKUP failed; $DEST was not touched"
  MANIFEST_DEST="$(manifest "$TARGET")" || fail "cannot list $TARGET; $DEST was not touched"
  MANIFEST_BACKUP="$(manifest "$BACKUP")" || fail "cannot list $BACKUP; $DEST was not touched"
  [ "$MANIFEST_DEST" = "$MANIFEST_BACKUP" ] ||
    fail "the backup at $BACKUP differs from $TARGET (file list, sizes or checksums); $DEST was not touched"
  echo "Backup verified: $(printf '%s\n' "$MANIFEST_BACKUP" | grep -c '') entries with matching sizes and checksums."
else
  mkdir -p "$DEST" || fail "cannot create $DEST"
fi

cp -Rp "$SRC"/. "$DEST"/ || fail "copying $SRC into $DEST failed${BACKUP:+; the previous contents are in $BACKUP}"

escape_pattern() {
  printf '%s' "$1" | sed 's/[][\\.*^$|]/\\&/g'
}

escape_replacement() {
  printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

replace() {
  file="$1"
  from="$2"
  to="$3"
  grep -qF "$from" "$file" || fail "$file does not contain $from"
  tmp="$file.setup-tmp"
  sed "s|$(escape_pattern "$from")|$(escape_replacement "$to")|" "$file" > "$tmp" || fail "rewriting $file failed"
  grep -qF "$to" "$tmp" || fail "rewriting $file did not produce $to"
  mv "$tmp" "$file" || fail "replacing $file failed"
}

replace "$DEST/settings.json" '"path": "~/.claude/mods"' "\"path\": \"$HOME/.claude/mods\""
replace "$DEST/mods/jev-band/hooks/register.tsx" "const LOGS = '~/.claude/logs'" "const LOGS = '$HOME/.claude/logs'"
chmod +x "$DEST/scripts/deny-check.sh" "$DEST/mcp/linear_mcp/scripts/cf-secrets.sh" || fail "chmod failed"

cat <<EOF

Hexis is in $DEST. Still to do by hand (README.md has the details):
  1. Install the tools: python3 (3.13) with the mcp package, git, jq, bun, ruff, pyright; agy, yt-dlp and ffmpeg
     for the see-hear skill.
  2. Make $DEST a git repository: cd "$DEST" && git init (CLAUDE.md assumes the tree is its own repo).
  3. Install the plugins:
       claude plugin install jev-band@hexis-mods
       claude plugin install pyright-lsp@claude-plugins-official
       claude plugin install clangd-lsp@claude-plugins-official
  4. Put the keys you hold into $DEST/secrets/ (file names in README.md). Without the Jev key the Jev checks stay off.
  5. Register the MCP servers you use with 'claude mcp add' (README.md).
  6. Start a new Claude Code session and check that the SessionStart hook runs.
EOF
