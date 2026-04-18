# Design: handle pre-dirty vault in git sync

## Context

`sync_project` runs `git pull --rebase` as its first step. Git refuses a
rebase when the working tree has unstaged changes. The current code
treats that subprocess failure identically to a real rebase conflict:
abort rebase, write a `{slug}.conflict.md` sidecar, return `conflict`.
That is wrong: nothing conflicted; the user just has dirty state. The
sidecar misleads, the error message misleads, and the DB row persists
while the vault file does not.

## Goals / Non-Goals

- Goals
  - Distinguish dirty-tree rejection from rebase-merge conflict.
  - Never write a sidecar for dirty-tree rejection.
  - Give users a way to opt into transparent handling via stash.

- Non-Goals
  - A dedicated bot branch that the user merges back. This breaks
    cross-machine availability (the whole point of the sync), adds
    persistent branch state, and grows drift over time. Explicitly
    rejected.
  - Auto-committing the user's unrelated changes. The vault is the
    user's thinking space; silently committing work in progress is a
    footgun.

## Decisions

### New sync status: `dirty`

`SyncStatus` becomes `Literal["ok", "conflict", "dirty", "push_failed",
"noop"]`. The sync function returns `dirty` when the vault has
uncommitted changes that are not the file the bot is about to write and
auto-stash is disabled.

### Pre-sync dirty check

Before `git pull --rebase`:

1. Run `git status --porcelain`. Collect the list of paths with staged
   or unstaged changes.
2. Filter out the file the bot is about to write
   (`<subfolder>/<slug>.md`). The bot is allowed to overwrite its own
   output.
3. If the filtered list is non-empty:
   - With `auto_stash_dirty = false` (default): return `dirty` with a
     message listing the first few dirty paths.
   - With `auto_stash_dirty = true`: stash (see below), continue.

### Optional auto-stash

`git stash push -u -m "secondbrain-autostash-<slug>-<timestamp>"`
before pull. On successful push at the end, `git stash pop`.

- The stash message embeds the slug and timestamp so users can tell
  auto-stashes apart if several accumulate.
- The stash uses `-u` to include untracked files, so brand-new files
  outside the bot's subfolder are preserved.
- If the pop fails (merge conflict because the pulled remote changed a
  file the user had edited), the bot leaves the stash intact and
  returns a new `SyncResult(status="ok", message="stash left in place:
  <ref>")`. The handler surfaces that message so the user knows where
  their in-flight work is.

### What stays the same

- Real rebase conflicts still produce `{slug}.conflict.md` sidecars and
  return `conflict`. That behavior is spec'd and useful.
- `push_failed` semantics unchanged.
- The pull is still always run from the sync path; we do not skip pulls
  even on a brand-new file. Safety over cleverness.

### Handler wiring

Every handler that calls `sync_project_async` today already branches on
`result.status`. Each branch adds a `dirty` case:

- `new_project_command`: reply "created '<name>' but vault has
  uncommitted changes; commit or stash them and run `/project
  <name>` to retry the sync".
- `handle_text_message`: reply "saved note but vault is dirty; commit
  or stash before I can sync".
- Confirmation callback (new-project create): same treatment as the
  capture handler.

DB row stays written in all cases. Retry is safe because `_has_changes`
short-circuits `noop` when nothing actually changed.

## Risks / Trade-offs

- **Auto-stash pop conflicts still exist.** Rare in practice (the
  user's edit and the bot's write would need to touch the same file),
  but when it happens the user sees two reflog entries and a
  not-empty stash. Mitigated by: a clear message with the stash ref,
  so `git stash show` / `git stash pop` are one command away.
- **Dirty listing leaks paths.** The error message includes path
  names. Fine for a single-user bot; flagged here for awareness.
- **New config knob.** One more thing to document. Worth it - the
  default is safe and the escape hatch is minimal.

## Migration Plan

- Existing users: no action required. `auto_stash_dirty` defaults to
  false, so behavior for clean vaults is unchanged. Users who were
  running into the current bogus-conflict behavior will now see a
  clear "commit or stash" message instead.
- No DB changes.

## Open Questions

None.
