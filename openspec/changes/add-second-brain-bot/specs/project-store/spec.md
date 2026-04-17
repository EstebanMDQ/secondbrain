## ADDED Requirements

### Requirement: Project Schema
The system SHALL store projects in SQLite via SQLAlchemy with the following
fields: id (slug, primary key), name (string), description (string),
stack (string), tags (JSON list), status (enum: idea, in-progress, paused,
shipped), notes (JSON list of strings), and aliases (JSON list of strings).

#### Scenario: Project creation
- **WHEN** a new project is created
- **THEN** the system SHALL persist all structured fields to the SQLite database
- **AND** the id SHALL be a URL-safe slug derived from the project name

#### Scenario: Tags stored as JSON
- **WHEN** a project is created or updated with tags
- **THEN** the tags SHALL be stored as a JSON array in a single column

#### Scenario: Notes stored as JSON
- **WHEN** a project is created or updated with notes
- **THEN** the notes SHALL be stored as a JSON array of strings in a single column

### Requirement: Project Aliases
The system SHALL maintain a list of aliases (alternative names) for each project.
The AI categorization prompt SHALL include aliases when listing known projects so
the model can match a project even when the user refers to it by a different name.

#### Scenario: Alias added on creation
- **WHEN** a new project is created with name "My Auth Service"
- **THEN** the system SHALL store "My Auth Service" as the first alias

#### Scenario: AI uses a different name for existing project
- **WHEN** the AI matches a message to an existing project using a name not
  in the aliases list
- **THEN** the system SHALL add the new name to the aliases list

#### Scenario: Project lookup by alias
- **WHEN** a user references a project by any of its aliases
- **THEN** the system SHALL resolve it to the correct project

### Requirement: Slug Collision Handling
The system SHALL detect when a new project's slug collides with an existing one
and ask the user to choose a different name.

#### Scenario: Slug collision on creation
- **WHEN** a new project would produce a slug that already exists
- **THEN** the system SHALL inform the user of the conflict
- **AND** ask for an alternative name via Telegram

### Requirement: Schema Initialization
The system SHALL create database tables on startup using SQLAlchemy create_all.
No migration framework SHALL be used.

#### Scenario: First startup
- **WHEN** the application starts and no database file exists
- **THEN** the system SHALL create the SQLite file and all tables

#### Scenario: Subsequent startup
- **WHEN** the application starts and the database already exists
- **THEN** the system SHALL reuse the existing database without data loss

### Requirement: Project CRUD
The system SHALL support creating, reading, updating, and listing projects.

#### Scenario: Create project
- **WHEN** a new project is created with extracted data
- **THEN** the system SHALL insert a new row with all provided fields
- **AND** default status to "idea" if not specified

#### Scenario: Update project fields
- **WHEN** the AI extracts updated information for an existing project
- **THEN** the system SHALL merge new data into the existing record
- **AND** append new notes (respecting deduplication)
- **AND** only update fields that are present in the AI response (omitted
  fields mean no change; explicit null clears the field)

#### Scenario: List all projects
- **WHEN** a project listing is requested
- **THEN** the system SHALL return all projects with name and status

#### Scenario: Get project by name, slug, or alias
- **WHEN** a specific project is requested by name, slug, or alias
- **THEN** the system SHALL return the full project record with all fields
