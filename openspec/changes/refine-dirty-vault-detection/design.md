## Context

`add-dirty-vault-handling` introduced a pre-sync check that runs
`git status --porcelain -uall` and returns `SyncStatus="dirty"` whenever
any non-skipped entry appears. `-uall` was added deliberately so the
skip filter could match a specific untracked file before a brand-new
directory existed, but its side effect is that *any* untracked content
in the vault makes the bot refuse to sync.

In practice the vault accumulates untracked content the user does not
think of as "uncommitted work": Obsidian's `.trash/`, backup directories
written by sync tools (`.backup/`), editor swap files, OS metadata
(`.DS_Store`). None of these block `git pull --rebase` - git refuses
the rebase only when it would clobber tracked, locally-modified files.
The current check is stricter than git itself and produces a confusing
UX where the bot reports "vault has uncommitted changes: .backup".

Constraints carried over from the existing design:
- The sync must remain atomic from the bot's perspective; we still
  need a deterministic order of pull -> write -> commit -> push.
- The `dirty` status SHALL remain distinct from `conflict` so handlers
  can keep producing distinct replies.
- `auto_stash_dirty` continues to exist for users who want the bot to
  stash and restore tracked changes around the sync.

## Goals / Non-Goals

**Goals:**
- Stop reporting `dirty` for working trees whose only "dirtiness" is
  untracked content - that content cannot block `git pull --rebase`.
- Let the user opt specific paths (tracked or otherwise) out of the
  dirty check via TOML config.
- Keep the existing `auto_stash_dirty` flow correct: when it is
  enabled, only the entries that would actually block the rebase get
  stashed, and untracked-only state never triggers an unnecessary
  stash.
- Keep handlers untouched semantically - they still get `ok` /
  `dirty` / `conflict` / `push_failed`.

**Non-Goals:**
- No worktree-based isolation (considered and rejected for now; see
  Decisions).
- No new bot commands for stashing/discarding from Telegram.
- No change to conflict-sidecar behavior.
- No retroactive renaming of `auto_stash_dirty`.

## Decisions

### Classify porcelain output instead of counting lines

`git status --porcelain` emits two-character status codes followed by
the path. The first character is the index status, the second is the
working-tree status. We will treat a porcelain entry as "blocking" only
when at least one of:

- the index status is one of `M A D R C U` (modified/added/deleted/
  renamed/copied/unmerged in the index), or
- the worktree status is one of `M A D U` (modified/intent-to-add/
  deleted/unmerged in the working tree).

`A` in the worktree column is `git add -N`. We include it because
`git pull --rebase` refuses to apply when an intent-to-add path would
be touched by the rebase, so it is a real blocker even though the
file has no content in the index.

Untracked entries (`??`) SHALL NOT be classified as blocking. We will
keep using `--porcelain` (v1) without `-uall` and without `--ignored`
for the classification pass, because we no longer need to enumerate
untracked content - it never contributes to `dirty` - and ignored
entries should not appear in the output at all.

**Alternatives considered:**
- *Drop the dirty check entirely and let `git pull --rebase` decide*:
  cleaner but loses the explicit `dirty` status we already wired into
  handlers, and the rebase failure message is opaque ("error: cannot
  pull with rebase: You have unstaged changes").
- *Run `git diff-index --quiet HEAD`*: simpler but doesn't surface the
  list of dirty paths for the user-facing message.

### Add `dirty_ignore_paths` config

Add `dirty_ignore_paths: list[str]` to `ObsidianSettings`, defaulting to
`[]`. Entries are matched as path prefixes against porcelain paths
(after stripping the 3-char prefix and trailing slash semantics). A
prefix match means: if the entry ends in `/`, treat it as a directory
prefix; otherwise treat it as an exact path match. This is enough for
the real cases (`".backup/"`, `".obsidian/workspace.json"`) without
introducing a full glob engine.

Paths matching `dirty_ignore_paths` are dropped from the *user-facing
dirty list*, but they are still recognised as actually-dirty working-
tree state. If any of them would block `git pull --rebase` (i.e. they
are tracked-modified or intent-to-add), the bot transparently stashes
the working tree before the pull and pops it after a successful
push - regardless of `auto_stash_dirty`. The flag and the list are
two opt-ins into the same stash machinery: `auto_stash_dirty` opts
*everything* in unconditionally; `dirty_ignore_paths` opts in only
those specific paths.

We considered the simpler "just filter at the dirty check, let pull
fail with conflict if it has to" interpretation. Rejected: the
feature would be useless for the very case it exists for - the user
asks the bot to ignore a tracked path, and the bot still produces a
confusing `conflict` sidecar.

**Alternative considered:** rely on `.gitignore` instead of a separate
list. Rejected: gitignore already prevents tracked files from being
listed as untracked; the new list specifically targets *tracked,
locally-modified* paths the user wants the bot to tolerate, which
gitignore cannot express.

### Plumb the ignore list through, not the config object

`sync_project` takes a `dirty_ignore_paths: Sequence[str] = ()`
parameter (sibling to `auto_stash_dirty`). The handler reads it from
`BotContext.dirty_ignore_paths` (which is loaded once from settings at
startup, like the existing flag). The sync layer does not import
config.

### Worktree isolation deferred

We considered giving the bot its own `git worktree`. That solves dirty
state structurally and is appealing, but:
- It changes the on-disk layout, the install flow, and how the user
  sees the bot's commits land in their main checkout.
- The current single-checkout approach has worked for everything
  except this one class of false positives, which the smaller change
  resolves directly.
- Worktree is still a viable next step if dirty UX keeps biting; the
  refined classification here doesn't preclude it.

## Risks / Trade-offs

- **Risk:** A real conflict-causing scenario hides behind an untracked
  file that the upcoming `git pull --rebase` would overwrite (very
  rare: it would require a new file on the remote with the exact same
  path as an untracked local file).
  → Mitigation: if it happens, `git pull --rebase` fails, the existing
  `conflict` path fires, and we write the conflict sidecar. The user
  gets a clear message; we just don't pre-empt the rebase.

- **Risk:** A user lists a tracked file in `dirty_ignore_paths` and
  then loses local edits because the bot proceeds to pull/commit
  around them.
  → Mitigation: documented in README that this list is an escape
  hatch for *bot-owned* paths the user knowingly tolerates; defaults
  remain empty. `git pull --rebase` would still refuse if it could
  not reconcile the file, falling back to `conflict`.

- **Trade-off:** Prefix matching is less expressive than gitignore
  globs. Acceptable: every real case we have is a prefix.

## Migration Plan

- No data migration. The config field is additive with a `[]` default.
- Existing installs upgrade transparently: behavior changes from
  "any uncommitted content blocks" to "only tracked-modified content
  blocks". This is strictly more permissive; nothing that previously
  worked stops working.
- Rollback: revert the change; the previous strict behavior returns.
