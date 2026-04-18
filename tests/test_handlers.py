from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import sessionmaker
from telegram import InlineKeyboardMarkup

from secondbrain import config, handlers, obsidian, store


def _make_settings(vault: Path) -> config.Settings:
    return config.Settings(
        log_level="debug",
        telegram=config.TelegramSettings(token="t", allowed_user_id=42),
        ai=config.AISettings(
            categorization=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            discussion=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            timeout_seconds=30,
        ),
        discussion=config.DiscussionSettings(max_history=20, stale_minutes=30),
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="projects"),
    )


def _make_ctx(
    tmp_path: Path,
    category_payload: dict[str, Any],
) -> tuple[handlers.BotContext, AsyncMock, Any]:
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "brain.db"
    engine = store.init_db(db)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    categorize = AsyncMock(return_value=category_payload)
    ai_clients = MagicMock()
    ai_clients.categorize = categorize

    ctx = handlers.BotContext(
        settings=_make_settings(vault),
        ai_clients=ai_clients,
        session_factory=session_factory,
        vault_path=vault,
        vault_subfolder="projects",
    )
    return ctx, categorize, session_factory


def _fake_update_context(
    ctx: handlers.BotContext,
    *,
    user_id: int,
    text: str,
    message_id: int = 1,
) -> tuple[MagicMock, MagicMock]:
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.message_id = message_id
    update.message.reply_text = AsyncMock()

    tg_ctx = MagicMock()
    tg_ctx.bot_data = {handlers.CTX_KEY: ctx}
    return update, tg_ctx


async def test_unauthorized_user_is_silently_dropped(tmp_path: Path) -> None:
    ctx, categorize, _ = _make_ctx(tmp_path, {"intent": "note", "name": "whatever"})
    update, tg_ctx = _fake_update_context(ctx, user_id=999, text="ignored")

    await handlers.handle_text_message(update, tg_ctx)

    update.message.reply_text.assert_not_called()
    categorize.assert_not_called()


async def test_note_for_existing_project_updates_and_syncs(tmp_path: Path) -> None:
    payload = {
        "intent": "note",
        "name": "Taskbot",
        "notes": ["remember to fix the bug"],
    }
    ctx, categorize, session_factory = _make_ctx(tmp_path, payload)

    with session_factory() as session:
        store.create_project(session, name="Taskbot")
        session.commit()

    vault = ctx.vault_path
    sync_result = obsidian.SyncResult(
        status="ok",
        path=vault / "projects" / "taskbot.md",
    )
    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="remember to fix the bug")

    sync_mock = AsyncMock(return_value=sync_result)
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_text_message(update, tg_ctx)

    categorize.assert_awaited_once()
    sync_mock.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()

    reply = update.message.reply_text.await_args.args[0]
    assert "Taskbot" in reply
    assert "note" in reply.lower()

    with session_factory() as session:
        project = store.get_project(session, "Taskbot")
        assert project is not None
        assert "remember to fix the bug" in project.notes


async def test_note_for_new_project_stores_pending_and_asks(tmp_path: Path) -> None:
    payload = {
        "intent": "note",
        "name": "NewThing",
        "description": "a new project idea",
        "notes": ["first spark"],
    }
    ctx, _, session_factory = _make_ctx(tmp_path, payload)
    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="first spark", message_id=77)

    sync_mock = AsyncMock()
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_text_message(update, tg_ctx)

    sync_mock.assert_not_called()
    update.message.reply_text.assert_awaited_once()

    call = update.message.reply_text.await_args
    prompt = call.args[0]
    assert "Create" in prompt
    assert "NewThing" in prompt

    markup = call.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "confirm:yes:77" in button_data
    assert "confirm:no:77" in button_data

    with session_factory() as session:
        stored = store.get_state(session, f"{handlers.STATE_PENDING_PREFIX}77")

    assert stored is not None
    assert stored["name"] == "NewThing"
    assert stored["notes"] == ["first spark"]


def test_parse_capture_message_single_line_has_no_notes() -> None:
    selector, notes = handlers.parse_capture_message("morning-news")
    assert selector == "morning-news"
    assert notes == []


def test_parse_capture_message_two_lines_yields_one_note() -> None:
    selector, notes = handlers.parse_capture_message("morning-news\nfix dedupe")
    assert selector == "morning-news"
    assert notes == ["fix dedupe"]


def test_parse_capture_message_two_paragraphs_yield_two_notes() -> None:
    selector, notes = handlers.parse_capture_message("morning-news\nfix dedupe\n\nbump feed log")
    assert selector == "morning-news"
    assert notes == ["fix dedupe", "bump feed log"]


def test_parse_capture_message_blank_line_groups_paragraphs() -> None:
    text = "morning-news\nline one\nline two\n\nsecond paragraph\nwith wrap"
    selector, notes = handlers.parse_capture_message(text)
    assert selector == "morning-news"
    assert notes == ["line one\nline two", "second paragraph\nwith wrap"]


def test_parse_capture_message_trims_leading_and_trailing_blank_lines() -> None:
    text = "\n\nmorning-news\nfix dedupe\n\n\n"
    selector, notes = handlers.parse_capture_message(text)
    assert selector == "morning-news"
    assert notes == ["fix dedupe"]


def test_parse_capture_message_collapses_multiple_blank_separators() -> None:
    text = "morning-news\nfirst\n\n\n\nsecond"
    selector, notes = handlers.parse_capture_message(text)
    assert selector == "morning-news"
    assert notes == ["first", "second"]


def test_parse_capture_message_empty_input() -> None:
    assert handlers.parse_capture_message("") == ("", [])
    assert handlers.parse_capture_message("\n\n\n") == ("", [])
