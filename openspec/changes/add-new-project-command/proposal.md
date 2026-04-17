# Change: Add /new slash command for explicit project creation

## Why

Today, projects are only created implicitly: the user sends a note, the
categorization AI proposes a project, and the user accepts via inline keyboard.
That round-trip is wasteful when the user simply wants to register a project
name (and optionally a short description) without having any content to
categorize yet. It also burns AI tokens for a deterministic operation.

A dedicated `/new` command gives the user direct, AI-free control over
project creation, mirroring the explicit feel of `/projects`, `/project`, and
`/export`.

## What Changes

- Add `/new <name>` slash command that creates a project with just a name.
- Accept an optional description in the same message (newline-delimited, or
  `<name> - <description>` single-line shorthand).
- Reject names that collide with any existing project name, slug, or alias
  (case-insensitive) with a clear error message referencing the colliding
  project.
- Do NOT invoke the categorization AI, do NOT enter discussion mode, and do
  NOT start a confirmation flow - creation is immediate on valid input.
- Sync the new project to the Obsidian vault immediately (same path as
  implicit creation).
- Update `/help` output to include `/new`.

## Impact

- Affected specs: `slash-commands`
- Affected code:
  - `src/secondbrain/handlers.py` - new `new_project_command` handler and
    argument parser
  - `src/secondbrain/bot.py` - register `CommandHandler("new", ...)`
  - `tests/test_commands.py` - unit tests for parsing and collision behavior
  - `README.md` - document the command under "Commands"
