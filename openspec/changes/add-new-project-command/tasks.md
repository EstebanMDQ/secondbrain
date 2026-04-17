# Tasks: add-new-project-command

## 1. Argument parser
- [x] 1.1 Add a pure parser in `handlers.py` (or a small helper module) that
      splits the raw argument text into `(name, description | None)` using
      the multi-line / dash-shorthand / name-only rules from design.md.
- [x] 1.2 Unit-test every branch: name only, dash-shorthand, multi-line,
      dash-shorthand with a hyphen in the name (resolves to the shorthand),
      multi-line that also contains ` - ` (multi-line wins), leading/trailing
      whitespace, empty argument (rejected).

## 2. Handler
- [x] 2.1 Implement `new_project_command` in `handlers.py`:
      parse args -> reject empty name -> check collision via
      `store.get_project` -> on collision, reply with the existing project's
      name and slug -> on success, `store.create_project` with name and
      optional description.
- [x] 2.2 Trigger `obsidian.sync_project_async` after creation; surface
      conflict / push_failed status to the user (same convention as the
      implicit-creation path).
- [x] 2.3 Reply with a short confirmation including the project's slug.
- [x] 2.4 Unit-test the handler with a mocked sync and a mocked session:
      successful create, collision (name, slug, alias), empty name, sync
      conflict.

## 3. Wiring
- [x] 3.1 Register `CommandHandler("new", handlers.new_project_command)` in
      `bot.py` alongside the other command handlers.
- [x] 3.2 Add `/new` to the `/help` command output with a one-line
      description.

## 4. Docs
- [x] 4.1 Add `/new` to the "Commands" section in `README.md` with both
      syntaxes (multi-line and dash-shorthand).

## 5. Validation
- [x] 5.1 Run `uv run pytest` - all new and existing tests pass.
- [x] 5.2 Run `openspec validate add-new-project-command --strict
      --no-interactive` and resolve any issues before marking the proposal
      ready.
