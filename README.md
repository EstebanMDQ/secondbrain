# second-brain

A self-hosted Telegram bot for capturing and organizing project ideas on the
go. Chat naturally about your projects and the bot uses an LLM to sort each
message into a per-project markdown file in your Obsidian vault, then commits
and pushes the change so the same notes are available on every machine you
work from.

## Features

- Capture ideas from anywhere through a private Telegram bot.
- Two-tier AI: a cheap categorization model classifies and extracts fields,
  a bigger discussion model handles back-and-forth chat.
- Auto-categorization into per-project markdown with YAML frontmatter,
  written into a configurable Obsidian subfolder.
- Atomic git sync (pull, write, commit, push) keeps the vault current
  without blocking the bot loop.
- Discussion mode with a rolling summary so long conversations stay
  in-context without runaway token usage.
- Slash commands for listing, inspecting, exporting, and saving notes
  without leaving Telegram.

## Requirements

- Python 3.13 or newer.
- A Telegram bot token (create one with [@BotFather](https://t.me/BotFather))
  and your numeric Telegram user ID.
- An OpenAI-compatible endpoint for both AI tiers (Ollama, OpenAI,
  Anthropic via a compatible proxy, etc.).
- An Obsidian vault that is a git repository with a configured remote.

## Installation

The package is not on PyPI yet (coming soon). For now install from source:

```bash
git clone https://github.com/your-org/second-brain.git
cd second-brain
uv tool install .
```

Once published, install with either:

```bash
uv tool install secondbrain
# or
pip install secondbrain
```

## Setup

Run the interactive wizard to generate `~/.config/second-brain/config.toml`:

```bash
second-brain init
```

The wizard asks for the Telegram token and allowed user ID, base URL / API
key / model for both AI tiers, the path to your Obsidian vault, and a few
tunable defaults. The vault path is validated as a git repo with at least
one configured remote before the config is written.

## Running

Start the bot in the foreground (good for verifying the setup):

```bash
second-brain run
```

Install it as a user-level service so it starts at login and restarts on
crash:

```bash
second-brain install-service     # systemd user unit on Linux, launchd on macOS
second-brain status              # show config path, db path, project count, service state
second-brain uninstall-service   # stop and remove the service
```

## Docker

A `Dockerfile` and `docker-compose.yml` are included for users who prefer
containers. Mount your vault, supply the configuration via environment
variables, and bring the stack up:

```bash
docker compose up -d
```

Required environment variables (see the comments at the top of
`docker-compose.yml` for the full list):

- `VAULT_DIR` - host path to the Obsidian vault, mounted at `/vault`.
- `SECONDBRAIN_TELEGRAM_TOKEN`, `SECONDBRAIN_TELEGRAM_ALLOWED_USER_ID`.
- `SECONDBRAIN_AI_CATEGORIZATION_BASE_URL`, `_API_KEY`, `_MODEL`.
- `SECONDBRAIN_AI_DISCUSSION_BASE_URL`, `_API_KEY`, `_MODEL`.

`CONFIG_DIR` and `DATA_DIR` default to `./config` and `./data` next to the
compose file and are persisted across restarts.

## Commands

- `/start` - welcome message and bot intro
- `/help` - show this list of commands
- `/projects` - list all projects with their status
- `/project <name>` - show full detail for a project
- `/new <name>` - create a project by name; put a description on the next line, or after ` - ` on the same line
- `/export <name>` - send the project markdown file as a document
- `/chat` - enter discussion mode for back-and-forth
- `/save` - summarize the current discussion and save to a project
- `/clear` - wipe the discussion history (with confirmation)

### Capturing notes

Plain text messages are parsed deterministically - no AI is called on the
capture path. The protocol:

- The first non-empty line is the **project selector** (name, alias, or
  fuzzy match against either).
- Subsequent non-empty lines are **notes**. Paragraphs separated by a
  blank line become separate bullets under `## Notes`; newlines inside a
  paragraph are preserved as continuation lines.
- Single-line messages (a selector with no notes) are rejected so the bot
  never silently creates an empty project.

Project matching is exact first (slug, case-insensitive name, or alias),
then fuzzy via `rapidfuzz` with a configurable threshold (default 85) and
a 10-point runner-up gap to avoid ambiguous matches. If nothing matches,
the bot offers to create the project with a yes/no inline keyboard.

Example:

```
morning-news
Fix RSS dedupe - currently drops items that share a title but differ in URL.
Also: bump feed health jsonl to include HTTP status.
```

-> matches the `morning-news` project and appends two note bullets.

## Configuration reference

`~/.config/second-brain/config.toml`:

```toml
log_level = "info"  # debug, info, warning, error

[telegram]
token = "123456:ABC..."
allowed_user_id = 12345678          # only this Telegram user can talk to the bot

[ai]
timeout_seconds = 30                # per-request timeout for both tiers

[ai.categorization]                 # deprecated: kept for forward-compat, no longer called on capture
base_url = "http://localhost:11434/v1"
api_key = "ollama"
model = "llama3.2"

[ai.discussion]                     # bigger model, used in /chat and /save
base_url = "https://api.openai.com/v1"
api_key = "sk-..."
model = "gpt-4o"

[discussion]
max_history = 20                    # recent messages kept in memory before compaction
stale_minutes = 30                  # idle timeout before discussion mode auto-exits

[capture]
fuzzy_threshold = 85                # rapidfuzz score required to match a project selector (0-100)

[obsidian]
vault_path = "/home/user/obsidian-vault"
subfolder = "projects"              # notes are written to <vault>/<subfolder>/<slug>.md
auto_stash_dirty = false            # if true, stash ALL uncommitted changes before sync and pop after push; on pop conflict the stash is left in place and the ref is reported
dirty_ignore_paths = []             # paths to stash transparently around the sync, even when auto_stash_dirty=false (entries ending in "/" are directory prefixes, others are exact paths). e.g. [".backup/", ".obsidian/workspace.json"]
```

Every key can be overridden by an environment variable with the
`SECONDBRAIN_` prefix and underscores for nested tables (for example
`SECONDBRAIN_AI_CATEGORIZATION_MODEL`). Env vars take precedence over the
file, which is convenient for Docker and one-off tweaks.

## Troubleshooting

- **systemd service stops when you log out.** User-level units only run
  while the user has an active session. Enable lingering once with
  `loginctl enable-linger $USER` so the service keeps running across
  logins.
- **`vault path is not a git repository`.** The vault must be an
  initialized git repo with at least one configured remote. Run
  `git init`, add a remote, and push an initial commit before pointing
  the bot at it.
- **Categorization fails or hangs.** If you configured Ollama as the
  categorization endpoint, make sure the Ollama daemon is running
  (`ollama serve`) and the configured model has been pulled
  (`ollama pull llama3.2`).
- **`.conflict.md` files in the vault.** A git rebase failed during sync.
  Resolve the conflict manually in the vault, commit, and push; the bot
  will keep writing to the canonical file on the next update.
- **`vault has uncommitted changes`.** The bot refuses to sync when
  the vault has tracked-modified files (intent-to-add files count
  too). Untracked content - new files, `.backup/` folders, editor swap
  files - does not trigger this, because it can't actually block
  `git pull --rebase`. Run `git status` in the vault, commit or stash
  the listed paths, then re-send the note (or run `/project <name>`)
  to retry. The DB row was already written, so no capture is lost.
  Two escape hatches:
  - `auto_stash_dirty = true` under `[obsidian]` makes the bot stash
    ALL dirty content transparently and pop after the push.
  - `dirty_ignore_paths = [".backup/", ".obsidian/workspace.json"]`
    targets specific paths: the bot will stash *those* paths to let
    the sync proceed, even when `auto_stash_dirty=false`. Entries
    ending in `/` match directory prefixes; others match exact paths.
  If a stash pop conflicts (rare - only when the pulled remote and
  your stashed work touched the same file), the bot leaves the stash
  in place and reports its ref so you can recover with
  `git stash show` / `git stash pop`.

## License

Apache 2.0 - see [LICENSE](LICENSE).
