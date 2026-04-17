from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from secondbrain import config, discussion, handlers, obsidian, store


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    discussion.reset_for_tests()


def _make_settings(
    vault: Path, *, max_history: int = 4, stale_minutes: int = 30
) -> config.Settings:
    return config.Settings(
        log_level="debug",
        telegram=config.TelegramSettings(token="t", allowed_user_id=42),
        ai=config.AISettings(
            categorization=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            discussion=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            timeout_seconds=30,
        ),
        discussion=config.DiscussionSettings(
            max_history=max_history, stale_minutes=stale_minutes
        ),
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="projects"),
    )


def _make_ctx(tmp_path: Path, **settings_kwargs: Any) -> tuple[handlers.BotContext, Any]:
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "brain.db"
    engine = store.init_db(db)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    ai_clients = MagicMock()
    ai_clients.discuss = AsyncMock(return_value="ok")
    ai_clients.compact = AsyncMock(return_value="new summary")
    ai_clients.summarize_discussion = AsyncMock(return_value=[])

    ctx = handlers.BotContext(
        settings=_make_settings(vault, **settings_kwargs),
        ai_clients=ai_clients,
        session_factory=session_factory,
        vault_path=vault,
        vault_subfolder="projects",
    )
    return ctx, session_factory


def _fake_update_context(
    ctx: handlers.BotContext,
    *,
    user_id: int,
    text: str = "",
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


async def test_enter_and_exit_toggle_state(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    await discussion.enter(42, session_factory, max_history=4)
    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is True
    state = discussion.get_state(42)
    assert state is not None
    assert state.max_history == 4

    await discussion.append_user_message(42, "hi")
    assert len(state.recent_messages) == 1

    await discussion.exit_discussion(42, session_factory)
    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is False
    assert len(state.recent_messages) == 0


async def test_exit_with_clear_summary_wipes_rolling_summary(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)

    await discussion.enter(42, session_factory, max_history=4)
    state = discussion.get_state(42)
    assert state is not None
    state.rolling_summary = "previous summary"
    with session_factory() as session:
        store.set_state(session, discussion.STATE_ROLLING_SUMMARY, "previous summary")
        session.commit()

    await discussion.exit_discussion(42, session_factory, clear_summary=True)
    assert state.rolling_summary is None
    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_ROLLING_SUMMARY) is None


async def test_compact_if_needed_drops_half_and_updates_summary(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path, max_history=4)
    await discussion.enter(42, session_factory, max_history=4)

    await discussion.append_user_message(42, "m1", max_history=4)
    await discussion.append_assistant_message(42, "r1", max_history=4)
    await discussion.append_user_message(42, "m2", max_history=4)
    await discussion.append_assistant_message(42, "r2", max_history=4)

    state = discussion.get_state(42)
    assert state is not None
    assert len(state.recent_messages) == 4

    state.rolling_summary = "prior"
    compact_mock = AsyncMock(return_value="fresh summary")
    ctx.ai_clients.compact = compact_mock

    ran = await discussion.compact_if_needed(42, ctx.ai_clients, session_factory)
    assert ran is True

    compact_mock.assert_awaited_once()
    called_messages, prior = compact_mock.await_args.args
    assert prior == "prior"
    assert [m["content"] for m in called_messages] == ["m1", "r1"]

    assert len(state.recent_messages) == 2
    assert [m["content"] for m in state.recent_messages] == ["m2", "r2"]
    assert state.rolling_summary == "fresh summary"

    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_ROLLING_SUMMARY) == "fresh summary"


async def test_compact_if_needed_noop_when_window_not_full(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path, max_history=4)
    await discussion.enter(42, session_factory, max_history=4)
    await discussion.append_user_message(42, "m1", max_history=4)

    compact_mock = AsyncMock(return_value="should not happen")
    ctx.ai_clients.compact = compact_mock

    ran = await discussion.compact_if_needed(42, ctx.ai_clients, session_factory)
    assert ran is False
    compact_mock.assert_not_awaited()


def test_is_exit_intent_dict_field() -> None:
    assert discussion.is_exit_intent({"intent": "exit_discussion"}) is True
    assert discussion.is_exit_intent({"intent": "note"}) is False


def test_is_exit_intent_string_phrases() -> None:
    assert discussion.is_exit_intent("let's end this discussion") is True
    assert discussion.is_exit_intent("goodbye for now") is True
    assert discussion.is_exit_intent("carry on") is False
    assert discussion.is_exit_intent("") is False


async def test_restore_state_rehydrates_summary(tmp_path: Path) -> None:
    _, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.set_state(session, discussion.STATE_DISCUSSION_MODE, True)
        store.set_state(session, discussion.STATE_ROLLING_SUMMARY, "snap")
        session.commit()

    mode = await discussion.restore_state(42, session_factory, max_history=4)
    assert mode is True
    state = discussion.get_state(42)
    assert state is not None
    assert state.rolling_summary == "snap"
    assert state.just_restored is True
    assert len(state.recent_messages) == 0


