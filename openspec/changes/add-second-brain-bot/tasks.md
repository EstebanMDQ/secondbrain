# Tasks: add-second-brain-bot

## 1. Project Scaffold
- [ ] 1.1 Initialize Python project with uv, src layout (pyproject.toml with entry points)
- [ ] 1.2 Create src/secondbrain/ package structure (cli.py, bot.py, handlers.py, ai.py, store.py, obsidian.py, discussion.py, config.py, service.py)
- [ ] 1.3 Configure pyproject.toml: package metadata, dependencies, `[project.scripts]` entry point for `second-brain` CLI
- [ ] 1.4 Create Dockerfile and docker-compose.yml (optional deployment path)
- [ ] 1.5 Add LICENSE file

## 2. CLI and Configuration
- [ ] 2.1 Implement cli.py with click: `second-brain init`, `run`, `install-service`, `uninstall-service`, `status`
- [x] 2.2 Implement config.py: load TOML config from ~/.config/second-brain/config.toml, env var overrides (SECONDBRAIN_ prefix)
- [ ] 2.3 Implement `second-brain init` interactive wizard (prompt for all settings, validate vault is a git repo with remote, write config.toml, create data dir)
- [x] 2.4 Validate config on startup, fail fast with clear error messages
- [x] 2.5 Write unit test: config loading, env var override, missing config error

## 3. Service Installation
- [x] 3.1 Implement service.py: detect OS (Linux/macOS)
- [x] 3.2 Implement systemd user unit generation and install/uninstall (Linux)
- [x] 3.3 Implement launchd plist generation and load/unload (macOS)
- [x] 3.4 Implement `second-brain status` command (service state, config path, DB path, project count)

## 4. Project Store (SQLite)
- [x] 4.1 Define SQLAlchemy model for Project (id, name, description, stack, tags, status, notes, aliases)
- [x] 4.2 Add state table for discussion mode flag, rolling summary, and pending confirmations
- [x] 4.3 Implement create_all initialization (DB at XDG_DATA_HOME/second-brain/brain.db)
- [x] 4.4 Implement CRUD: create_project, get_project, update_project, list_projects
- [x] 4.5 Implement project lookup by name, slug, or alias
- [x] 4.6 Implement alias management (add alias on new name match)
- [x] 4.7 Implement slug collision detection
- [x] 4.8 Implement note deduplication on upsert (case-insensitive, whitespace-stripped)
- [x] 4.9 Implement field update with omit-means-no-change semantics
- [x] 4.10 Write unit tests: upsert/merge, note dedup, alias lookup, slug collision, field update semantics

## 5. AI Provider
- [x] 5.1 Implement OpenAI-compatible client wrapper with two-tier config and configurable timeout
- [x] 5.2 Write categorization prompt template (include existing project names and aliases, instruct to omit unknown fields)
- [x] 5.3 Implement defensive JSON response parser (try parse -> extract block -> fallback)
- [x] 5.4 Write discussion prompt with conversation history + rolling summary injection
- [x] 5.5 Write compaction prompt for summarizing overflowing messages into rolling summary
- [x] 5.6 Write unit tests: response parser (all three fallback cases), timeout handling

## 6. Obsidian Sync
- [x] 6.1 Implement markdown file writer with YAML frontmatter and notes section
- [x] 6.2 Implement atomic git sync: pull -> write -> add -> commit -> push (asyncio.to_thread)
- [x] 6.3 Implement conflict handling: abort merge, save as .conflict.md, notify user
- [x] 6.4 Write unit tests: markdown export generator

## 7. Telegram Bot Core
- [ ] 7.1 Set up python-telegram-bot Application with polling in bot.py
- [ ] 7.2 Implement ALLOWED_USER_ID filter (ignore unauthorized users silently)
- [ ] 7.3 Implement message handler: check discussion mode -> categorize -> upsert -> sync -> reply
- [ ] 7.4 Implement new project confirmation flow (inline keyboard yes/no)
- [ ] 7.5 Persist pending confirmations to SQLite for restart survival
- [ ] 7.6 Write integration test: chat handler with mocked AI

## 8. Discussion Mode
- [ ] 8.1 Implement conversation context: rolling summary + recent message window (max_history from config)
- [ ] 8.2 Implement compaction: summarize oldest messages into rolling summary when window overflows
- [ ] 8.3 Implement /chat command to enter discussion mode
- [ ] 8.4 Implement AI-based intent routing in categorization response
- [ ] 8.5 Implement natural language exit detection (AI classifies exit intent)
- [ ] 8.6 Implement stale conversation timeout as background asyncio task (stale_minutes from config), reset timer on each message, re-init on restart
- [ ] 8.7 Implement /save command: AI summarizes discussion, confirm target project, append to notes, sync
- [ ] 8.8 Persist discussion mode flag and rolling summary to SQLite, restore on restart
- [ ] 8.9 Write integration test: discussion flow with save

## 9. Slash Commands
- [ ] 9.1 /start - welcome message on first use, short ack on subsequent calls
- [ ] 9.2 /help - list all commands with descriptions
- [ ] 9.3 /projects - list all projects with name and status
- [ ] 9.4 /project <name> - show full project detail (resolve by name, slug, or alias)
- [ ] 9.5 /export <name> - send project markdown file as Telegram document
- [ ] 9.6 /clear - wipe conversation context, exit discussion mode (with confirmation)
- [ ] 9.7 /save - summarize and save discussion to project notes
- [ ] 9.8 Write integration test: /export command with mocked DB

## 10. Integration and Polish
- [ ] 10.1 Wire all components together: cli.py -> bot.py -> handlers -> services
- [ ] 10.2 End-to-end manual test: install package, run init, start service, test via Telegram
- [ ] 10.3 Write README.md with installation, setup, usage, and Docker instructions
- [ ] 10.4 Update openspec/project.md if conventions changed during implementation
