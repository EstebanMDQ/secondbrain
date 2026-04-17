"""Click-based CLI entry point for second-brain.

Exposes subcommands: ``init``, ``run``, ``install-service``,
``uninstall-service``, and ``status``. Bot-specific imports are kept lazy so
invoking the CLI (or ``--help``) does not force loading the async bot stack.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import click

from secondbrain import config, service

LOG_LEVELS = ("debug", "info", "warning", "error")


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "second-brain" / "config.toml"


def _escape_toml_string(value: str) -> str:
    """Escape a string for a TOML basic-string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _render_toml(data: dict[str, Any]) -> str:
    """Render a nested dict into a TOML string.

    Supports only the subset needed by the init wizard: top-level scalars and
    one or two levels of nested tables containing strings or ints.
    """
    lines: list[str] = []
    scalars: dict[str, Any] = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables: dict[str, Any] = {k: v for k, v in data.items() if isinstance(v, dict)}

    for key, value in scalars.items():
        lines.append(_format_kv(key, value))
    if scalars and tables:
        lines.append("")

    def emit_table(prefix: str, table: dict[str, Any]) -> None:
        child_scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        child_tables = {k: v for k, v in table.items() if isinstance(v, dict)}
        lines.append(f"[{prefix}]")
        for k, v in child_scalars.items():
            lines.append(_format_kv(k, v))
        lines.append("")
        for k, v in child_tables.items():
            emit_table(f"{prefix}.{k}", v)

    for name, table in tables.items():
        emit_table(name, table)

    return "\n".join(lines).rstrip() + "\n"


def _format_kv(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, int):
        return f"{key} = {value}"
    if isinstance(value, str):
        return f'{key} = "{_escape_toml_string(value)}"'
    raise TypeError(f"unsupported TOML value type for {key}: {type(value).__name__}")


def _validate_vault(vault: Path) -> None:
    """Ensure ``vault`` is an existing directory, a git repo, and has a remote."""
    if not vault.exists():
        raise click.ClickException(f"vault path does not exist: {vault}")
    if not vault.is_dir():
        raise click.ClickException(f"vault path is not a directory: {vault}")
    if not (vault / ".git").exists():
        raise click.ClickException(f"vault path is not a git repository: {vault}")
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), "remote"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(f"failed to inspect git remotes in {vault}: {exc}") from exc
    if not result.stdout.strip():
        raise click.ClickException(f"vault git repo has no configured remote: {vault}")


def _configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_log_level(explicit: str | None) -> str:
    """CLI flag wins; otherwise fall back to the config file if it loads cleanly."""
    if explicit:
        return explicit.lower()
    try:
        settings = config.load_config()
    except config.ConfigError:
        return "info"
    return settings.log_level


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default=None,
    help="Override log level (falls back to config, then 'info').",
)
@click.pass_context
def main(ctx: click.Context, log_level: str | None) -> None:
    """Self-hosted Telegram bot for capturing project ideas."""
    resolved = _resolve_log_level(log_level)
    _configure_logging(resolved)
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = resolved


@main.command("init")
def init_cmd() -> None:
    """Interactive setup wizard. Writes config to ~/.config/second-brain/config.toml."""
    click.echo("Second Brain setup wizard")
    click.echo("-------------------------")

    telegram_token = click.prompt("Telegram bot token", hide_input=True)
    allowed_user_id = click.prompt("Allowed Telegram user ID", type=int)

    click.echo("\nCategorization AI (cheap model for extraction):")
    cat_base_url = click.prompt("  base URL", default="http://localhost:11434/v1")
    cat_api_key = click.prompt("  API key", hide_input=True)
    cat_model = click.prompt("  model")

    click.echo("\nDiscussion AI (bigger model for chat):")
    disc_base_url = click.prompt("  base URL", default="https://api.openai.com/v1")
    disc_api_key = click.prompt("  API key", hide_input=True)
    disc_model = click.prompt("  model")

    vault_raw = click.prompt("\nObsidian vault path")
    vault = Path(vault_raw).expanduser().resolve()
    _validate_vault(vault)

    timeout = click.prompt("AI request timeout (seconds)", default=30, type=int)
    max_history = click.prompt("Discussion max_history", default=20, type=int)
    stale_minutes = click.prompt("Discussion stale_minutes", default=30, type=int)

    payload: dict[str, Any] = {
        "log_level": "info",
        "telegram": {
            "token": telegram_token,
            "allowed_user_id": allowed_user_id,
        },
        "ai": {
            "timeout_seconds": timeout,
            "categorization": {
                "base_url": cat_base_url,
                "api_key": cat_api_key,
                "model": cat_model,
            },
            "discussion": {
                "base_url": disc_base_url,
                "api_key": disc_api_key,
                "model": disc_model,
            },
        },
        "discussion": {
            "max_history": max_history,
            "stale_minutes": stale_minutes,
        },
        "obsidian": {
            "vault_path": str(vault),
            "subfolder": "projects",
        },
    }

    config_path = _default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_render_toml(payload))
    config.data_dir().mkdir(parents=True, exist_ok=True)

    click.echo(f"\nWrote config to {config_path}")


@main.command("run")
@click.pass_context
def run_cmd(ctx: click.Context) -> None:
    """Start the Telegram bot in the foreground."""
    try:
        config.load_config()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    # TODO(task 8/10): wire in bot.py entry point once the Telegram layer lands.
    # Keep the import lazy so the CLI does not force bot deps at module load.
    click.echo("bot not yet implemented")


@main.command("install-service")
def install_service_cmd() -> None:
    """Install and start the bot as a user-level OS service."""
    try:
        service.install_service()
    except service.UnsupportedOSError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Service installed and started.")


@main.command("uninstall-service")
def uninstall_service_cmd() -> None:
    """Stop and remove the user-level OS service."""
    try:
        service.uninstall_service()
    except service.UnsupportedOSError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Service uninstalled.")


@main.command("status")
def status_cmd() -> None:
    """Show config path, DB path, project count, and service status."""
    from secondbrain import store

    config_path = _default_config_path()
    click.echo(f"Config: {config_path}")

    try:
        settings = config.load_config()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    db = config.db_path()
    click.echo(f"DB:     {db}")
    click.echo(f"Vault:  {settings.obsidian.vault_path}")

    engine = store.init_db(db)
    with store.Session(engine) as session:
        projects = store.list_projects(session)
    click.echo(f"Projects: {len(projects)}")

    try:
        status = service.service_status()
        click.echo(
            f"Service: active={status['active']} enabled={status['enabled']} pid={status['pid']}"
        )
    except service.UnsupportedOSError as exc:
        click.echo(f"Service: unsupported ({exc})")


if __name__ == "__main__":
    main()
