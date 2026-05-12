"""Telegram message and callback handlers for the second-brain bot.

Handlers receive a :class:`BotContext` via ``context.bot_data['ctx']`` that
exposes the loaded settings, the AI client pair, a SQLAlchemy session factory,
and the vault sync configuration. Auth is enforced per-handler - unauthorized
users are silently dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from secondbrain import ai, discussion, obsidian, store
from secondbrain.config import Settings

logger = logging.getLogger(__name__)

CTX_KEY = "ctx"
STATE_DISCUSSION_MODE = discussion.STATE_DISCUSSION_MODE
STATE_PENDING_PREFIX = "pending_confirmation:"
STATE_PENDING_SAVE = "pending_save"
STATE_AWAITING_SAVE_NAME = "awaiting_save_name"
STATE_HAS_STARTED = "has_started"

COMMAND_DESCRIPTIONS: dict[str, str] = {
    "/start": "welcome message and bot intro",
    "/help": "show this list of commands",
    "/projects": "list all projects with their status",
    "/project <name>": "show full detail for a project",
    "/new <name>": "create a project (optional description on next line or after ' - ')",
    "/export <name>": "send the project markdown file as a document",
    "/chat": "enter discussion mode for back-and-forth",
    "/save": "summarize the current discussion and save to a project",
    "/clear": "wipe the discussion history (with confirmation)",
}

_WELCOME_MESSAGE = (
    "welcome to second-brain\n\n"
    "send any message and i'll categorize it into a project and sync it "
    "to your obsidian vault. use /chat to talk things through before saving, "
    "/projects to see what you've captured, and /help for the full command list."
)


@dataclass(frozen=True)
class BotContext:
    """Dependencies injected into every handler via ``application.bot_data``."""

    settings: Settings
    ai_clients: ai.AIClients
    session_factory: Callable[[], Session]
    vault_path: Path
    vault_subfolder: str
    auto_stash_dirty: bool = False
    dirty_ignore_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ProjectSnapshot:
    """Detached copy of a project so sync can run after the session closes."""

    name: str
    slug: str
    status: str | None
    stack: list[str]
    tags: list[str]
    description: str | None
    ideas: str | None
    notes: list[str]


def _snapshot(project: store.Project) -> _ProjectSnapshot:
    return _ProjectSnapshot(
        name=project.name,
        slug=project.slug,
        status=project.status,
        stack=list(project.stack or []),
        tags=list(project.tags or []),
        description=project.description,
        ideas=project.ideas,
        notes=list(project.notes or []),
    )


def parse_capture_message(text: str) -> tuple[str, list[str]]:
    """Split a capture message into (selector, notes) per the capture protocol.

    The first non-empty line (after trimming leading/trailing blank lines) is
    the selector. Remaining lines are grouped into paragraphs separated by
    one or more blank lines; each paragraph becomes one note string with
    internal newlines preserved.
    """
    lines = text.split("\n")

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = len(lines)
    while end > start and not lines[end - 1].strip():
        end -= 1
    lines = lines[start:end]

    if not lines:
        return "", []

    selector = lines[0].strip()
    remainder = lines[1:]

    notes: list[str] = []
    current: list[str] = []
    for line in remainder:
        if line.strip():
            current.append(line)
        elif current:
            notes.append("\n".join(current))
            current = []
    if current:
        notes.append("\n".join(current))

    return selector, notes


def parse_new_project_args(raw: str) -> tuple[str, str | None]:
    """Split the raw argument text for `/new` into (name, description).

    If the payload contains a newline, the first line becomes the name and
    the remaining lines (joined with newlines) become the description.
    Otherwise, a `` - `` (space-dash-space) separator splits the line into
    name and description. If neither form applies, the entire payload is
    treated as the name with no description. Returns a stripped name (may
    be empty) and a stripped non-empty description or ``None``.
    """
    if "\n" in raw:
        first, rest = raw.split("\n", 1)
        name = first.strip()
        description = rest.strip() or None
        return name, description

    if " - " in raw:
        first, rest = raw.split(" - ", 1)
        name = first.strip()
        description = rest.strip() or None
        return name, description

    return raw.strip(), None


def get_ctx(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Return the :class:`BotContext` stored on the application."""
    ctx = context.bot_data.get(CTX_KEY)
    if not isinstance(ctx, BotContext):
        raise RuntimeError("BotContext missing from application bot_data")
    return ctx


