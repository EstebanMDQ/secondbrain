## ADDED Requirements

### Requirement: Python Package Distribution
The system SHALL be distributed as an installable Python package via PyPI. Users
SHALL be able to install it with `pip install secondbrain` or `uv tool install
secondbrain`. The package SHALL provide a `second-brain` CLI entry point.

#### Scenario: Install via pip
- **WHEN** a user runs `pip install secondbrain`
- **THEN** the `second-brain` CLI command SHALL be available in their PATH

#### Scenario: Install via uv
- **WHEN** a user runs `uv tool install secondbrain`
- **THEN** the `second-brain` CLI command SHALL be available in their PATH

### Requirement: Interactive Setup Wizard
The system SHALL provide a `second-brain init` command that interactively
configures the application on first run. The wizard SHALL prompt for required
settings and write a TOML config file.

#### Scenario: First-time init
- **WHEN** the user runs `second-brain init` with no existing config
- **THEN** the wizard SHALL prompt for: Telegram bot token, Telegram user ID,
  categorization AI settings (base URL, API key, model), discussion AI settings
  (base URL, API key, model), and Obsidian vault path
- **AND** validate that the vault path is a git repository with a configured
  remote (warn if not, allow the user to continue or fix)
- **AND** write the config to ~/.config/second-brain/config.toml
- **AND** create the data directory at ~/.local/share/second-brain/

#### Scenario: Re-init with existing config
- **WHEN** the user runs `second-brain init` with an existing config file
- **THEN** the wizard SHALL show current values as defaults
- **AND** allow the user to update individual settings

### Requirement: Configuration File
The system SHALL read configuration from a TOML file at
~/.config/second-brain/config.toml (or XDG_CONFIG_HOME/second-brain/config.toml).
Environment variables SHALL override config file values when present.

#### Scenario: Config file loaded
- **WHEN** the application starts
- **THEN** it SHALL read settings from the TOML config file
- **AND** apply any environment variable overrides on top

#### Scenario: Config file missing
- **WHEN** the application starts with no config file
- **THEN** it SHALL print an error directing the user to run `second-brain init`

#### Scenario: Environment variable override
- **WHEN** an environment variable like SECONDBRAIN_TELEGRAM_TOKEN is set
- **THEN** it SHALL override the corresponding config file value

### Requirement: Run Command
The system SHALL provide a `second-brain run` command that starts the Telegram
bot in the foreground. This is the primary way to run the service manually or
for debugging.

#### Scenario: Foreground run
- **WHEN** the user runs `second-brain run`
- **THEN** the bot SHALL start in the foreground with log output to stdout
- **AND** shut down gracefully on SIGINT/SIGTERM

#### Scenario: Log level configuration
- **WHEN** the user sets log_level in the config file or passes --log-level to run
- **THEN** the system SHALL use the specified log level (debug, info, warning, error)
- **AND** default to "info" if not specified

### Requirement: Service Installation
The system SHALL provide `second-brain install-service` and
`second-brain uninstall-service` commands to manage OS-level service integration.
Linux (systemd) SHALL be the primary target. macOS (launchd) SHALL be supported
as secondary.

#### Scenario: Install systemd service on Linux
- **WHEN** the user runs `second-brain install-service` on Linux
- **THEN** the system SHALL resolve the absolute path to the `second-brain`
  binary (via shutil.which or sys.executable) and embed it in the unit file
- **AND** generate a systemd user unit file at
  ~/.config/systemd/user/second-brain.service
- **AND** enable and start the service
- **AND** print instructions for checking status and enabling lingering

#### Scenario: Install launchd service on macOS
- **WHEN** the user runs `second-brain install-service` on macOS
- **THEN** the system SHALL resolve the absolute path to the `second-brain`
  binary and embed it in the plist
- **AND** generate a launchd plist at
  ~/Library/LaunchAgents/com.secondbrain.bot.plist
- **AND** load and start the service

#### Scenario: Uninstall service
- **WHEN** the user runs `second-brain uninstall-service`
- **THEN** the system SHALL stop the service, disable it, and remove the
  service file

#### Scenario: Unsupported OS
- **WHEN** the user runs `second-brain install-service` on an unsupported OS
- **THEN** the system SHALL print an error with instructions to use
  `second-brain run` manually or set up a custom service

### Requirement: XDG-Compliant Data Storage
The system SHALL store data files following XDG Base Directory conventions.
The SQLite database SHALL be stored at
~/.local/share/second-brain/brain.db (or XDG_DATA_HOME/second-brain/brain.db).

#### Scenario: Default data directory
- **WHEN** XDG_DATA_HOME is not set
- **THEN** the SQLite database SHALL be at ~/.local/share/second-brain/brain.db

#### Scenario: Custom XDG_DATA_HOME
- **WHEN** XDG_DATA_HOME is set to a custom path
- **THEN** the SQLite database SHALL be at $XDG_DATA_HOME/second-brain/brain.db

### Requirement: Status Command
The system SHALL provide a `second-brain status` command that shows the current
state: whether the service is running, config file location, database path,
vault path, and number of projects stored.

#### Scenario: Status when running
- **WHEN** the user runs `second-brain status` while the service is active
- **THEN** the system SHALL show service status, config path, DB path, vault
  path, and project count

#### Scenario: Status when not running
- **WHEN** the user runs `second-brain status` while the service is stopped
- **THEN** the system SHALL indicate the service is not running and show
  config path

### Requirement: Docker Support (Optional)
The system SHALL include a Dockerfile and docker-compose.yml for users who
prefer containerized deployment. This is a secondary deployment path; the
primary method is the native Python package.

#### Scenario: Docker deployment
- **WHEN** a user runs `docker compose up -d`
- **THEN** the bot SHALL start with configuration from environment variables
  or a mounted config file
