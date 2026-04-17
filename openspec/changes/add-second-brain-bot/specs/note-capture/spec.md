## ADDED Requirements

### Requirement: Message Intake
The system SHALL accept text messages from the authorized Telegram user and
forward them to the categorization AI for project classification and intent
detection.

#### Scenario: Authorized user sends a note
- **WHEN** the authorized user sends a text message to the bot
- **THEN** the system SHALL pass the message to the categorization model
- **AND** the categorization model SHALL classify intent (note vs question)
- **AND** extract structured project data if intent is note

#### Scenario: Unauthorized user sends a message
- **WHEN** a user whose Telegram ID does not match ALLOWED_USER_ID sends a message
- **THEN** the system SHALL ignore the message and not respond

### Requirement: Intent Routing
The system SHALL route messages based on AI-classified intent. Notes are
upserted to the project store. Questions are routed to the discussion model.
The /chat command SHALL force discussion mode regardless of AI classification.

#### Scenario: AI classifies message as a note
- **WHEN** the categorization model classifies a message as a note
- **THEN** the system SHALL upsert the extracted data into the project store
- **AND** trigger an Obsidian sync
- **AND** reply with a confirmation

#### Scenario: AI classifies message as a question
- **WHEN** the categorization model classifies a message as a question
- **THEN** the system SHALL route the message to the discussion model
- **AND** reply with the discussion model's response

#### Scenario: User forces discussion mode
- **WHEN** the user sends the /chat command
- **THEN** subsequent messages SHALL be routed to the discussion model
- **AND** bypass categorization until the discussion ends

#### Scenario: Already in discussion mode
- **WHEN** the user sends a message while discussion mode is active
- **THEN** the system SHALL route it directly to the discussion model
- **AND** skip categorization entirely

### Requirement: New Project Detection
The system SHALL detect when a message refers to a project that does not yet
exist and ask the user for confirmation before creating it.

#### Scenario: AI identifies a new project
- **WHEN** the categorization model infers a project name not in the store
- **THEN** the system SHALL present the extracted project details
- **AND** ask the user to confirm creation via inline keyboard (yes/no)

#### Scenario: User confirms new project
- **WHEN** the user confirms the new project creation
- **THEN** the system SHALL create the project in the store with the extracted data
- **AND** trigger an Obsidian sync

#### Scenario: User rejects new project
- **WHEN** the user declines the new project creation
- **THEN** the system SHALL discard the extraction and inform the user

### Requirement: Note Deduplication
The system SHALL deduplicate notes on upsert by case-insensitive string match
(after stripping leading/trailing whitespace) against existing notes for the
same project.

#### Scenario: Duplicate note (case-insensitive)
- **WHEN** a note matches an existing note after lowercasing and stripping whitespace
- **THEN** the system SHALL skip the insert and not create a duplicate

#### Scenario: Unique note
- **WHEN** a note does not match any existing note for the target project
- **THEN** the system SHALL append it to the project's notes list
