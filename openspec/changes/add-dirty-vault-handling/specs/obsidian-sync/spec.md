## MODIFIED Requirements

### Requirement: Git Sync
The system SHALL perform atomic git operations when syncing: detect a
pre-existing dirty working tree, then pull, write the file, commit, and
push. All git operations SHALL run via `asyncio.to_thread` to avoid
blocking the event loop. The sync function SHALL distinguish the
following outcomes in its returned status: `ok`, `noop`, `dirty`,
`conflict`, `push_failed`.

#### Scenario: Successful sync on a clean tree
- **WHEN** the working tree has no uncommitted changes other than the
  file the bot is about to write
- **THEN** the system SHALL: git pull --rebase, write the file, git
  add, git commit, git push
- **AND** return `status="ok"`

#### Scenario: Dirty tree with auto-stash disabled
- **WHEN** the working tree has uncommitted changes other than the file
  the bot is about to write
- **AND** `auto_stash_dirty` is false in config
- **THEN** the system SHALL NOT run any git operations, SHALL NOT write
  any conflict sidecar, and SHALL return `status="dirty"` with a
  message listing the dirty paths

#### Scenario: Dirty tree with auto-stash enabled
- **WHEN** the working tree has uncommitted changes other than the file
  the bot is about to write
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
