## MODIFIED Requirements

### Requirement: Categorization Prompt
The categorization AI tier SHALL NOT be invoked on the note-capture path.
Its configuration block (`[ai.categorization]` in the TOML config) MAY
remain present for forward compatibility but the system SHALL NOT call
the categorization model during capture. If a future capability reuses
the categorization tier (for example, an optional semantic-matching
fallback), that capability SHALL define its own prompt and invocation
rules in its own spec.

#### Scenario: Capture path does not call categorization AI
- **WHEN** the authorized user sends a plain text message outside
  discussion mode
- **THEN** the system SHALL parse the message using the line-based
  protocol defined in `note-capture` and SHALL NOT call the
  categorization model

#### Scenario: Categorization config block remains legal
- **WHEN** a user's TOML config contains a populated `[ai.categorization]`
  block
- **THEN** the system SHALL load it without error
- **AND** SHALL NOT treat it as required configuration for the capture
  path
