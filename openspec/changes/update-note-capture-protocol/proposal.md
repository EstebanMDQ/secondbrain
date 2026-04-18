# Change: Replace AI-driven note capture with an explicit line-based protocol

## Why

The bot's current capture flow hands the raw message to a cheap categorization
model and expects a structured JSON payload (intent, project_slug, name,
description, stack, tags, status, notes). In practice, small local models
(qwen2.5:3b) regularly hallucinate fields - most damagingly, they rewrite
`name` with whatever noun phrase looks title-cased, silently clobbering an
existing project's canonical name and dropping the actual note content on
the floor. A larger model makes the problem rarer but does not remove it,
and every captured message pays tokens for work that is mostly pattern
matching.

A line-based protocol trades away natural-language capture for determinism:
the first line of a message names the project, each subsequent line is a
note bullet. Matching a user-typed project name against the project store
is a job for a fuzzy matcher (rapidfuzz), not a language model. The result
is predictable, cheap, typo-tolerant, and immune to hallucination.

## What Changes

- **BREAKING**: plain text messages are parsed, not categorized by an AI.
  - The first non-empty line is the project selector.
  - Each subsequent non-empty line becomes one bullet under `## Notes`.
  - Blank lines separate paragraphs within a single bullet.
  - Single-line messages (no newline) are rejected with a usage hint.
- **BREAKING**: project matching on capture uses exact name / slug / alias,
  then rapidfuzz fallback above a configurable threshold (default 85).
  The categorization AI is no longer invoked on the capture path.
- **BREAKING**: intent classification ("note" vs "question") is removed.
  `/chat` remains the only way to enter discussion mode. Messages sent
  outside discussion mode are always treated as notes.
- **BREAKING**: the AI-driven new-project confirmation flow loses its
  AI-proposed metadata (description/stack/tags/status). When the first
  line does not match any project, the bot offers to create an empty
  project with just that name. Metadata is filled in later via `/new
  <name>\n<description>` or a future edit command.
- Obsidian writer renders multi-line note bullets correctly: continuation
  lines are indented two spaces under the bullet.
- `ai-provider`: the categorization tier becomes optional infrastructure.
  The config block stays (forward compatibility), but the bot no longer
  calls the categorization model during capture.

## Impact

- Affected specs:
  - `note-capture` (MODIFIED: Message Intake, Intent Routing, New Project
    Detection; Note Deduplication kept as-is)
  - `ai-provider` (MODIFIED: Categorization Prompt requirement - scoped
    down or removed; OpenAI-Compatible Client requirement kept)
  - `obsidian-sync` (MODIFIED: Notes section rendering for multi-line
    bullets)
- Affected code:
  - `src/secondbrain/handlers.py` - rewrite `handle_text_message`; drop
    categorization call; add line parser and fuzzy matcher call.
  - `src/secondbrain/ai.py` - remove `build_categorization_prompt` and
    the `categorize` client method (or keep as dead code pending cleanup
    change).
  - `src/secondbrain/store.py` - add `find_project_fuzzy` helper using
    rapidfuzz against name+slug+aliases.
  - `src/secondbrain/obsidian.py` - update `render_project_md` to handle
    multi-line note strings (indent continuation lines).
  - `pyproject.toml` - add `rapidfuzz` dependency.
  - Tests: rewrite `tests/test_handlers.py` capture flow; add
    `tests/test_fuzzy_match.py`; update `tests/test_obsidian.py` for the
    multi-line bullet rendering.
  - `README.md` - document the capture protocol under usage.
