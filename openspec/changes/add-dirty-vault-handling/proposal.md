# Change: Handle pre-dirty vault state in git sync

## Why

The current sync path assumes the vault's working tree is clean when it
runs `git pull --rebase`. When the user (or our own `import-vault`
subcommand) leaves uncommitted changes behind, the rebase refuses to run
with "cannot pull with rebase: You have unstaged changes" and the bot
treats the failure as a rebase *conflict*, writing a `{slug}.conflict.md`
sidecar and replying with a misleading "git rebase conflicted" message.
This happened today on `/new cuentos` and `/new TODO` after
`import-vault` rewrote six files without committing them, producing
bogus conflict sidecars and leaving DB rows without matching vault
files.

The fix is to distinguish "vault has uncommitted changes" from "rebase
truly conflicted" and to fail fast with a clear error in the former
case. An optional opt-in auto-stash lets power users have the bot
transparently handle pre-dirty state.

## What Changes

- Add a `dirty` `SyncStatus` distinct from `conflict` and `push_failed`.
- Before `git pull --rebase`, check `git status --porcelain`. If the
  tree has changes unrelated to the file the bot is about to write,
  return `dirty` without touching the repo or writing a sidecar.
- The handler path replies with "vault has uncommitted changes; commit
  or stash them before I can sync" when sync returns `dirty`.
- Add `[obsidian] auto_stash_dirty: bool = false` config option. When
  true, the bot does `git stash push -u -m secondbrain-autostash`
  before pull and `git stash pop` after a successful push. If the pop
  conflicts, the bot leaves the stash in place and surfaces the stash
  ref to the user via Telegram so they can recover manually.
- The existing `conflict` status keeps its meaning: a true rebase merge
  conflict between pulled remote changes and the bot's local write.
  Conflict sidecars are only written for this case.

## Impact

- Affected specs: `obsidian-sync` (MODIFIED: Git Sync, Markdown File
  Generation stays untouched)
- Affected code:
  - `src/secondbrain/obsidian.py` - add dirty pre-check, new status,
    optional stash path.
  - `src/secondbrain/config.py` - add `auto_stash_dirty` to
    `ObsidianSettings`.
  - `src/secondbrain/handlers.py` - handle the new `dirty` status in
    every place that reports sync results.
  - `tests/test_obsidian.py` - cover clean-tree happy path, dirty
    rejection, auto-stash success, auto-stash with pop conflict.
  - `README.md` - document the config flag and the recovery steps.
