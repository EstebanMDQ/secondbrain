# Design: line-based note capture with fuzzy project matching

## Context

The bot captures ideas by chatting naturally in Telegram. The initial design
delegated project classification and field extraction to a cheap
"categorization" AI tier. In practice this makes the system's behavior a
function of the model's quality on any given input, and small local models
(qwen2.5:3b, llama3.2:3b) routinely hallucinate: they rewrite the project
`name` field, omit notes, or invent stack/tags that do not match the
message.

Today's failure, reported by the user: sending `Project TODO Agregar buff
al equipaje` produced a DB row with `slug=todo`, `name="agregar buff al
equipaje"`, `notes=[]`. The actual note content was silently lost and the
canonical project name was clobbered.

Upgrading the model (Gemini, GPT-4o) reduces the rate but does not remove
the class of failure, and it moves a per-message operation from free/local
to metered/remote. For a personal project tracker with one user and a
handful of projects, the cost is paid over and over for work that is
fundamentally string matching.

## Goals / Non-Goals

- Goals
  - Deterministic, predictable behavior: the same message always produces
    the same output.
  - Zero AI calls on the capture path by default.
  - Typo tolerance on project names ("facturaabot" -> "facturabot").
  - Preserve the existing `## Notes` bullet shape and sync-to-vault
    contract.
  - BREAKING change is acceptable - the existing single-line capture flow
    is known-broken and has only been used by the author.

- Non-Goals
  - Extracting stack, tags, or status from free text. Those are fillable
    via `/new <name>\n<description>` today; a future `/edit` command can
    handle the rest.
  - Fuzzy matching for semantic synonyms ("the invoice bot" ->
    "facturabot"). Outside the scope of rapidfuzz. If that becomes
    important, re-add the categorization AI as an opt-in fallback in a
    separate change.
  - AI-classified question detection. Users enter discussion mode via
    `/chat` explicitly.

## Decisions

### Capture protocol

For any plain text message not in discussion mode:

1. Split the message on `\n`. Drop leading/trailing empty lines.
2. The first remaining non-empty line is the **project selector**.
3. Subsequent lines, grouped by blank-line separators, are **note
   paragraphs**. Each paragraph becomes one bullet under `## Notes`.
   Within a paragraph, newlines are preserved and rendered with
   continuation-line indentation.
4. A message with only a project selector and no notes is rejected with
   "send project on line 1, notes on the next lines." This prevents silent
   "created empty project and did nothing" outcomes.

Example:

```
morning-news
Fix RSS dedupe - currently drops items that share a title but differ in URL.
Also: bump feed health jsonl to include HTTP status.
```

-> project match "morning-news" + two note bullets.

### Project matching

Evaluation order:

1. **Exact match** via `store.get_project` (slug, case-insensitive name,
   case-insensitive alias). Already implemented.
2. **Fuzzy match** via `rapidfuzz.process.extractOne` against the union of
   each project's name and aliases. If the top score >= `fuzzy_threshold`
   (default 85) **and** the runner-up is at least 10 points lower (to
   avoid ambiguity between similar names), return that project.
3. **No match**: show "Create 'X'? [Yes/No]" inline keyboard. On Yes,
   create an empty project with `name = selector` (reusing the existing
   new-project flow, minus the AI-proposed metadata).

`fuzzy_threshold` lives under `[discussion]` in the config... actually
better: under a new `[capture]` section so it is clearly about the capture
path, not discussion. Default keeps the bot working out of the box.

- Alternatives considered
  - *AI semantic match:* rejected for this change. Too expensive per
    message for marginal value when the user controls the selector.
    Re-introducible as a fallback later if warranted.
  - *Exact match only:* rejected. "facturaabot" should map cleanly to
    "facturabot"; a small fuzzy layer is cheap and eliminates a whole
    class of frustration.

### Multi-line note rendering

The writer currently emits `- {note}\n`. For a multi-line note this
produces broken markdown:

```
- Line one
Line two
```

Change to indent continuation lines by 2 spaces so they belong to the
bullet:

```
- Line one
  Line two
```

This matches standard markdown rendering and Obsidian's live-preview
behavior.

### Removal of AI categorization path

The `handle_text_message` handler no longer calls
`ai_clients.categorize`. `ai.build_categorization_prompt` and the client's
`categorize` method can stay as dead code for one cycle to avoid churn,
then be removed in a follow-up cleanup change once no callers remain.

The config's `[ai.categorization]` block stays legal to reduce migration
pain for existing users. It is now pure forward-compat and does nothing on
capture. Documented as deprecated in the README.

### `/chat` and discussion mode

Unaffected. `STATE_DISCUSSION_MODE` still short-circuits the capture path
into `_handle_discussion_turn`. Users who want to brainstorm freely use
`/chat`.

### New-project confirmation shape

The existing callback payload shape is `{intent, project_slug, name,
description, stack, tags, status, notes}`. Under the new protocol, the
payload becomes `{name, notes}` - just the selector and the parsed notes.
The `handle_confirmation_callback` function updates to create a project
with those two fields only.

## Risks / Trade-offs

- **UX shift.** Users who were used to sending a stream-of-consciousness
  message and getting stack/tags/status auto-extracted will see that stop
  working. Mitigated by: the feature rarely worked reliably; users can
  fill those in via `/new`; and the change is BREAKING so it will be
  called out in commit + README.

- **rapidfuzz is a new dependency.** Small (pure-Python fallback with
  C acceleration), widely used, MIT-licensed. Acceptable footprint.

- **Loss of natural phrasing.** "A message about morning-news: fix dedupe"
  no longer works. User has to write it on two lines. Explicit > clever
  for a personal tool.

- **Ambiguous fuzzy matches.** "factura" could match "facturabot" at
  score ~90. The 10-point runner-up gap rule mitigates; if the user has
  both "facturabot" and "factura-other", ambiguity triggers the
  no-match flow and the user picks explicitly.

## Migration Plan

1. Ship behind no feature flag - the old AI path is already known-broken
   in the field.
2. Call out BREAKING in the commit and README.
3. Follow-up cleanup change removes `ai.build_categorization_prompt` and
   `AIClients.categorize` once no other callers need them.
4. Users do not need to touch their config; `[ai.categorization]` stays
   legal but unused.

## Open Questions

- Should the fuzzy threshold be per-user (config) or fixed (in code)?
  Default to config for flexibility, but hard-code a sensible default so
  most users never change it.
- Should `find_project_fuzzy` also include `description` in the haystack?
  No - description is prose, not an identifier. Keep the haystack to
  name + aliases.