def require_allowed_user(update: Update, allowed_user_id: int) -> bool:
    """Return True only when the effective user matches the configured id."""
    user = update.effective_user
    if user is None or user.id != allowed_user_id:
        logger.info(
            "dropping message from unauthorized user id=%r",
            getattr(user, "id", None),
        )
        return False
    return True


def _normalize_notes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _summarize_update(payload: dict[str, Any], project_name: str) -> str:
    note_count = len(_normalize_notes(payload.get("notes")))
    if note_count == 1:
        return f"Added note to '{project_name}'"
    if note_count > 1:
        return f"Added {note_count} notes to '{project_name}'"
    return f"Updated '{project_name}'"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the welcome message on first use, a short ack on subsequent calls."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return

    with ctx.session_factory() as session:
        has_started = bool(store.get_state(session, STATE_HAS_STARTED, False))
        if not has_started:
            store.set_state(session, STATE_HAS_STARTED, True)
            session.commit()

    if has_started:
        await update.message.reply_text("ready - /help for commands")
    else:
        await update.message.reply_text(_WELCOME_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List every registered command with a one-line description."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return
    lines = [f"{cmd} - {desc}" for cmd, desc in COMMAND_DESCRIPTIONS.items()]
    await update.message.reply_text("\n".join(lines))


async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a sorted list of every project and its status."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return
    with ctx.session_factory() as session:
        projects = store.list_projects(session)

    if not projects:
        await update.message.reply_text(
            "no projects yet - send a message to capture your first one"
        )
        return

    projects.sort(key=lambda p: p.name.lower())
    lines = [f"{p.name} - {p.status or 'no status'}" for p in projects]
    await update.message.reply_text("\n".join(lines))


def _format_project_detail(project: store.Project) -> str:
    stack = ", ".join(project.stack or []) or "-"
    tags = ", ".join(project.tags or []) or "-"
    description = project.description or "-"
    note_count = len(project.notes or [])
    return (
        f"name: {project.name}\n"
        f"slug: {project.slug}\n"
        f"status: {project.status or '-'}\n"
        f"stack: {stack}\n"
        f"tags: {tags}\n"
        f"description: {description}\n"
        f"notes: {note_count}"
    )


async def project_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the full stored detail for a single project."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return
    if not context.args:
        await update.message.reply_text("usage: /project <name>")
        return
    query = " ".join(context.args).strip()

    with ctx.session_factory() as session:
        project = store.get_project(session, query)
        if project is None:
            await update.message.reply_text(f"no project matches '{query}'")
            return
        detail = _format_project_detail(project)

    await update.message.reply_text(detail)


def _extract_raw_args(message_text: str | None, command: str) -> str:
    """Return the text after ``/command`` (and any ``@bot`` suffix) as-is.

    Preserves newlines so multi-line command payloads (used by ``/new``)
    survive ``context.args`` whitespace-splitting.
    """
    if not message_text:
        return ""
    if not message_text.startswith(f"/{command}"):
        return ""
    after = message_text[len(command) + 1 :]
    if after.startswith("@"):
        _, _, after = after.partition(" ")
    elif after.startswith(" ") or after.startswith("\n"):
        after = after[1:]
    elif after:
        return ""
    return after


async def new_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a project from an explicit ``/new <name>[ - desc | \\ndesc]`` command."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return

    raw = _extract_raw_args(update.message.text, "new")
    name, description = parse_new_project_args(raw)

    if not name:
        await update.message.reply_text(
            "usage: /new <name>\noptional description: put it on the next line, or after ' - '"
        )
        return

    with ctx.session_factory() as session:
        existing = store.get_project(session, name)
        if existing is not None:
            await update.message.reply_text(
                f"'{name}' collides with existing project '{existing.name}' (slug: {existing.slug})"
            )
            return

        project = store.create_project(
            session,
            name=name,
            description=description,
        )
        session.commit()
        session.refresh(project)
        snapshot = _snapshot(project)

    result = await obsidian.sync_project_async(
        ctx.vault_path,
        ctx.vault_subfolder,
        snapshot,
        auto_stash_dirty=ctx.auto_stash_dirty,
        dirty_ignore_paths=ctx.dirty_ignore_paths,
    )
    if result.status in ("ok", "noop"):
        await update.message.reply_text(f"created '{snapshot.name}' (slug: {snapshot.slug})")
    elif result.status == "conflict":
        await update.message.reply_text(
            f"created '{snapshot.name}' but git rebase conflicted - see {result.path.name}"
        )
    elif result.status == "dirty":
        await update.message.reply_text(
            f"created '{snapshot.name}' but vault has uncommitted changes - "
            f"commit or stash and retry with /project {snapshot.name}\n{result.message}"
        )
    else:
        await update.message.reply_text(
            f"created '{snapshot.name}' but sync failed: {result.message}"
        )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the project's markdown file from the vault as a Telegram document."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return
    if not context.args:
        await update.message.reply_text("usage: /export <name>")
        return
    query = " ".join(context.args).strip()

    with ctx.session_factory() as session:
        project = store.get_project(session, query)
        if project is None:
            await update.message.reply_text(f"no project matches '{query}'")
            return
        snapshot = _snapshot(project)

    path = ctx.vault_path / ctx.vault_subfolder / f"{snapshot.slug}.md"
    if not path.exists():
        path = obsidian.write_project_file(ctx.vault_path, ctx.vault_subfolder, snapshot)

    chat = update.effective_chat
    if chat is None:
        return
    with path.open("rb") as fh:
        await context.bot.send_document(
            chat_id=chat.id,
            document=fh,
            filename=f"{snapshot.slug}.md",
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route a free-text message: awaiting name -> discussion -> capture parse."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return

    message = update.message
    if message is None or not message.text:
        return
    user = update.effective_user
    user_id = user.id if user is not None else 0

    with ctx.session_factory() as session:
        awaiting_save_name = bool(store.get_state(session, STATE_AWAITING_SAVE_NAME, False))
        discussion_mode = bool(store.get_state(session, STATE_DISCUSSION_MODE, False))

    if awaiting_save_name:
        await _save_to_named_project(ctx, message, message.text.strip())
        return

    if discussion_mode:
        await _handle_discussion_turn(ctx, message, user_id)
        return

    selector, notes = parse_capture_message(message.text)
    if not selector or not notes:
        await message.reply_text("send the project on line 1 and notes on the next lines")
        return

    with ctx.session_factory() as session:
        project = store.get_project(session, selector)
        if project is None:
            project = store.find_project_fuzzy(
                session, selector, ctx.settings.capture.fuzzy_threshold
            )

        if project is None:
            pending_key = f"{STATE_PENDING_PREFIX}{message.message_id}"
            store.set_state(session, pending_key, {"name": selector, "notes": notes})
            session.commit()
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Yes",
                            callback_data=f"confirm:yes:{message.message_id}",
                        ),
                        InlineKeyboardButton(
                            "No",
                            callback_data=f"confirm:no:{message.message_id}",
                        ),
                    ]
                ]
            )
            await message.reply_text(
                f"Create '{selector}'?",
                reply_markup=keyboard,
            )
            return

        updated = store.update_project(session, project.id, notes=notes)
        session.commit()
        session.refresh(updated)
        snapshot = _snapshot(updated)

    result = await obsidian.sync_project_async(
        ctx.vault_path,
        ctx.vault_subfolder,
        snapshot,
        auto_stash_dirty=ctx.auto_stash_dirty,
        dirty_ignore_paths=ctx.dirty_ignore_paths,
    )
    if result.status in ("ok", "noop"):
        await message.reply_text(_summarize_update({"notes": notes}, snapshot.name))
    elif result.status == "conflict":
        await message.reply_text(
            f"Updated '{snapshot.name}' but git rebase conflicted - see {result.path.name}"
        )
    elif result.status == "dirty":
        await message.reply_text(
            f"updated '{snapshot.name}' but vault has uncommitted changes - "
            f"commit or stash and retry with /project {snapshot.name}\n{result.message}"
        )
    else:
        await message.reply_text(f"Updated '{snapshot.name}' but sync failed: {result.message}")


