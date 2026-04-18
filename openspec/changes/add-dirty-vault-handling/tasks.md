# Tasks: add-dirty-vault-handling

## 1. Status and config
- [x] 1.1 Extend `SyncStatus` in `obsidian.py` with `"dirty"`.
- [x] 1.2 Add `auto_stash_dirty: bool = False` to `ObsidianSettings` in
      `config.py`; surface it in env-var overrides and in the TOML load.
- [x] 1.3 Default the init wizard behavior: do not prompt for it;
      written with the hard-coded default.

## 2. Sync logic
- [x] 2.1 Add a helper `_dirty_paths(vault_path, skip_rel_path)` that
      runs `git status --porcelain` and returns the non-skipped paths.
- [x] 2.2 Integrate the helper into `sync_project` before
      `git pull --rebase`:
      - If dirty and `auto_stash_dirty` is false -> return
        `SyncResult(status="dirty", path=target, message=...)` without
        writing any sidecar and without running git operations.
      - If dirty and `auto_stash_dirty` is true -> `git stash push -u
        -m "secondbrain-autostash-<slug>-<ts>"` before pull.
- [x] 2.3 After a successful push, if a stash was created, `git stash
      pop`. On pop failure, leave the stash in place and attach the
      stash ref to the returned message.
- [x] 2.4 Thread the `auto_stash_dirty` flag into `sync_project` (and
      the async wrapper) as a parameter; plumb from the handler via
      `BotContext`.
- [x] 2.5 Keep existing `conflict` semantics: real rebase failures
      still abort the rebase and write a `{slug}.conflict.md` sidecar.

## 3. Handlers
- [x] 3.1 Add a `dirty` branch to each handler that inspects
      `result.status` (new-project command, text capture, confirmation
      callback, save flow). Reply with a short "vault has uncommitted
      changes; commit or stash" message that includes the first few
      dirty paths.

## 4. Tests
- [x] 4.1 Unit-test `_dirty_paths` against a real temp repo.
- [x] 4.2 Extend `tests/test_obsidian.py`:
      - Dirty vault with auto-stash off returns `dirty` and writes no
        sidecar.
      - Dirty vault with auto-stash on stashes, pulls, writes, commits,
        pushes, and pops cleanly.
      - Dirty vault with auto-stash on where `git stash pop` fails
        returns `ok` with a stash-left-in-place message.
      - Clean vault path still returns `ok`.
      - Genuine rebase conflict still returns `conflict` and writes a
        sidecar (regression check).

## 5. Docs
- [x] 5.1 Document `auto_stash_dirty` under "Configuration reference"
      in `README.md`, with a note about stash recovery.
- [x] 5.2 Add a "Troubleshooting" entry: what to do when the bot
      reports "vault has uncommitted changes".

## 6. Validation
- [x] 6.1 `uv run pytest` - all new and existing tests pass.
- [x] 6.2 `openspec validate add-dirty-vault-handling --strict
      --no-interactive`.
