# Seed

Claude Code の作業環境 (Hexis) を macOS の `~/.claude` に置くためのリポジトリです。特定の人の記録・アカウント・機械の情報は含みません。

- `hexis/` … `~/.claude` にそのまま置く中身 (rules, agents, skills, hooks, scripts, mods, mcp, settings.json)
- `setup-macos.sh` … `hexis/` を `~/.claude` に置くスクリプト

`setup-macos.sh` は macOS 上ではまだ実行されていません (Linux の bash で、空の home、既存の `~/.claude`、symlink の `~/.claude`、`~/.claude` 内の symlink、`&` `|` `\` を含む home、古い Python、コピー失敗、backup 不一致を試しています)。

## 前提

- Claude Code の CLI (`claude`) と、`claude` でのサインイン
- Python 3.10 以上 (`python` か `python3`; ruff と pyright の設定は 3.13)。hook は `"$(command -v python || command -v python3)"` で起動します
- `git`
- `jq` (`scripts/deny-check.sh` が `settings.json` の deny を読みます)
- `bun` (`mcp/linear_mcp` のテストと、その前に走る biome / tsc)
- `ruff` と `pyright` (`scripts/check.py`)
- Python パッケージ `mcp` (`scripts/check.py` が `mcp/linear_claude` のテストを走らせるので必須です)
- `agy` (Antigravity CLI、Google アカウントでのサインインは各自の端末で)、`yt-dlp`、`ffmpeg` (skill `see-hear` を使う場合のみ)

## 置き方

```
./setup-macos.sh
```

0. 何かを書く前に確かめます。`python` か `python3` が 3.10 以上でなければ止まります (hook が必要とするためです)。`~/.claude` の中で Seed が書き込む場所 (ファイルでもフォルダでも、`skills/` のような途中のフォルダでも) が symlink なら、その一覧を出して止まります。そのままコピーするとリンク先を上書きし、backup にはリンクしか残らないためです。どちらの場合も何も書きません。
1. `~/.claude` が既にあれば、まず `~/.claude.backup-YYYYMMDD-HHMMSS` に丸ごとコピーし、ファイル一覧・サイズ・チェックサム (`cksum`) が元と一致するか確かめます。`~/.claude` が symlink なら、リンク先の中身をコピーします (リンクそのものは backup として扱いません)。リンク先が無い symlink、コピーの失敗、一致しない backup のときは、何も上書きせずに終了します。
2. `hexis/` の中身を `~/.claude` に重ねてコピーします。同じ名前のファイル (`CLAUDE.md`, `settings.json` など) は Seed の版になり、それ以外 (`projects/`, `.credentials.json` など) は残ります。
3. 次の 2 か所を `$HOME` の絶対パスに書き換えます。どちらも `~` を展開しないためです。
   - `settings.json` の `extraKnownMarketplaces.hexis-mods.source.path` (`~/.claude/mods`)
   - `mods/jev-band/hooks/register.tsx` の `LOGS` (`~/.claude/logs`)
4. 残りの手作業を表示します。

置いたあと、CLAUDE.md は `~/.claude` が独立した git リポジトリである前提なので、`git init` してください。

```
cd ~/.claude && git init
```

手で置く場合も同じ順番です: `cp -RpL ~/.claude/ ~/.claude.backup-<日時>` で退避してから `cp -Rp hexis/. ~/.claude/`、そのあと上の 2 か所を書き換えます。`-L` は symlink をたどって中身をコピーするので、`~/.claude` 自体や中のファイルが symlink でも backup に中身が残ります。ただし `~/.claude` の中で Seed が書き込む場所に symlink があると、`cp -Rp hexis/. ~/.claude/` がリンク先を上書きします。先にそれを実ファイル・実フォルダに置き換えてください。

## 最初に書き換えるもの

- `~/.claude/CLAUDE.md` の「Who I am」(自分が誰か、従わせたい作業環境の決まり) と、「Language」の返答言語 (既定は日本語)
- `settings.json` の `model` (既定は `claude-fable-5-2[1m]`) と、`language`、`defaultMode` などの好み

## プラグイン

`settings.json` の `enabledPlugins` で有効になっているものを入れます。

```
claude plugin install jev-band@hexis-mods
claude plugin install pyright-lsp@claude-plugins-official
claude plugin install clangd-lsp@claude-plugins-official
```

`typesafe@typesafe-ai`, `rust-analyzer-lsp`, `csharp-lsp` は `false` のままです。

## 各自で用意する鍵と設定 (名前のみ)

`~/.claude/secrets/` に置くファイル:

- `typesafe_hexis_api_key.txt` … Jev (`hooks/jev_client.py`)。無い場合、Jev を使う 9 つの hook (brief-check, commit-gate, hold-gate, md-check, misread-check, output-check, relay-check, restate-gate, route-check) は判定せず、`logs/jev-hooks.jsonl` に error を記録して通します。Jev の読みの行が出ないので jev-band の帯は読みの行なしになります。
- `linear_claude_oauth.txt`, `linear_claude_api_key.txt` … `scripts/linear_client.py`, `mcp/linear_claude/server.py`
- `linear_peer_oauth.txt`, `linear_mcp_peer_key.txt` … `mcp/linear_mcp/scripts/cf-secrets.sh` (2 つ目の app identity `/peer` を使う場合)

`~/.claude/local.json` (任意、Seed には含みません。無ければどちらも空です):

```
{
  "private_folders": ["~/<触らせないフォルダ>"],
  "foreground_projects": ["<~/dev の下のフォルダ名>"]
}
```

- `private_folders` … `scripts/sweep.py` が決して触らず、skill `see-hear` が決して外部へ送らないフォルダ
- `foreground_projects` … `hooks/input-guard.py` が、そのプロジェクト自身の Rust ソース (`~/dev/<名前>/<…>/src/*.rs`) に限って、ウィンドウを前面に出す API を許すプロジェクト

環境変数 (使う場合):

- `LINEAR_CLAUDE_CLIENT_ID`, `LINEAR_CLAUDE_CLIENT_SECRET`, `LINEAR_CLAUDE_API_KEY`, `LINEAR_OAUTH_FILE`
- `LINEAR_HANDOFF_USER` … Linear の `handoff` でユーザーを指定しなかったときに担当にする人 (名前・表示名・メール・UUID)。未設定なら `owner`
- `mcp/linear_mcp` (ID は `CLAUDE` と `PEER`): `LINEAR_<ID>_CLIENT_ID`, `LINEAR_<ID>_CLIENT_SECRET`, `MCP_KEY_<ID>`。Cloudflare 用に `.env.workers.secrets`, `.dev.vars`

Seed に入れていないもの:

- `scripts/linear_ops.json` … Linear の workspace・ユーザー・チーム・プロジェクトの ID。`scripts/linear_ops.py` が読みます
- MCP の登録 (`~/.claude.json`): `linear-mcp` (remote の URL と Authorization header)、`linear-claude` (`claude mcp add --scope user linear-claude -- python ~/.claude/mcp/linear_claude/server.py`)
- docs hub の artifact の URL (`process/docs-hub.md` の `<docs-hub artifact URL>`) と、docs hub を組み立てるファイル一式 (`outputs/docs-hub/` の `list.tsv`, `template.html`, `build.py`, `originals/`)

## 意図して入れていないもの

- 記録: `decisions/`, `inbox/`, `outputs/`, `docs/`, `evals/` の中身 (各フォルダには形式を説明する README だけ入れています)、`STATE.md`、`projects/` (各プロジェクトの memory、feedback memory、`OWNER.md`、`PROGRESS.md`)
- `knowledge/` の中身 (コードが読む `knowledge/model-pricing.md` と、空の `knowledge/INDEX.md` だけ入っています)。規則や skill が名前を出す `knowledge/machine.md` などは、各自が書き足すまでありません
- 実行時のもの: `logs/`, `secrets/`, `.credentials.json`, `~/.claude.json`, `local.json`, backup

## プラットフォームの注意

- `hooks/session-start.py` の sweep 起動は pwsh と WMI を使うため Windows 以外では起動しません。`scripts/sweep.py` は Windows の temp の配置を前提にしています
- `scripts/model-lineup-check.py` は入っていますが、定期実行は設定されません
- `hooks/guard.py` は Windows・Linux・macOS の後始末系コマンド (アンインストール、自動起動の解除、常駐プロセスの停止、再起動) をまとめて止めます。skill `hexis-shell` は Windows の tool shell の注意点です

## 確認

```
cd ~/.claude/mcp/linear_mcp && bun install
cd ~/.claude && python3 scripts/check.py
```

`scripts/check.py` は ruff format / ruff check --fix / pyright / unittest (`scripts/tests`, `mcp/linear_claude`) / `bun test` (`mcp/linear_mcp`) を順に実行します。
