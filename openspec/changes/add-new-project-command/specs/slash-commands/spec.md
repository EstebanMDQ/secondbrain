## ADDED Requirements

### Requirement: New Project Command
The system SHALL respond to `/new <name>` by creating a new project in the
store with the given name and no other fields populated. The system SHALL
optionally accept a description provided either on subsequent lines of the
same message or after a ` - ` (space-dash-space) separator on the first
line. If a newline is present anywhere in the argument, the multi-line form
SHALL take precedence over the dash-shorthand form. The system SHALL reject
the command when the name collides (case-insensitive) with an existing
project's name, slug, or alias, replying with the colliding project's name
and slug. The system SHALL NOT call the categorization AI, SHALL NOT enter
discussion mode, and SHALL NOT start a confirmation flow. On successful
creation, the system SHALL sync the new project to the Obsidian vault and
reply to the user with a short confirmation including the new project's
slug.

#### Scenario: Create project with only a name
- **WHEN** the user sends `/new My Project` and no project named "My Project"
  (or any case variant), slug "my-project", or alias matching that name
  exists
- **THEN** the system SHALL create a project with name "My Project" and no
  description
- **AND** the system SHALL sync the project file to the vault
- **AND** the system SHALL reply with a confirmation mentioning the new
  slug

#### Scenario: Create project with description on subsequent lines
- **WHEN** the user sends a multi-line message whose first line is
  `/new My Project` and subsequent lines contain description text
- **THEN** the system SHALL use the first line (after the command token)
  as the name and the remaining lines (joined with newlines) as the
  description

#### Scenario: Create project with dash-shorthand description
- **WHEN** the user sends `/new My Project - A short description` on a
  single line
- **THEN** the system SHALL use "My Project" as the name and "A short
  description" as the description

#### Scenario: Multi-line form wins over dash-shorthand
- **WHEN** the user sends a multi-line message whose first line is
  `/new name - not a description` and a second line contains "real
  description"
- **THEN** the system SHALL use "name - not a description" as the name and
  "real description" as the description

#### Scenario: Reject collision with an existing project name
- **WHEN** the user sends `/new Foo` and a project named "foo" (any case
  variant) already exists
- **THEN** the system SHALL NOT create a new project
- **AND** the system SHALL reply with an error that names the existing
  project and its slug

#### Scenario: Reject collision with an existing alias
- **WHEN** the user sends `/new Foo` and some project has "foo" registered
  as an alias
- **THEN** the system SHALL NOT create a new project
- **AND** the system SHALL reply with an error that names the project that
  owns the alias and its slug

#### Scenario: Reject empty name
- **WHEN** the user sends `/new` or `/new    ` (whitespace only)
- **THEN** the system SHALL NOT create a project
- **AND** the system SHALL reply with a usage hint

#### Scenario: Command does not trigger categorization or discussion mode
- **WHEN** the user sends `/new <name>` while not in discussion mode
- **THEN** the system SHALL NOT call the categorization AI
- **AND** the system SHALL NOT enter discussion mode

#### Scenario: Help output includes /new
- **WHEN** the user sends /help
- **THEN** the response SHALL mention `/new` as the command for creating a
  project by name with an optional description
