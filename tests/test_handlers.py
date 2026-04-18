from __future__ import annotations

from pathlib import Path
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
        capture=config.CaptureSettings(fuzzy_threshold=85),
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="projects"),
    )


def _make_ctx(tmp_path: Path) -> tuple[handlers.BotContext, sessionmaker]:
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "brain.db"
    engine = store.init_db(db)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    ctx = handlers.BotContext(
        settings=_make_settings(vault),
        ai_clients=MagicMock(),
        session_factory=session_factory,
        vault_path=vault,
        vault_subfolder="projects",
    )
    return ctx, session_factory


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


def _fake_callback_context(
    ctx: handlers.BotContext,
    *,
    user_id: int,
    data: str,
) -> tuple[MagicMock, MagicMock]:
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    tg_ctx = MagicMock()
    tg_ctx.bot_data = {handlers.CTX_KEY: ctx}
    return update, tg_ctx


async def test_unauthorized_user_is_silently_dropped(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, user_id=999, text="ignored\nnote")

    await handlers.handle_text_message(update, tg_ctx)

    update.message.reply_text.assert_not_called()


async def test_matched_project_appends_notes_and_replies_ok(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    with session_factory() as session:
        store.create_project(session, name="Taskbot")
        session.commit()

    sync_result = obsidian.SyncResult(
        status="ok",
        path=ctx.vault_path / "projects" / "taskbot.md",
    )
    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="Taskbot\nremember to fix the bug")

    sync_mock = AsyncMock(return_value=sync_result)
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_text_message(update, tg_ctx)

    sync_mock.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()

    reply = update.message.reply_text.await_args.args[0]
    assert "Taskbot" in reply
    assert "note" in reply.lower()

    with session_factory() as session:
        project = store.get_project(session, "Taskbot")
        assert project is not None
        assert "remember to fix the bug" in project.notes


async def test_typo_selector_matches_via_fuzzy_and_appends_notes(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    with session_factory() as session:
        store.create_project(session, name="facturabot")
        session.commit()

    sync_result = obsidian.SyncResult(
        status="ok",
        path=ctx.vault_path / "projects" / "facturabot.md",
    )
    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="facturaabot\nfix invoice parser")

    sync_mock = AsyncMock(return_value=sync_result)
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_text_message(update, tg_ctx)

    sync_mock.assert_awaited_once()
    reply = update.message.reply_text.await_args.args[0]
    assert "facturabot" in reply

    with session_factory() as session:
        project = store.get_project(session, "facturabot")
        assert project is not None
        assert "fix invoice parser" in project.notes


async def test_single_line_message_is_rejected(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    with session_factory() as session:
        store.create_project(session, name="Taskbot")
        session.commit()

    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="Taskbot")

    sync_mock = AsyncMock()
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_text_message(update, tg_ctx)

    sync_mock.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "line 1" in reply
    assert "notes" in reply.lower()

    with session_factory() as session:
        project = store.get_project(session, "Taskbot")
        assert project is not None
        assert project.notes == []


async def test_no_match_stores_pending_confirmation(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(
        ctx, user_id=42, text="NewThing\nfirst spark", message_id=77
    )

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
    assert stored == {"name": "NewThing", "notes": ["first spark"]}


async def test_confirmation_yes_creates_project_with_name_and_notes(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    with session_factory() as session:
        store.set_state(
            session,
            f"{handlers.STATE_PENDING_PREFIX}77",
            {"name": "NewThing", "notes": ["first spark"]},
        )
        session.commit()

    sync_result = obsidian.SyncResult(
        status="ok",
        path=ctx.vault_path / "projects" / "newthing.md",
    )
    update, tg_ctx = _fake_callback_context(ctx, user_id=42, data="confirm:yes:77")

    sync_mock = AsyncMock(return_value=sync_result)
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_confirmation_callback(update, tg_ctx)

    sync_mock.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    reply = update.callback_query.edit_message_text.await_args.args[0]
    assert "NewThing" in reply

    with session_factory() as session:
        project = store.get_project(session, "NewThing")
        assert project is not None
        assert project.name == "NewThing"
        assert project.notes == ["first spark"]
        assert project.description is None
        assert project.stack == []
        assert project.tags == []
        assert project.status is None
        cleared = store.get_state(session, f"{handlers.STATE_PENDING_PREFIX}77")
        assert cleared is None


async def test_confirmation_no_cancels_without_creating(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    with session_factory() as session:
        store.set_state(
            session,
            f"{handlers.STATE_PENDING_PREFIX}77",
            {"name": "NewThing", "notes": ["first spark"]},
        )
        session.commit()

    update, tg_ctx = _fake_callback_context(ctx, user_id=42, data="confirm:no:77")

    sync_mock = AsyncMock()
    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_confirmation_callback(update, tg_ctx)

    sync_mock.assert_not_called()
    reply = update.callback_query.edit_message_text.await_args.args[0]
    assert "cancelled" in reply.lower()

    with session_factory() as session:
        project = store.get_project(session, "NewThing")
        assert project is None
        cleared = store.get_state(session, f"{handlers.STATE_PENDING_PREFIX}77")
        assert cleared is None


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
