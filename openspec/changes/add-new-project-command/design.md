# Design: /new slash command

## Context

The bot's existing project-creation path is AI-mediated: user types a note, AI
infers project metadata, user confirms via inline keyboard. That is the right
shape for *capturing ideas*, but the wrong shape for *registering a project*
the user already has in mind. A dedicated command avoids an AI round-trip
and removes the ambiguity of "did the AI pick the right project?".

## Goals / Non-Goals

- Goals
  - Single message, immediate, deterministic project creation.
  - Zero AI calls.
  - Collision detection that matches the store's alias/slug semantics so the
    user cannot create two projects that look the same to the matcher.
  - Description optional; stack/tags/status not settable from this command
    (the bot can learn those later via regular notes or a future edit
    command).

- Non-Goals
  - Multi-field edits (stack, tags, status). Covered by future commands.
  - Project deletion or renaming.
  - Batch creation or import. The existing `import-vault` CLI command covers
    bulk ingestion from the vault.

## Decisions

### Argument parsing

Accept the payload in one of three forms (evaluated in order):

1. **Multi-line:** first line is the name, remaining lines joined with
   newlines form the description.
   ```
   /new My Project
   A longer description
   on multiple lines.
   ```

2. **Dash-shorthand (single line):** name and description separated by the
   literal ` - ` (space-dash-space). Only the first occurrence splits.
   ```
   /new My Project - A one-line description
   ```

3. **Name only:** the entire argument is the name.
   ```
   /new My Project
   ```

Precedence: if a newline is present anywhere in the payload, form (1) wins,
even if the first line contains ` - `. This keeps the multi-line flow
unambiguous and lets project names include hyphens freely.

- Alternatives considered
  - *Interactive wizard (bot asks for name, then description)*: rejected.
    Adds state, breaks the "one message in, one reply out" convention shared
    by `/project` and `/export`.
  - *Custom delimiter such as `|`*: rejected. Less discoverable than ` - ` or
    newline; harder to type on mobile.
  - *Frontmatter-style key/value*: rejected. Overkill for two fields.

### Collision check

Use `store.get_project(session, name)` which already resolves by slug, name,
or alias (case-insensitive). If it returns a project, reject the creation
with a message that names the existing project and its slug so the user
knows what they collided with.

The check is intentionally wider than name equality: `/new foo` must fail
when a project named `Foo` exists, or when some other project has `foo` as
an alias. This matches how the categorization path dedups.

### Creation and sync

On success, call `store.create_project(session, name=..., description=...)`
with only the fields the user supplied. All other fields default (empty
lists, `None` status). Then call `obsidian.sync_project_async` on the
created row so the vault file appears immediately.

If the sync reports a conflict or push failure, surface the message to the
user but keep the DB row (mirrors the existing handler behavior for
implicit creation).

## Risks / Trade-offs

- **Hyphens in names collide with dash-shorthand.** A user who types
  `/new part-a - a thing` on one line will get name `part-a` and description
  `a thing`, which is what they wanted. A user who types `/new part - a`
  meaning "a project called `part - a`" will get name `part` and description
  `a`. Mitigation: document the dash-shorthand, and tell users to use the
  multi-line form when the name contains ` - `.

- **No description validation.** We accept any text, including markdown and
  multiline. That matches how descriptions work elsewhere in the bot.

## Migration Plan

Pure addition - no migration. The DB schema already holds `description`.
Existing projects are unaffected.

## Open Questions

None outstanding.