async def handle_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve a pending new-project confirmation from the inline keyboard."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return

    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "confirm":
        return
    decision, message_id = parts[1], parts[2]
    pending_key = f"{STATE_PENDING_PREFIX}{message_id}"

    with ctx.session_factory() as session:
        payload = store.get_state(session, pending_key)
        if payload is None:
            await query.edit_message_text("(this confirmation expired)")
            return

        store.set_state(session, pending_key, None)

        if decision != "yes":
            session.commit()
            await query.edit_message_text("cancelled")
            return

        name = payload.get("name") or "untitled"
        project = store.create_project(
            session,
            name=name,
            notes=list(payload.get("notes") or []),
        )
        session.commit()
        session.refresh(project)
        snapshot = _snapshot(project)

    result = await obsidian.sync_project_async(
        ctx.vault_path,
        ctx.vault_subfolder,
        snapshot,
        auto_stash_dirty=ctx.auto_stash_dirty,
        dirty_ignore_paths=ctx.dirty_ignore_paths,
    )
    if result.status in ("ok", "noop"):
        await query.edit_message_text(f"Created '{name}'")
    elif result.status == "conflict":
        await query.edit_message_text(
            f"Created '{name}' but git rebase conflicted - see {result.path.name}"
        )
    elif result.status == "dirty":
        await query.edit_message_text(
            f"Created '{name}' but vault has uncommitted changes - "
            f"commit or stash and retry with /project {name}\n{result.message}"
        )
    else:
        await query.edit_message_text(f"Created '{name}' but sync failed: {result.message}")


