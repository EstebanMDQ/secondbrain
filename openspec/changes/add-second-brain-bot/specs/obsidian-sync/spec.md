## ADDED Requirements

### Requirement: Markdown File Generation
The system SHALL write one markdown file per project into a configurable
subfolder of the Obsidian vault directory. Files SHALL include YAML frontmatter
with project metadata and be compatible with Obsidian.

#### Scenario: Project file written
- **WHEN** a project is created or updated
- **THEN** the system SHALL write a markdown file at
  {OBSIDIAN_VAULT_PATH}/{OBSIDIAN_SUBFOLDER}/{project-slug}.md

#### Scenario: YAML frontmatter format
- **WHEN** a markdown file is generated
- **THEN** the file SHALL contain YAML frontmatter with name, status, stack,
  tags, and description fields

#### Scenario: Notes section
- **WHEN** a project has notes
- **THEN** the markdown file SHALL include a ## Notes section with each note
  as a bullet point

### Requirement: Git Sync
The system SHALL perform atomic git operations when syncing: pull first, then
write the file, commit, and push. All git operations SHALL run via
asyncio.to_thread to avoid blocking the event loop.

#### Scenario: Successful sync
- **WHEN** markdown files need to be synced
- **THEN** the system SHALL: git pull, write the file, git add, git commit,
  git push

#### Scenario: Git pull conflict
- **WHEN** git pull results in a merge conflict on a project file
- **THEN** the system SHALL abort the merge, save the new content as
  {project-slug}.conflict.md, and inform the user via Telegram that a
  conflict needs manual resolution

#### Scenario: Git push failure
- **WHEN** the git push fails for reasons other than a conflict
- **THEN** the system SHALL log the error and inform the user via Telegram
- **AND** the local commit SHALL be preserved for manual recovery

#### Scenario: Async git operations
- **WHEN** git operations are executed
- **THEN** the system SHALL run them via asyncio.to_thread to avoid blocking
  the event loop
