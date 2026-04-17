"""Telegram bot bootstrap.

Builds the python-telegram-bot ``Application``, wires handlers from
:mod:`secondbrain.handlers`, and runs the polling loop. The CLI's ``run``
command is the sole caller.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from sqlalchemy.orm import sessionmaker
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from secondbrain import ai, config, handlers, store
from secondbrain.config import Settings

logger = logging.getLogger(__name__)


def _build_ai_config(settings: Settings) -> ai.AIConfig:
    return ai.AIConfig(
        categorization=ai.AITierConfig(
            base_url=settings.ai.categorization.base_url,
            api_key=settings.ai.categorization.api_key,
            model=settings.ai.categorization.model,
        ),
        discussion=ai.AITierConfig(
            base_url=settings.ai.discussion.base_url,
            api_key=settings.ai.discussion.api_key,
            model=settings.ai.discussion.model,
        ),
        timeout_seconds=settings.ai.timeout_seconds,
    )


def _build_application(settings: Settings) -> tuple[Application, handlers.BotContext]:
    engine = store.init_db(config.db_path())
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    ai_clients = ai.AIClients(_build_ai_config(settings))

    ctx = handlers.BotContext(
        settings=settings,
        ai_clients=ai_clients,
        session_factory=session_factory,
        vault_path=settings.obsidian.vault_path,
        vault_subfolder=settings.obsidian.subfolder,
    )

    application = Application.builder().token(settings.telegram.token).build()
    application.bot_data[handlers.CTX_KEY] = ctx

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(
        CallbackQueryHandler(
            handlers.handle_confirmation_callback,
            pattern=r"^confirm:",
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text_message)
    )

    return application, ctx


async def run_bot(settings: Settings) -> None:
    """Start the bot and block on the polling loop until SIGINT/SIGTERM."""
    application, _ctx = _build_application(settings)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Some platforms (notably Windows) do not support signal handlers.
            pass

    logger.info("starting telegram polling")
    async with application:
        await application.start()
        updater = application.updater
        if updater is None:
            raise RuntimeError("application has no updater; polling requires one")
        await updater.start_polling()
        try:
            await stop_event.wait()
        finally:
            logger.info("stopping telegram polling")
            await updater.stop()
            await application.stop()
