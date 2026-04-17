# Change: Add Second Brain Bot

## Why
Capture project ideas on the go via Telegram chat. Currently, ideas get lost
between thinking about them and sitting down to work. Need a zero-friction way
to record and organize project notes that are available on any machine.

## What Changes
- New: Installable Python package (PyPI) with `second-brain` CLI entry point
- New: Interactive setup wizard (`second-brain init`) with TOML config file
- New: System service installation (systemd on Linux, launchd on macOS)
- New: XDG-compliant data storage (~/.config, ~/.local/share)
- New: Telegram bot with single-user auth (ALLOWED_USER_ID)
- New: AI-powered note categorization and project inference (OpenAI-compatible API)
- New: Two-tier AI routing - cheap model for extraction, bigger model for discussion
- New: Hybrid intent detection - AI auto-classifies, /chat forces discussion mode
- New: SQLite project store with structured metadata and project aliases
- New: Obsidian vault markdown writer with atomic git sync (pull/write/commit/push)
- New: Git conflict handling (save as .conflict.md for manual resolution)
- New: Discussion mode with rolling summary + recent message window
- New: /save command to AI-summarize discussions into project notes
- New: Natural language discussion exit detection and stale conversation timeout
- New: Discussion state persistence across bot restarts (SQLite)
- New: Slug collision detection and alias-based project matching
- New: Case-insensitive note deduplication
- New: AI request timeout handling
- New: Slash commands: /start, /help, /projects, /project, /export, /clear, /chat, /save
- New: Docker support as optional secondary deployment path

## Impact
- Affected specs: cli-service, note-capture, project-store, obsidian-sync,
  ai-provider, discussion-mode, slash-commands (all new)
- Affected code: entire codebase (greenfield)
