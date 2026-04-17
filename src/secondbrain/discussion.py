"""In-memory discussion mode state and stale-timer management.

Discussion mode keeps a rolling summary plus a bounded window of recent
messages per user. The recent window lives in process memory only (lost on
restart); the rolling summary and active flag are persisted to SQLite so a
restart can resume the conversation with preserved context.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from secondbrain import ai, store

logger = logging.getLogger(__name__)

STATE_DISCUSSION_MODE = "discussion_mode"
STATE_ROLLING_SUMMARY = "discussion_rolling_summary"

DISCUSSION_SYSTEM_PROMPT = (
    "You are a helpful assistant embedded in a personal project tracker. "
    "Discuss the user's projects, challenge assumptions, and help them think "
    "through ideas. Keep replies concise and conversational. When the user "
    "signals they want to end the conversation, acknowledge and wrap up."
)

_EXIT_PHRASES: frozenset[str] = frozenset(
    {
        "exit discussion",
        "end discussion",
        "let's end this",
        "stop discussion",
        "we're done",
        "i'm done",
        "goodbye",
        "/exit",
    }
)

SessionFactory = Callable[[], Session]


@dataclass
class ConversationState:
    """Per-user in-memory discussion context."""

    max_history: int
    recent_messages: deque[dict[str, str]] = field(init=False)
    rolling_summary: str | None = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    just_restored: bool = False

    def __post_init__(self) -> None:
        self.recent_messages = deque(maxlen=self.max_history)


_states: dict[int, ConversationState] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def get_state(user_id: int) -> ConversationState | None:
    """Return the in-memory state for ``user_id`` or None if not initialized."""
    return _states.get(user_id)


def _ensure_state(user_id: int, max_history: int) -> ConversationState:
    state = _states.get(user_id)
    if state is None:
        state = ConversationState(max_history=max_history)
        _states[user_id] = state
    return state


def reset_for_tests() -> None:
    """Drop all in-memory state. Tests use this to isolate runs."""
    _states.clear()


async def append_user_message(user_id: int, text: str, *, max_history: int = 20) -> None:
    """Append a user turn to the recent window and reset the activity timer."""
    state = _ensure_state(user_id, max_history)
    state.recent_messages.append({"role": "user", "content": text})
    state.last_activity = _now()
    state.just_restored = False


async def append_assistant_message(user_id: int, text: str, *, max_history: int = 20) -> None:
    """Append an assistant turn to the recent window and reset the activity timer."""
    state = _ensure_state(user_id, max_history)
    state.recent_messages.append({"role": "assistant", "content": text})
    state.last_activity = _now()


async def get_context_messages(
    user_id: int,
    *,
    system_prompt: str = DISCUSSION_SYSTEM_PROMPT,
) -> list[dict[str, str]]:
    """Build the messages list for a discussion turn (system + summary + history)."""
    state = _states.get(user_id)
    if state is None:
        return ai.build_discussion_messages(system_prompt, None, [])
    return ai.build_discussion_messages(
        system_prompt,
        state.rolling_summary,
        list(state.recent_messages),
    )


async def compact_if_needed(
    user_id: int,
    ai_clients: ai.AIClients,
    session_factory: SessionFactory,
) -> bool:
    """Compact the oldest half of the window into the rolling summary when full.

    Returns True if compaction ran, False otherwise. The updated rolling
    summary is persisted to the state table so it survives restarts.
    """
    state = _states.get(user_id)
    if state is None:
        return False
    maxlen = state.recent_messages.maxlen
    if maxlen is None or len(state.recent_messages) < maxlen:
        return False

    half = max(1, maxlen // 2)
    oldest: list[dict[str, str]] = []
    for _ in range(half):
        if not state.recent_messages:
            break
        oldest.append(state.recent_messages.popleft())

    new_summary = await ai_clients.compact(oldest, state.rolling_summary)
    state.rolling_summary = new_summary.strip() or state.rolling_summary

    with session_factory() as session:
        store.set_state(session, STATE_ROLLING_SUMMARY, state.rolling_summary)
        session.commit()
    return True


async def enter(
    user_id: int,
    session_factory: SessionFactory,
    *,
    max_history: int = 20,
) -> ConversationState:
    """Flip the discussion_mode flag on and ensure in-memory state exists."""
    state = _ensure_state(user_id, max_history)
    state.last_activity = _now()
    with session_factory() as session:
        store.set_state(session, STATE_DISCUSSION_MODE, True)
        session.commit()
    return state


async def exit_discussion(
    user_id: int,
    session_factory: SessionFactory,
    *,
    clear_summary: bool = False,
) -> None:
    """Flip the discussion_mode flag off and clear in-memory recent messages.

    When ``clear_summary`` is True (as used by /clear) the rolling summary is
    wiped from both memory and SQLite. Otherwise the summary is preserved so
    a future /chat session can pick up where this one left off.
    """
    state = _states.get(user_id)
    if state is not None:
        state.recent_messages.clear()
        if clear_summary:
            state.rolling_summary = None
        state.just_restored = False
    with session_factory() as session:
        store.set_state(session, STATE_DISCUSSION_MODE, False)
        if clear_summary:
            store.set_state(session, STATE_ROLLING_SUMMARY, None)
        session.commit()


async def restore_state(
    user_id: int,
    session_factory: SessionFactory,
    *,
    max_history: int = 20,
) -> bool:
    """Read persisted discussion state into memory on startup.

    Recent messages are lost across restarts - ``just_restored`` is set so the
    handler can inform the user on their first post-restart interaction.
    Returns the restored discussion_mode flag.
    """
    state = _ensure_state(user_id, max_history)
    with session_factory() as session:
        mode = bool(store.get_state(session, STATE_DISCUSSION_MODE, False))
        summary = store.get_state(session, STATE_ROLLING_SUMMARY, None)
    state.rolling_summary = summary if isinstance(summary, str) else None
    state.last_activity = _now()
    state.just_restored = mode and state.rolling_summary is not None
    return mode


def is_exit_intent(ai_response: dict[str, Any] | str) -> bool:
    """Detect explicit exit intent from a JSON intent or natural-language sniff.

    The categorization tier may emit ``intent == "exit_discussion"``. For the
    discussion model's free-text reply we fall back to matching common English
    wrap-up phrases.
    """
    text = ""
    if isinstance(ai_response, dict):
        if ai_response.get("intent") == "exit_discussion":
            return True
        content = ai_response.get("content") or ai_response.get("reply") or ""
        text = str(content)
    else:
        text = str(ai_response or "")

    lowered = text.strip().lower()
    if not lowered:
        return False
    for phrase in _EXIT_PHRASES:
        if phrase in lowered:
            return True
    return False


async def check_stale(
    user_id: int,
    session_factory: SessionFactory,
    stale_minutes: int,
    on_timeout: Callable[[int], Awaitable[None]],
    *,
    now: datetime | None = None,
) -> bool:
    """Fire ``on_timeout`` if the discussion has been idle past ``stale_minutes``."""
    state = _states.get(user_id)
    if state is None:
        return False
    with session_factory() as session:
        mode = bool(store.get_state(session, STATE_DISCUSSION_MODE, False))
    if not mode:
        return False
    current = now or _now()
    if (current - state.last_activity).total_seconds() >= stale_minutes * 60:
        await on_timeout(user_id)
        return True
    return False


async def stale_timer_task(
    user_id: int,
    session_factory: SessionFactory,
    stale_minutes: int,
    on_timeout: Callable[[int], Awaitable[None]],
    *,
    poll_interval: float = 60.0,
) -> None:
    """Background task: poll once per minute and fire on_timeout when stale."""
    while True:
        try:
            await asyncio.sleep(poll_interval)
            await check_stale(user_id, session_factory, stale_minutes, on_timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stale_timer_task errored for user_id=%s", user_id)
