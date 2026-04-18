# Tasks: update-note-capture-protocol

## 1. Parser and fuzzy match
- [x] 1.1 Add a pure parser in `handlers.py` (or a small helper module)
      that returns `(selector: str, notes: list[str])` from a raw message
      per the rules in `design.md` - first non-empty line + paragraph-
      separated remainder; rejects single-line input by returning an
      empty notes list.
- [x] 1.2 Add `rapidfuzz` to `pyproject.toml` and `uv lock`.
- [x] 1.3 Implement `store.find_project_fuzzy(session, query, threshold)`
      using `rapidfuzz.process.extractOne` against the union of each
      project's name and aliases. Apply the 10-point runner-up gap rule;
      return None when ambiguous.
- [x] 1.4 Unit-test the parser and the fuzzy matcher (exact, typo, near
      miss, ambiguous, no match).

## 2. Handler rewrite
- [x] 2.1 Rewrite `handle_text_message` to: parse -> reject single-line ->
      exact match -> fuzzy match -> present create-confirmation if no
      match -> append notes and sync if matched.
- [x] 2.2 Drop the `ctx.ai_clients.categorize` call from the capture
      path. Keep the client available for discussion mode.
- [x] 2.3 Simplify the pending-confirmation payload stored in the state
      table to `{name, notes}`. Update
      `handle_confirmation_callback` to create a project with those two
      fields only (no AI-proposed metadata).
- [x] 2.4 Integration-test the handler end-to-end with a fake store:
      matched project, typo-matched project, new-project confirmation
      accept/reject, single-line rejection.

## 3. Obsidian writer
- [x] 3.1 Update `render_project_md` to render multi-line note strings
      with continuation-line indentation (2 spaces).
- [x] 3.2 Unit-test the writer for: single-line bullet, multi-line bullet,
      empty notes list.

## 4. Config
- [x] 4.1 Add `[capture]` section to `config.Settings`, `CaptureSettings`
      dataclass with `fuzzy_threshold: int = 85`.
- [x] 4.2 Document the section in `README.md` and the init wizard.
- [x] 4.3 Init wizard SHALL NOT prompt for it by default; it uses the
      hard-coded default unless the user edits the TOML.

## 5. Spec and documentation
- [x] 5.1 Rewrite the "Commands" / "Capturing notes" section of
      `README.md` with the new protocol, including an example.
- [x] 5.2 Mark `[ai.categorization]` as deprecated-but-legal in the
      README configuration reference.

## 6. Validation
- [x] 6.1 `uv run pytest` - all new and existing tests pass.
- [x] 6.2 `openspec validate update-note-capture-protocol --strict
      --no-interactive`.
