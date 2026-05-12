## Why

The current dirty-vault check runs `git status --porcelain -uall`, which
lists every untracked file individually. As a result the bot refuses to
sync whenever the vault has cosmetic untracked content like a `.backup/`
folder, an Obsidian `.trash/`, or editor swap files - none of which can
actually block `git pull --rebase`. The user hit this today trying to
capture into `notest`: an untracked `.backup` folder caused a `dirty`
reply even though the rebase would have succeeded. The check needs to
classify "dirty" by what git actually refuses to rebase over, not by
"anything not committed".

## What Changes

- `_dirty_paths` SHALL distinguish tracked-modified/staged entries
  (which actually block `git pull --rebase`) from untracked entries
  (which do not). Untracked entries SHALL NOT cause a `dirty` result by
  default.
- Add `[obsidian] dirty_ignore_paths: list[str] = []` to
  `ObsidianSettings`. Entries are gitignore-style path prefixes
  (e.g. `".backup/"`, `".obsidian/workspace.json"`); matches are filtered
  from the dirty set before classification.
- The `dirty` `SyncStatus` keeps its meaning but only fires for paths
  that survive both filters (tracked-modified, not on the ignore list).
- The user-facing dirty message and the auto-stash code path SHALL
  operate on the same filtered set so they stay consistent.
- No new bot commands and no change to the existing `auto_stash_dirty`
  flag.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities
- `obsidian-sync`: refine the Git Sync requirement so the dirty check
  ignores untracked entries by default and honors a configurable
  ignore list.

## Impact

- Affected code:
  - `src/secondbrain/obsidian.py` - rework `_dirty_paths` to classify
    porcelain lines and accept an ignore list; plumb the new parameter
    through `sync_project` / `sync_project_async`.
  - `src/secondbrain/config.py` - add `dirty_ignore_paths` to
    `ObsidianSettings` with TOML and env-var support.
  - `src/secondbrain/handlers.py` - pass `dirty_ignore_paths` into the
    sync calls (via `BotContext`).
  - `tests/test_obsidian.py` - cover untracked-only, ignore-list match,
    tracked-modified, and mixed cases.
  - `README.md` - document `dirty_ignore_paths` and update the
    troubleshooting entry for dirty vaults.
- No migration or config rewrite: the new field defaults to an empty
  list and the untracked-as-clean behavior is the new baseline. Users
  who relied on the bot refusing to sync over untracked files would
  need to add them to the ignore list - but no one has asked for that,
  and untracked files are not a real conflict source.