async def _handle_discussion_turn(ctx: BotContext, message: Any, user_id: int) -> None:
    """Route a message through the discussion model and reply."""
    max_history = ctx.settings.discussion.max_history
    await discussion.append_user_message(user_id, message.text, max_history=max_history)

    state = discussion.get_state(user_id)
    rolling_summary = state.rolling_summary if state is not None else None
    history = list(state.recent_messages) if state is not None else []
    prefix = ""
    if state is not None and state.just_restored:
        prefix = "(recent messages were lost on restart, summary preserved)\n\n"
        state.just_restored = False

    try:
        reply = await ctx.ai_clients.discuss(
            discussion.DISCUSSION_SYSTEM_PROMPT, rolling_summary, history
        )
    except ai.AIError as exc:
        logger.warning("discuss failed: %s", exc)
        await message.reply_text(f"AI error: {exc}")
        return

    await discussion.append_assistant_message(user_id, reply, max_history=max_history)
    await discussion.compact_if_needed(user_id, ctx.ai_clients, ctx.session_factory)

    if discussion.is_exit_intent(reply):
        await discussion.exit_discussion(user_id, ctx.session_factory)
        await message.reply_text(f"{prefix}{reply}")
        await message.reply_text("exiting discussion mode")
        return

    await message.reply_text(f"{prefix}{reply}")


async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enter discussion mode for subsequent free-text messages."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    user = update.effective_user
    if user is None or update.message is None:
        return
    await discussion.enter(
        user.id,
        ctx.session_factory,
        max_history=ctx.settings.discussion.max_history,
    )
    await update.message.reply_text("entered discussion mode")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt the user to confirm wiping discussion state."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is None:
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data="clear:yes"),
                InlineKeyboardButton("No", callback_data="clear:no"),
            ]
        ]
    )
    await update.message.reply_text(
        "Clear discussion history and rolling summary?",
        reply_markup=keyboard,
    )