async def test_stale_timer_triggers_exit(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path, stale_minutes=0)
    await discussion.enter(42, session_factory, max_history=4)

    state = discussion.get_state(42)
    assert state is not None
    state.last_activity = datetime.now(UTC) - timedelta(minutes=5)

    fired: list[int] = []

    async def on_timeout(uid: int) -> None:
        fired.append(uid)
        await discussion.exit_discussion(uid, session_factory)

    triggered = await discussion.check_stale(42, session_factory, 0, on_timeout)
    assert triggered is True
    assert fired == [42]
    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is False


async def test_stale_timer_noop_when_not_in_discussion_mode(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path, stale_minutes=0)
    await discussion.enter(42, session_factory, max_history=4)
    await discussion.exit_discussion(42, session_factory)

    fired: list[int] = []

    async def on_timeout(uid: int) -> None:
        fired.append(uid)

    triggered = await discussion.check_stale(42, session_factory, 0, on_timeout)
    assert triggered is False
    assert fired == []


async def test_chat_command_enters_discussion_mode(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, user_id=42)

    await handlers.chat_command(update, tg_ctx)

    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is True
    update.message.reply_text.assert_awaited_once()
    assert "discussion" in update.message.reply_text.await_args.args[0]


async def test_handle_text_routes_to_discussion(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    ctx.ai_clients.discuss = AsyncMock(return_value="sure, tell me more")
    await discussion.enter(42, session_factory, max_history=4)

    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="what do you think?")
    await handlers.handle_text_message(update, tg_ctx)

    ctx.ai_clients.discuss.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args.args[0]
    assert "sure" in reply

    state = discussion.get_state(42)
    assert state is not None
    assert [m["content"] for m in state.recent_messages] == [
        "what do you think?",
        "sure, tell me more",
    ]


async def test_handle_text_exit_intent_leaves_discussion(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    ctx.ai_clients.discuss = AsyncMock(return_value="goodbye then!")
    await discussion.enter(42, session_factory, max_history=4)

    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="done chatting")
    await handlers.handle_text_message(update, tg_ctx)

    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is False
    assert update.message.reply_text.await_count == 2
    last = update.message.reply_text.await_args_list[-1].args[0]
    assert "exit" in last.lower()


async def test_clear_confirm_yes_wipes_state(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    await discussion.enter(42, session_factory, max_history=4)
    state = discussion.get_state(42)
    assert state is not None
    state.rolling_summary = "to be cleared"
    with session_factory() as session:
        store.set_state(session, discussion.STATE_ROLLING_SUMMARY, "to be cleared")
        session.commit()

    update = MagicMock()
    update.effective_user.id = 42
    update.callback_query.data = "clear:yes"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    tg_ctx = MagicMock()
    tg_ctx.bot_data = {handlers.CTX_KEY: ctx}

    await handlers.handle_clear_callback(update, tg_ctx)

    with session_factory() as session:
        assert store.get_state(session, discussion.STATE_DISCUSSION_MODE) is False
        assert store.get_state(session, discussion.STATE_ROLLING_SUMMARY) is None
    assert state.rolling_summary is None


async def test_save_flow_appends_notes_and_syncs(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    bullets = ["fix the migration", "file a follow-up ticket"]
    ctx.ai_clients.summarize_discussion = AsyncMock(return_value=bullets)

    await discussion.enter(42, session_factory, max_history=4)
    await discussion.append_user_message(42, "chat about auth", max_history=4)
    await discussion.append_assistant_message(42, "ok", max_history=4)

    with session_factory() as session:
        store.create_project(session, name="Auth Service")
        session.commit()

    save_update, tg_ctx = _fake_update_context(
        ctx, user_id=42, text="/save", message_id=100
    )
    await handlers.save_command(save_update, tg_ctx)

    ctx.ai_clients.summarize_discussion.assert_awaited_once()
    save_update.message.reply_text.assert_awaited_once()

    with session_factory() as session:
        pending = store.get_state(session, handlers.STATE_PENDING_SAVE)
    assert pending is not None
    assert pending["bullets"] == bullets

    sync_result = obsidian.SyncResult(
        status="ok", path=ctx.vault_path / "projects" / "auth-service.md"
    )
    sync_mock = AsyncMock(return_value=sync_result)

    cb_update = MagicMock()
    cb_update.effective_user.id = 42
    cb_update.callback_query.data = "save:proj:auth-service"
    cb_update.callback_query.answer = AsyncMock()
    cb_update.callback_query.edit_message_text = AsyncMock()

    with patch.object(obsidian, "sync_project_async", sync_mock):
        await handlers.handle_save_callback(cb_update, tg_ctx)

    sync_mock.assert_awaited_once()
    cb_update.callback_query.edit_message_text.assert_awaited_once()

    with session_factory() as session:
        project = store.get_project(session, "auth-service")
        assert project is not None
        assert project.notes == bullets
        assert store.get_state(session, handlers.STATE_PENDING_SAVE) is None


async def test_save_with_no_active_discussion_replies_nothing(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, user_id=42, text="/save")
    await handlers.save_command(update, tg_ctx)
    update.message.reply_text.assert_awaited_once()
    assert "nothing" in update.message.reply_text.await_args.args[0].lower()
