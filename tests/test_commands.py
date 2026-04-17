from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import sessionmaker

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
    user_id: int = 42,
    chat_id: int = 42,
    args: list[str] | None = None,
) -> tuple[MagicMock, MagicMock]:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()

    tg_ctx = MagicMock()
    tg_ctx.bot_data = {handlers.CTX_KEY: ctx}
    tg_ctx.args = args or []
    tg_ctx.bot.send_document = AsyncMock()
    return update, tg_ctx


async def test_start_first_use_sends_welcome_then_short_ack(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx)

    await handlers.start_command(update, tg_ctx)
    first = update.message.reply_text.await_args.args[0]
    assert "welcome" in first.lower()

    with session_factory() as session:
        assert store.get_state(session, handlers.STATE_HAS_STARTED) is True

    update.message.reply_text.reset_mock()
    await handlers.start_command(update, tg_ctx)
    second = update.message.reply_text.await_args.args[0]
    assert "ready" in second.lower()
    assert "/help" in second


async def test_help_lists_all_commands(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx)

    await handlers.help_command(update, tg_ctx)

    reply = update.message.reply_text.await_args.args[0]
    for cmd in ("/start", "/help", "/projects", "/project", "/export", "/chat", "/save", "/clear"):
        assert cmd in reply


async def test_projects_empty(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx)

    await handlers.projects_command(update, tg_ctx)

    reply = update.message.reply_text.await_args.args[0]
    assert "no projects" in reply.lower()


async def test_projects_lists_alphabetized(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.create_project(session, name="Zeta", status="idea")
        store.create_project(session, name="alpha", status="active")
        store.create_project(session, name="Midway")
        session.commit()

    update, tg_ctx = _fake_update_context(ctx)
    await handlers.projects_command(update, tg_ctx)

    reply = update.message.reply_text.await_args.args[0]
    lines = reply.splitlines()
    assert lines == [
        "alpha - active",
        "Midway - no status",
        "Zeta - idea",
    ]


async def test_project_detail_existing(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.create_project(
            session,
            name="Taskbot",
            description="a tiny task tracker",
            stack=["python", "sqlite"],
            tags=["tool"],
            status="building",
            notes=["first note", "second note"],
        )
        session.commit()

    update, tg_ctx = _fake_update_context(ctx, args=["Taskbot"])
    await handlers.project_command(update, tg_ctx)

    reply = update.message.reply_text.await_args.args[0]
    assert "name: Taskbot" in reply
    assert "slug: taskbot" in reply
    assert "status: building" in reply
    assert "stack: python, sqlite" in reply
    assert "tags: tool" in reply
    assert "description: a tiny task tracker" in reply
    assert "notes: 2" in reply


async def test_project_detail_missing(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, args=["ghost"])

    await handlers.project_command(update, tg_ctx)

    reply = update.message.reply_text.await_args.args[0]
    assert "no project matches 'ghost'" in reply


async def test_export_existing_sends_document(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.create_project(
            session,
            name="Taskbot",
            status="building",
            notes=["seeded"],
        )
        session.commit()

    projects_dir = ctx.vault_path / ctx.vault_subfolder
    projects_dir.mkdir(parents=True, exist_ok=True)
    seeded = projects_dir / "taskbot.md"
    seeded.write_text("seeded content", encoding="utf-8")

    update, tg_ctx = _fake_update_context(ctx, chat_id=777, args=["Taskbot"])
    await handlers.export_command(update, tg_ctx)

    tg_ctx.bot.send_document.assert_awaited_once()
    call = tg_ctx.bot.send_document.await_args
    assert call.kwargs["chat_id"] == 777
    assert call.kwargs["filename"] == "taskbot.md"
    document = call.kwargs["document"]
    assert hasattr(document, "read")
    assert document.name == str(seeded)


async def test_export_missing_file_is_regenerated(tmp_path: Path) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.create_project(
            session,
            name="Fresh",
            status="idea",
            notes=["spark"],
        )
        session.commit()

    update, tg_ctx = _fake_update_context(ctx, args=["Fresh"])
    await handlers.export_command(update, tg_ctx)

    target = ctx.vault_path / "projects" / "fresh.md"
    assert target.exists()
    tg_ctx.bot.send_document.assert_awaited_once()
    call = tg_ctx.bot.send_document.await_args
    assert call.kwargs["filename"] == "fresh.md"


async def test_export_unknown_project(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, args=["ghost"])

    await handlers.export_command(update, tg_ctx)

    tg_ctx.bot.send_document.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "no project matches 'ghost'" in reply


async def test_commands_drop_unauthorized(tmp_path: Path) -> None:
    ctx, _ = _make_ctx(tmp_path)
    update, tg_ctx = _fake_update_context(ctx, user_id=1, args=["Taskbot"])

    await handlers.projects_command(update, tg_ctx)
    await handlers.help_command(update, tg_ctx)
    await handlers.project_command(update, tg_ctx)
    await handlers.export_command(update, tg_ctx)

    update.message.reply_text.assert_not_called()
    tg_ctx.bot.send_document.assert_not_called()


async def test_export_uses_write_project_file_when_missing(
    tmp_path: Path, monkeypatch
) -> None:
    ctx, session_factory = _make_ctx(tmp_path)
    with session_factory() as session:
        store.create_project(session, name="Gen", status="idea")
        session.commit()

    original = obsidian.write_project_file
    calls: list[str] = []

    def spy(vault_path: Path, subfolder: str, project: object) -> Path:
        calls.append("called")
        return original(vault_path, subfolder, project)

    monkeypatch.setattr(handlers.obsidian, "write_project_file", spy)

    update, tg_ctx = _fake_update_context(ctx, args=["Gen"])
    await handlers.export_command(update, tg_ctx)

    assert calls == ["called"]
    tg_ctx.bot.send_document.assert_awaited_once()
