## MODIFIED Requirements

### Requirement: Markdown File Generation
The system SHALL write one markdown file per project into a configurable
subfolder of the Obsidian vault directory. Files SHALL include YAML
frontmatter with project metadata and be compatible with Obsidian. Note
bullets SHALL render correctly for multi-line note strings by indenting
continuation lines two spaces under the bullet marker.

#### Scenario: Project file written
- **WHEN** a project is created or updated
- **THEN** the system SHALL write a markdown file at
  {OBSIDIAN_VAULT_PATH}/{OBSIDIAN_SUBFOLDER}/{project-slug}.md

#### Scenario: YAML frontmatter format
- **WHEN** a markdown file is generated
- **THEN** the file SHALL contain YAML frontmatter with name, status,
  stack, tags, and description fields

#### Scenario: Single-line note bullet
- **WHEN** a project has a note containing no newlines
- **THEN** the markdown SHALL render the note as `- <text>` under the
  `## Notes` heading

#### Scenario: Multi-line note bullet
- **WHEN** a project has a note whose value contains one or more
  newlines
- **THEN** the markdown SHALL render the first line as `- <first line>`
  and each continuation line as `  <line>` (two-space indent) so the
  rendered output is a single bullet with multi-line content

#### Scenario: Empty notes list
- **WHEN** a project has no notes
- **THEN** the markdown SHALL omit the `## Notes` heading entirely