async def handle_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve the /clear yes/no confirmation."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != "clear":
        return
    decision = parts[1]
    user = update.effective_user
    if user is None:
        return
    if decision == "yes":
        await discussion.exit_discussion(user.id, ctx.session_factory, clear_summary=True)
        await query.edit_message_text("cleared")
    else:
        await query.edit_message_text("cancelled")


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Summarize the active discussion and prompt the user for a target project."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    message = update.message
    user = update.effective_user
    if message is None or user is None:
        return

    state = discussion.get_state(user.id)
    if state is None or (not state.recent_messages and not state.rolling_summary):
        await message.reply_text("nothing to save")
        return

    history = list(state.recent_messages)
    try:
        bullets = await ctx.ai_clients.summarize_discussion(history, state.rolling_summary)
    except ai.AIError as exc:
        logger.warning("summarize_discussion failed: %s", exc)
        await message.reply_text(f"AI error: {exc}")
        return

    if not bullets:
        await message.reply_text("nothing to save")
        return

    with ctx.session_factory() as session:
        store.set_state(session, STATE_PENDING_SAVE, {"bullets": bullets})
        store.set_state(session, STATE_AWAITING_SAVE_NAME, False)
        projects = store.list_projects(session)
        session.commit()

    projects.sort(key=lambda p: p.updated_at, reverse=True)
    top = projects[:5]
    rows: list[list[InlineKeyboardButton]] = []
    for project in top:
        rows.append(
            [
                InlineKeyboardButton(
                    project.name,
                    callback_data=f"save:proj:{project.slug}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Type name", callback_data="save:custom")])
    rows.append([InlineKeyboardButton("Cancel", callback_data="save:cancel")])

    preview = "\n".join(f"- {bullet}" for bullet in bullets)
    await message.reply_text(
        f"Save these notes?\n{preview}\n\nTo which project?",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /save target-project inline keyboard."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) < 2 or parts[0] != "save":
        return
    action = parts[1]

    with ctx.session_factory() as session:
        payload = store.get_state(session, STATE_PENDING_SAVE)
        if payload is None:
            await query.edit_message_text("(no pending save)")
            return

        if action == "cancel":
            store.set_state(session, STATE_PENDING_SAVE, None)
            store.set_state(session, STATE_AWAITING_SAVE_NAME, False)
            session.commit()
            await query.edit_message_text("cancelled")
            return

        if action == "custom":
            store.set_state(session, STATE_AWAITING_SAVE_NAME, True)
            session.commit()
            await query.edit_message_text("send the project name as the next message")
            return

        if action != "proj" or len(parts) != 3:
            return

        slug = parts[2]
        bullets = list(payload.get("bullets") or [])
        project = store.get_project(session, slug)
        if project is None:
            await query.edit_message_text("project not found")
            return

        store.set_state(session, STATE_PENDING_SAVE, None)
        store.set_state(session, STATE_AWAITING_SAVE_NAME, False)
        updated = store.update_project(session, project.id, notes=bullets)
        session.commit()
        session.refresh(updated)
        snapshot = _snapshot(updated)
        name = updated.name

    result = await obsidian.sync_project_async(
        ctx.vault_path,
        ctx.vault_subfolder,
        snapshot,
        auto_stash_dirty=ctx.auto_stash_dirty,
        dirty_ignore_paths=ctx.dirty_ignore_paths,
    )
    if result.status in ("ok", "noop"):
        await query.edit_message_text(f"saved to '{name}'")
    elif result.status == "conflict":
        await query.edit_message_text(
            f"saved to '{name}' but git rebase conflicted - see {result.path.name}"
        )
    elif result.status == "dirty":
        await query.edit_message_text(
            f"saved to '{name}' but vault has uncommitted changes - "
            f"commit or stash and retry with /project {name}\n{result.message}"
        )
    else:
        await query.edit_message_text(f"saved to '{name}' but sync failed: {result.message}")


async def _save_to_named_project(ctx: BotContext, message: Any, project_name: str) -> None:
    """Consume a pending save by creating or updating a project by name."""
    if not project_name:
        await message.reply_text("empty name, try /save again")
        with ctx.session_factory() as session:
            store.set_state(session, STATE_AWAITING_SAVE_NAME, False)
            session.commit()
        return

    with ctx.session_factory() as session:
        payload = store.get_state(session, STATE_PENDING_SAVE)
        store.set_state(session, STATE_AWAITING_SAVE_NAME, False)
        store.set_state(session, STATE_PENDING_SAVE, None)
        if payload is None:
            session.commit()
            await message.reply_text("(no pending save)")
            return

        bullets = list(payload.get("bullets") or [])
        existing = store.get_project(session, project_name)
        if existing is None:
            project = store.create_project(session, name=project_name, notes=bullets)
        else:
            project = store.update_project(session, existing.id, notes=bullets)
        session.commit()
        session.refresh(project)
        snapshot = _snapshot(project)
        name = project.name

    result = await obsidian.sync_project_async(
        ctx.vault_path,
        ctx.vault_subfolder,
        snapshot,
        auto_stash_dirty=ctx.auto_stash_dirty,
        dirty_ignore_paths=ctx.dirty_ignore_paths,
    )
    if result.status in ("ok", "noop"):
        await message.reply_text(f"saved to '{name}'")
    elif result.status == "conflict":
        await message.reply_text(
            f"saved to '{name}' but git rebase conflicted - see {result.path.name}"
        )
    elif result.status == "dirty":
        await message.reply_text(
            f"saved to '{name}' but vault has uncommitted changes - "
            f"commit or stash and retry with /project {name}\n{result.message}"
        )
    else:
        await message.reply_text(f"saved to '{name}' but sync failed: {result.message}")
