## 1. Config

- [x] 1.1 Add `dirty_ignore_paths: list[str] = field(default_factory=list)`
      to `ObsidianSettings` in `src/secondbrain/config.py`.
- [x] 1.2 Load it from the `[obsidian]` TOML section and accept an env-
      var override (`SECONDBRAIN_OBSIDIAN_DIRTY_IGNORE_PATHS`, comma-
      separated) consistent with how `auto_stash_dirty` is loaded.
- [x] 1.3 Surface the field on `BotContext` and thread it from the
      settings into the context at startup.

## 2. Dirty classification

- [x] 2.1 Rework `_dirty_paths` in `src/secondbrain/obsidian.py`:
      - Drop the `-uall` flag from the `git status --porcelain` call;
        do not pass `--ignored`.
      - Parse each porcelain line into `(index_status, worktree_status,
        path)`.
      - Treat an entry as blocking only when `index_status in
        {"M","A","D","R","C","U"}` or `worktree_status in
        {"M","A","D","U"}` (worktree `A` covers `git add -N`
        intent-to-add). Skip untracked (`??`).
- [x] 2.2 Extend the signature to accept
      `ignore_paths: Sequence[str] = ()`. Filter blocking entries by
      prefix match before returning: entries ending in `/` match any
      path that starts with that prefix; other entries match the path
      exactly. Continue to also filter `skip_rel_path`.
- [x] 2.3 Update `sync_project` to accept `dirty_ignore_paths:
      Sequence[str] = ()` and forward it to `_dirty_paths`. Use the
      filtered list for both the early `dirty` return message and the
      decision to stash when `auto_stash_dirty` is true.
- [x] 2.4 Update `sync_project_async` to forward the new parameter.

## 3. Handlers

- [x] 3.1 At every `sync_project_async` call site in
      `src/secondbrain/handlers.py`, pass
      `dirty_ignore_paths=ctx.dirty_ignore_paths` alongside the
      existing `auto_stash_dirty=ctx.auto_stash_dirty`.
- [x] 3.2 No reply-text changes; existing `dirty` branch already shows
      the message from the sync result, which now reflects the
      filtered list.

## 4. Tests

- [x] 4.1 Unit-test `_dirty_paths` directly in `tests/test_obsidian.py`
      against a real temp repo covering:
      - Clean tree -> empty list.
      - Only untracked files/folders -> empty list.
      - `git add -N` (intent-to-add) file -> path listed.
      - Tracked-modified file -> path listed.
      - Tracked-modified file matching a `ignore_paths` directory
        prefix entry (`.backup/`) -> empty list.
      - Non-slash `ignore_paths` entry (`.obsidian`) does NOT match
        `.obsidian/workspace.json` -> path still listed.
      - Mixed (one tracked-modified, one untracked, one ignored
        prefix) -> only the unfiltered tracked-modified path.
      - Locally-modified target file (matches `skip_rel_path`) ->
        empty list.
- [x] 4.2 Extend `sync_project` tests:
      - Vault with only an untracked `.backup/` folder returns `ok`,
        not `dirty`.
      - Vault with a tracked-modified file outside `dirty_ignore_paths`
        and `auto_stash_dirty=false` still returns `dirty`.
      - Vault with a tracked-modified file inside
        `dirty_ignore_paths` (and `auto_stash_dirty=false`) is stashed
        transparently, sync proceeds, stash pops, result is `ok`, and
        the ignored file is restored to its pre-sync state.
      - Mixed ignored + un-ignored dirty paths still returns `dirty`,
        and the result message contains only the un-ignored path.
      - Existing auto-stash test still passes when the only changes
        are tracked-modified.
- [x] 4.3 Updated `test_dirty_paths_reports_modified_and_untracked` ->
      `test_dirty_paths_ignores_untracked_only` and
      `test_dirty_paths_reports_tracked_modified` so we no longer
      assert that untracked content surfaces as dirty.

## 5. Docs

- [x] 5.1 Document `dirty_ignore_paths` under "Configuration reference"
      in `README.md` with examples (`.backup/`,
      `.obsidian/workspace.json`).
- [x] 5.2 Update the "vault has uncommitted changes" troubleshooting
      entry to note that only tracked-modified content triggers the
      message and that `dirty_ignore_paths` is the escape hatch.

## 6. Validation

- [x] 6.1 `uv run pytest`.
- [x] 6.2 `openspec validate refine-dirty-vault-detection --strict
      --no-interactive`.
