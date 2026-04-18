## MODIFIED Requirements

### Requirement: Message Intake
The system SHALL accept text messages from the authorized Telegram user and
parse them according to a deterministic line-based protocol: the first
non-empty line is the project selector; each subsequent paragraph
(separated by blank lines) is a note bullet. Messages SHALL NOT be sent to
a categorization AI on the capture path.

#### Scenario: Authorized user sends a multi-line note
- **WHEN** the authorized user sends a text message with more than one
  non-empty line
- **THEN** the system SHALL use the first non-empty line as the project
  selector
- **AND** each subsequent non-empty paragraph SHALL become a note bullet

#### Scenario: Authorized user sends a single-line message
- **WHEN** the authorized user sends a text message with only one
  non-empty line and no subsequent notes
- **THEN** the system SHALL reply with a usage hint explaining the
  protocol (project on line 1, notes on subsequent lines)
- **AND** the system SHALL NOT create or modify any project

#### Scenario: Unauthorized user sends a message
- **WHEN** a user whose Telegram ID does not match ALLOWED_USER_ID sends a
  message
- **THEN** the system SHALL ignore the message and not respond

### Requirement: Intent Routing
The system SHALL route messages based on explicit state only: the `/chat`
command enters discussion mode; plain text messages outside discussion
mode are always treated as notes. The system SHALL NOT use an AI to
classify message intent on the capture path.

#### Scenario: Plain text message outside discussion mode
- **WHEN** the authorized user sends a text message while not in
  discussion mode
- **THEN** the system SHALL treat the message as a note per the line-based
  protocol

#### Scenario: User forces discussion mode
- **WHEN** the user sends the /chat command
- **THEN** subsequent messages SHALL be routed to the discussion model
- **AND** bypass note parsing until the discussion ends

#### Scenario: Already in discussion mode
- **WHEN** the user sends a message while discussion mode is active
- **THEN** the system SHALL route it directly to the discussion model
- **AND** skip note parsing entirely

### Requirement: Project Matching
The system SHALL resolve the project selector against the project store
using exact match first (by slug, case-insensitive name, or
case-insensitive alias), then a fuzzy matcher with a configurable
threshold. Ambiguous fuzzy matches (runner-up score within 10 points of
the top score) SHALL be treated as no match.

#### Scenario: Exact match by name
- **WHEN** the selector equals an existing project name (case-insensitive)
- **THEN** the system SHALL route the note to that project

#### Scenario: Exact match by alias or slug
- **WHEN** the selector equals an existing project's slug or any of its
  aliases (case-insensitive)
- **THEN** the system SHALL route the note to that project

#### Scenario: Typo-tolerant fuzzy match
- **WHEN** the selector does not exactly match any project but rapidfuzz
  scores one project at or above the configured `fuzzy_threshold` AND the
  runner-up is at least 10 points lower
- **THEN** the system SHALL route the note to the top-scoring project

#### Scenario: Ambiguous fuzzy match
- **WHEN** the selector's top fuzzy score is within 10 points of the
  runner-up
- **THEN** the system SHALL NOT pick either project
- **AND** SHALL fall through to the no-match flow

#### Scenario: No match
- **WHEN** no project matches exactly or via fuzzy
- **THEN** the system SHALL prompt the user with a yes/no inline keyboard
  offering to create a new project with the selector as its name

### Requirement: New Project Detection
The system SHALL detect when a message's project selector does not match
any existing project and offer to create an empty project with that
selector as its name. The system SHALL NOT propose or extract
description, stack, tags, or status from the message content; those
fields are settable via `/new <name>\n<description>` or future edit
commands.

#### Scenario: First line does not match any project
- **WHEN** the selector has no exact or fuzzy match
- **THEN** the system SHALL present an inline keyboard asking
  "Create '<selector>'?" with Yes/No buttons

#### Scenario: User confirms new project
- **WHEN** the user confirms the creation
- **THEN** the system SHALL create a project with the selector as `name`
  and the parsed notes as initial notes
- **AND** trigger an Obsidian sync

#### Scenario: User rejects new project
- **WHEN** the user declines
- **THEN** the system SHALL discard the parsed notes and the creation
  prompt

### Requirement: Note Deduplication
The system SHALL deduplicate notes on upsert by case-insensitive string
match (after stripping leading/trailing whitespace) against existing
notes for the same project.

#### Scenario: Duplicate note (case-insensitive)
- **WHEN** a note matches an existing note after lowercasing and
  stripping whitespace
- **THEN** the system SHALL skip the insert and not create a duplicate

#### Scenario: Unique note
- **WHEN** a note does not match any existing note for the target project
- **THEN** the system SHALL append it to the project's notes list
