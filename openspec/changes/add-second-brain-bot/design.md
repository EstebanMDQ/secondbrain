## Context
Greenfield self-hosted Telegram bot, distributed as an installable Python
package. Single developer, targets Linux primarily and macOS secondarily.
Simplicity over scalability.

## Goals / Non-Goals
- Goals: Capture ideas fast, auto-organize by project, Obsidian-friendly output,
  AI provider agnostic, works across multiple machines via git-synced vault,
  easy to install and run as a system service
- Non-Goals: Multi-user support, web UI, real-time collaboration, complex NLP
  pipelines, Windows support

## Decisions

### Distribution: Installable Python package
- Published to PyPI as `secondbrain`, CLI entry point `second-brain`
- Install via `pip install secondbrain` or `uv tool install secondbrain`
- Interactive setup wizard (`second-brain init`) for first-time configuration
- Runs as a system service (systemd on Linux, launchd on macOS)
- Docker support included as optional secondary deployment path
- Alternatives considered: Docker-only (less approachable for OSS), snap/flatpak
  (overkill for a CLI tool)

### Configuration: TOML file with env var overrides
- Config file at ~/.config/second-brain/config.toml (XDG-compliant)
- `second-brain init` wizard generates the config interactively
- Environment variables override config (prefixed SECONDBRAIN_)
- TOML is more ergonomic than .env for users installing a package
- Docker users can use env vars or mount a config file

### Data storage: XDG-compliant
- SQLite DB at ~/.local/share/second-brain/brain.db
- Respects XDG_CONFIG_HOME and XDG_DATA_HOME if set
- Obsidian vault path is user-configured (separate directory)

### CLI framework: click
- Well-known, stable, lightweight
- Commands: init, run, install-service, uninstall-service, status
- Alternative considered: typer (heavier, adds pydantic dependency)

### Architecture: Single async Python process
- One process handles Telegram polling, AI calls, DB writes, git operations
- No task queue, no workers, no microservices
- python-telegram-bot async handlers dispatch to service layer
- Alternatives considered: FastAPI + webhook (more infra), celery (overkill)

### Data flow
1. Telegram message received by handler
2. Handler checks ALLOWED_USER_ID
3. If slash command -> route to command handler
4. If discussion mode is active -> route directly to discussion model
5. If /chat -> enter discussion mode
6. If regular message -> send to categorization model
7. Categorization model classifies intent and extracts data:
   - Intent: note -> upsert project store, sync obsidian, reply with confirmation
   - Intent: question -> route to discussion model, reply ephemerally
8. If new project detected -> confirmation flow (inline keyboard yes/no)
9. On project create/update -> git pull, write markdown, git commit/push
10. Bot replies with confirmation

### Two-tier AI configuration
- Both tiers use the openai Python package pointed at different base URLs
- Separate config sections for categorization vs discussion models
- Categorization: system prompt asks for JSON with intent, project slug, name,
  description, stack, tags, status, notes; omit fields that can't be inferred
- Discussion: system prompt sets context, conversation history appended
- Provider examples: Ollama (local), OpenAI, Anthropic (via compatible proxy)
- All AI calls enforce configurable timeout (default 30s)

### Hybrid intent routing
- Default: categorization model classifies intent (note vs question)
- /chat command: forces discussion mode, bypasses categorization
- Discussion exit: natural language detection or stale timeout
- /save command: AI summarizes discussion, appends to project notes
- /clear exits discussion mode and wipes history

### Field update semantics
- AI prompt instructs model to omit fields it can't infer
- Omitted fields in AI response = no change to existing value
- Present fields = update the value
- This avoids the null-vs-absent ambiguity

### Project aliases
- Each project stores a list of alternative names (aliases) in SQLite
- The primary name is always the first alias
- Categorization prompt includes all aliases for matching
- When the AI matches via a new name, that name is added as an alias
- Prevents the same project from being created under different names

