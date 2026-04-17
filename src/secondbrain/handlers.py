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

from secondbrain import ai, obsidian, store
from secondbrain.config import Settings

logger = logging.getLogger(__name__)

CTX_KEY = "ctx"
STATE_DISCUSSION_MODE = "discussion_mode"
STATE_PENDING_PREFIX = "pending_confirmation:"

_UPDATEABLE_FIELDS = frozenset(
    {"name", "description", "status", "notes", "stack", "tags", "aliases"}
)


@dataclass(frozen=True)
class BotContext:
    """Dependencies injected into every handler via ``application.bot_data``."""

    settings: Settings
    ai_clients: ai.AIClients
    session_factory: Callable[[], Session]
    vault_path: Path
    vault_subfolder: str


@dataclass(frozen=True)
class _ProjectSnapshot:
    """Detached copy of a project so sync can run after the session closes."""

    name: str
    slug: str
    status: str | None
    stack: list[str]
    tags: list[str]
    description: str | None
    notes: list[str]


def _snapshot(project: store.Project) -> _ProjectSnapshot:
    return _ProjectSnapshot(
        name=project.name,
        slug=project.slug,
        status=project.status,
        stack=list(project.stack or []),
        tags=list(project.tags or []),
        description=project.description,
        notes=list(project.notes or []),
    )


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


def _project_metas(session: Session) -> list[ai.ProjectMeta]:
    return [
        ai.ProjectMeta(name=p.name, aliases=list(p.aliases or []))
        for p in store.list_projects(session)
    ]


def _payload_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k in _UPDATEABLE_FIELDS}


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
    """Minimal /start placeholder - task 10 fills this in."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return
    if update.message is not None:
        await update.message.reply_text("welcome, use /help")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route a free-text message: discussion mode -> categorize -> note/question branch."""
    ctx = get_ctx(context)
    if not require_allowed_user(update, ctx.settings.telegram.allowed_user_id):
        return

    message = update.message
    if message is None or not message.text:
        return

    with ctx.session_factory() as session:
        discussion_mode = bool(store.get_state(session, STATE_DISCUSSION_MODE, False))

    if discussion_mode:
        await message.reply_text("(discussion mode not yet implemented)")
        return

    with ctx.session_factory() as session:
        projects = _project_metas(session)

    try:
        payload = await ctx.ai_clients.categorize(message.text, projects=projects)
    except ai.AIError as exc:
        logger.warning("categorization failed: %s", exc)
        await message.reply_text(f"AI error: {exc}")
        return

    intent = payload.get("intent", "note")
    if intent == "question":
        await message.reply_text("looks like a question - /chat to discuss")
        return

    project_name = payload.get("name")
    project_slug = payload.get("project_slug")
    identifier = project_slug or project_name
    if not identifier:
        await message.reply_text("couldn't infer a project from this message")
        return

    with ctx.session_factory() as session:
        existing = store.get_project(session, identifier)
        if existing is None:
            pending_key = f"{STATE_PENDING_PREFIX}{message.message_id}"
            store.set_state(session, pending_key, payload)
            session.commit()
            display = project_name or project_slug or identifier
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
                f"Create '{display}'?",
                reply_markup=keyboard,
            )
            return

        fields = _payload_fields(payload)
        if project_name:
            aliases = list(fields.get("aliases") or [])
            if project_name.lower() not in {a.lower() for a in aliases}:
                aliases.append(project_name)
            fields["aliases"] = aliases

        project = store.update_project(session, existing.id, **fields)
        session.commit()
        session.refresh(project)
        snapshot = _snapshot(project)

    result = await obsidian.sync_project_async(
        ctx.vault_path, ctx.vault_subfolder, snapshot
    )
    display = project_name or snapshot.name
    if result.status in ("ok", "noop"):
        await message.reply_text(_summarize_update(payload, display))
    elif result.status == "conflict":
        await message.reply_text(
            f"Updated '{display}' but git rebase conflicted - see {result.path.name}"
        )
    else:
        await message.reply_text(
            f"Updated '{display}' but sync failed: {result.message}"
        )


async def handle_confirmation_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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

        name = payload.get("name") or payload.get("project_slug") or "untitled"
        aliases = list(payload.get("aliases") or [])
        project = store.create_project(
            session,
            name=name,
            slug=payload.get("project_slug"),
            description=payload.get("description"),
            stack=list(payload.get("stack") or []),
            tags=list(payload.get("tags") or []),
            status=payload.get("status"),
            notes=_normalize_notes(payload.get("notes")),
            aliases=aliases,
        )
        session.commit()
        session.refresh(project)
        snapshot = _snapshot(project)

    result = await obsidian.sync_project_async(
        ctx.vault_path, ctx.vault_subfolder, snapshot
    )
    if result.status in ("ok", "noop"):
        await query.edit_message_text(f"Created '{name}'")
    elif result.status == "conflict":
        await query.edit_message_text(
            f"Created '{name}' but git rebase conflicted - see {result.path.name}"
        )
    else:
        await query.edit_message_text(
            f"Created '{name}' but sync failed: {result.message}"
        )
