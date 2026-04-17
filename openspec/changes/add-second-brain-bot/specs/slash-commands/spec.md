## ADDED Requirements

### Requirement: Start Command
The system SHALL respond to /start with a welcome message explaining what the
bot does and how to use it. The welcome message SHALL only be sent on first use;
subsequent /start calls SHALL reply with a short acknowledgment.

#### Scenario: First time /start
- **WHEN** the user sends /start for the first time
- **THEN** the system SHALL send a welcome message with usage instructions

#### Scenario: Subsequent /start
- **WHEN** the user sends /start again
- **THEN** the system SHALL reply with a short acknowledgment

### Requirement: Help Command
The system SHALL respond to /help with a list of available commands and brief
descriptions.

#### Scenario: Help requested
- **WHEN** the user sends /help
- **THEN** the system SHALL display all available commands with descriptions

### Requirement: List Projects Command
The system SHALL respond to /projects with a list of all projects showing
name and status.

#### Scenario: Projects exist
- **WHEN** the user sends /projects and projects exist in the store
- **THEN** the system SHALL display each project's name and status

#### Scenario: No projects
- **WHEN** the user sends /projects and the store is empty
- **THEN** the system SHALL inform the user that no projects exist

### Requirement: Project Detail Command
The system SHALL respond to /project <name> with full project details including
description, stack, tags, status, aliases, and notes.

#### Scenario: Valid project name
- **WHEN** the user sends /project with a valid project name, slug, or alias
- **THEN** the system SHALL display all stored fields for that project

#### Scenario: Unknown project
- **WHEN** the user sends /project with an unrecognized name
- **THEN** the system SHALL inform the user the project was not found

### Requirement: Export Command
The system SHALL respond to /export <name> by sending the project's markdown
file as a Telegram document attachment.

#### Scenario: Export existing project
- **WHEN** the user sends /export with a valid project name
- **THEN** the system SHALL send the corresponding .md file as a Telegram document

#### Scenario: Export unknown project
- **WHEN** the user sends /export with an unrecognized project name
- **THEN** the system SHALL inform the user the project was not found

### Requirement: Clear Command
The system SHALL respond to /clear by asking for confirmation, then wiping the
in-memory conversation context if confirmed. Projects and notes are NOT affected.

#### Scenario: User confirms clear
- **WHEN** the user sends /clear and confirms via inline keyboard
- **THEN** the system SHALL wipe the in-memory conversation context (messages
  and rolling summary) and the persisted discussion state in SQLite
- **AND** exit discussion mode if active
- **AND** inform the user that the conversation context was cleared

#### Scenario: User cancels clear
- **WHEN** the user sends /clear and declines
- **THEN** the system SHALL keep the conversation context intact

### Requirement: Chat Command
The system SHALL respond to /chat by entering discussion mode, routing
subsequent messages to the discussion model instead of the categorization model.

#### Scenario: Enter discussion mode
- **WHEN** the user sends /chat
- **THEN** the system SHALL enter discussion mode
- **AND** inform the user they are now in discussion mode

### Requirement: Save Command
The system SHALL respond to /save by summarizing the current discussion and
appending the summary to a project's notes.

#### Scenario: Save with active discussion
- **WHEN** the user sends /save while a discussion is active
- **THEN** the system SHALL use the discussion model to summarize the conversation
- **AND** ask the user to confirm the target project
- **AND** append the summary to the project's notes
- **AND** trigger an Obsidian sync

#### Scenario: Save with no discussion
- **WHEN** the user sends /save with no active discussion
- **THEN** the system SHALL inform the user there is nothing to save