### SQLite via SQLAlchemy (no migrations)
- create_all on startup, single .db file
- Tags, notes, and aliases stored as JSON columns (SQLite JSON1)
- Discussion mode state and pending confirmations persisted to SQLite
- Simple and disposable - user's real data lives in Obsidian markdown
- If schema changes, drop the DB and re-derive from markdown files

### Obsidian file format
- One .md file per project: {slug}.md
- YAML frontmatter: name, status, stack, tags, description
- Body: ## Notes section with bullet list
- Subfolder configurable via config (default: projects)

### Git operations (atomic sync)
- Sequence: git pull -> write file -> git add -> git commit -> git push
- On merge conflict: abort merge, write file as {slug}.conflict.md, notify user
- On push failure: log error, notify user, local commit preserved
- All operations via asyncio.to_thread to avoid blocking the event loop
- Alternative considered: GitPython (extra dependency for little gain)

### Discussion context: rolling summary + recent window
- Recent messages kept in-memory (last DISCUSSION_MAX_HISTORY, default 20)
- When the window overflows, oldest messages are compacted into a rolling summary
  via a summarization call to the discussion model
- The AI sees: system prompt + rolling summary + recent messages
- This preserves full conversation context without unbounded token growth
- On compaction, the oldest half of messages are summarized (not one at a time)
- Trade-off: one extra AI call per compaction (infrequent at 20-message window)

### Discussion state persistence
- Discussion mode flag, rolling summary, and pending confirmations stored in SQLite
- Recent message history stays in-memory (lost on restart)
- On restart: restore mode flag + rolling summary, inform user recent messages were lost

### Service management
- `second-brain install-service` resolves the absolute path to the binary
  (shutil.which / sys.executable) and embeds it in the service file
- Generates a systemd user unit (Linux) or launchd plist (macOS)
- User-level service (no root required)
- Logs go to journald (Linux) or system log (macOS)
- Log level configurable via config file or --log-level flag (default: info)

### Project structure
```
secondbrain/
├── src/
│   └── secondbrain/
│       ├── __init__.py
│       ├── cli.py            # Click CLI: init, run, install-service, status
│       ├── bot.py            # Telegram bot setup and polling
│       ├── handlers.py       # Telegram message/command handlers
│       ├── ai.py             # AI client, prompts, response parsing
│       ├── store.py          # SQLAlchemy models and CRUD
│       ├── obsidian.py       # Markdown writer + git sync
│       ├── discussion.py     # Conversation manager (rolling summary + window)
│       ├── config.py         # TOML config loading, settings dataclass
│       └── service.py        # systemd/launchd service file generation
├── tests/
│   ├── test_store.py
│   ├── test_obsidian.py
│   ├── test_ai.py
│   ├── test_handlers.py
│   ├── test_export.py
│   └── test_config.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml            # Package metadata, entry points, dependencies
├── LICENSE
└── README.md
```

### Config file format (config.toml)
```toml
log_level = "info"  # debug, info, warning, error

[telegram]
token = "123456:ABC..."
allowed_user_id = 12345678

[ai.categorization]
base_url = "http://localhost:11434/v1"
api_key = "ollama"
model = "llama3.2"

[ai.discussion]
base_url = "https://api.openai.com/v1"
api_key = "sk-..."
model = "gpt-4o"

[ai]
timeout_seconds = 30

[discussion]
max_history = 20
stale_minutes = 30

[obsidian]
vault_path = "/home/user/obsidian-vault"
subfolder = "projects"
```

## Risks / Trade-offs
- Git push in bot process may block briefly -> mitigated by asyncio.to_thread
- create_all with no migrations means schema changes require DB recreation
  -> acceptable, SQLite is a disposable index; markdown is source of truth
- Single-user design baked in -> intentional constraint for v1
- Ollama must be running for categorization -> document in setup instructions
- Conversation history lost on restart -> acceptable, rolling summary persists
- Git conflicts saved as .conflict.md -> user resolves manually
- systemd user units require lingering enabled for service to run when user is
  logged out -> document in setup instructions (loginctl enable-linger)

## Open Questions
- None remaining (all resolved in design session)
