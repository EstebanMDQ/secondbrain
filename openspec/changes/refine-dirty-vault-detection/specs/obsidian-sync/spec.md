## MODIFIED Requirements

### Requirement: Git Sync
The system SHALL perform atomic git operations when syncing: detect a
pre-existing dirty working tree, then pull, write the file, commit, and
push. All git operations SHALL run via `asyncio.to_thread` to avoid
blocking the event loop. The sync function SHALL distinguish the
following outcomes in its returned status: `ok`, `noop`, `dirty`,
`conflict`, `push_failed`.

The dirty pre-check SHALL classify `git status --porcelain` entries by
their index and worktree status codes. An entry SHALL count as
blocking when its index status is one of `M A D R C U`, OR its
worktree status is one of `M A D U` (`A` covers `git add -N`
intent-to-add files, which `git pull --rebase` refuses to overwrite).
Untracked entries (`??`) SHALL NOT count as blocking. The pre-check
SHALL NOT pass `--ignored` to `git status`, so ignored files do not
appear in its output. Before classification, the pre-check SHALL
filter out:
- the file the bot is about to write (the existing `skip_rel_path`),
  and
- any path matching an entry in the `dirty_ignore_paths` config list.

A `dirty_ignore_paths` entry ending in `/` matches any path that
starts with that exact prefix (directory match, including the
directory itself and everything under it). An entry without a
trailing `/` matches a path only when the path equals the entry
exactly. Paths matching `dirty_ignore_paths` SHALL NOT appear in the
`dirty` user-facing list; however, if any such path *is* dirty (i.e.
would actually block `git pull --rebase`), the bot SHALL stash all
dirty content before the pull and restore it with `git stash pop`
after a successful push - the ignore list is an opt-in "stash this
out of my way" escape hatch, not a way to tell git to ignore real
working-tree state. This auto-stash-for-ignored-paths happens
regardless of the `auto_stash_dirty` flag (the flag governs the
broader case of stashing un-ignored dirty content).

#### Scenario: Successful sync on a clean tree
- **WHEN** the working tree has no blocking entries other than the
  file the bot is about to write
- **THEN** the system SHALL: git pull --rebase, write the file, git
  add, git commit, git push
- **AND** return `status="ok"`

#### Scenario: Untracked-only working tree is not dirty
- **WHEN** the working tree's only non-clean entries are untracked
  (e.g. a `.backup/` folder appearing as a single `??` line)
- **THEN** the system SHALL proceed with the normal sync flow
- **AND** return `status="ok"` (or `noop` if applicable)
- **AND** SHALL NOT return `status="dirty"`

#### Scenario: Locally-modified target file does not block sync
- **WHEN** the only blocking entry is the file the bot is about to
  write (the `skip_rel_path`)
- **THEN** the pre-check SHALL filter it out
- **AND** the system SHALL proceed with the normal sync flow without
  returning `status="dirty"`

#### Scenario: Intent-to-add file blocks sync
- **WHEN** the working tree has a `git add -N` (intent-to-add) entry,
  surfaced by porcelain as worktree status `A`, and that path is not
  covered by `skip_rel_path` or `dirty_ignore_paths`
- **AND** `auto_stash_dirty` is false
- **THEN** the system SHALL return `status="dirty"` listing the
  intent-to-add path

#### Scenario: Tracked-modified file blocks sync with auto-stash disabled
- **WHEN** the working tree has a tracked file with local modifications
  (index or worktree status in the blocking set) other than the file
  the bot is about to write
- **AND** `auto_stash_dirty` is false in config
- **AND** that path is not covered by `dirty_ignore_paths`
- **THEN** the system SHALL NOT run any git operations, SHALL NOT write
  any conflict sidecar, and SHALL return `status="dirty"` with a
  message listing the blocking paths

#### Scenario: Dirty path covered by dirty_ignore_paths is stashed transparently
- **WHEN** the working tree's only blocking entries match an entry in
  `dirty_ignore_paths`
- **AND** `auto_stash_dirty` is false in config
- **THEN** the system SHALL stash the working-tree content before
  `git pull --rebase` so the rebase can proceed
- **AND** SHALL NOT return `status="dirty"`
- **AND** SHALL run `git stash pop` after a successful push to
  restore the ignored changes
- **AND** SHALL return `status="ok"`

#### Scenario: Directory prefix entry matches nested paths
- **WHEN** `dirty_ignore_paths` contains `.backup/` and the only
  blocking entry is `.backup/notes.md`
- **THEN** the pre-check SHALL filter that entry out and proceed with
  the normal sync flow

#### Scenario: Non-slash entry requires an exact match
- **WHEN** `dirty_ignore_paths` contains `.obsidian` (no trailing
  slash) and the working tree has a blocking entry
  `.obsidian/workspace.json`
- **THEN** the pre-check SHALL NOT filter `.obsidian/workspace.json`
- **AND** the system SHALL return `status="dirty"` for that path

#### Scenario: Mixed ignored and un-ignored blocking entries
- **WHEN** the working tree has two blocking entries, one matching a
  `dirty_ignore_paths` entry and one not
- **AND** `auto_stash_dirty` is false
- **THEN** the system SHALL return `status="dirty"`
- **AND** the message SHALL list only the un-ignored path

#### Scenario: Dirty tree with auto-stash enabled
- **WHEN** the working tree has blocking entries (after filtering)
  other than the file the bot is about to write
- **AND** `auto_stash_dirty` is true in config
- **THEN** the system SHALL run `git stash push -u -m
  secondbrain-autostash-<slug>-<ts>` before the pull
- **AND** proceed with pull, write, commit, push
- **AND** run `git stash pop` after a successful push

#### Scenario: Auto-stash pop conflicts with bot's commit
- **WHEN** auto-stash is active and `git stash pop` fails because the
  stashed changes touch the file the bot just wrote
- **THEN** the system SHALL leave the stash in place
- **AND** return `status="ok"` with a message that includes the stash
  reference so the user can recover manually

#### Scenario: Genuine rebase merge conflict
- **WHEN** `git pull --rebase` fails on a file that was modified on
  both sides of the pull
- **THEN** the system SHALL abort the rebase, write
  `{project-slug}.conflict.md`, and return `status="conflict"`

#### Scenario: Git push failure
- **WHEN** `git push` fails for reasons other than a rebase conflict
- **THEN** the system SHALL preserve the local commit, log the error,
  and return `status="push_failed"` with the push error message

#### Scenario: No-op when the file content is unchanged
- **WHEN** the rendered file content matches what is already on disk
- **THEN** the system SHALL skip the commit and push and return
  `status="noop"`

#### Scenario: Async git operations
- **WHEN** the sync function is invoked from an async handler
- **THEN** git operations SHALL run via `asyncio.to_thread`
