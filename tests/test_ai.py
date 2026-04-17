from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from secondbrain.ai import (
    AIClients,
    AIConfig,
    AIResponseError,
    AITierConfig,
    AITimeoutError,
    ProjectMeta,
    build_categorization_prompt,
    build_compaction_prompt,
    build_discussion_messages,
    parse_categorization_response,
)


def _make_config(timeout: int = 30) -> AIConfig:
    return AIConfig(
        categorization=AITierConfig(
            base_url="http://localhost/v1",
            api_key="cat-key",
            model="cat-model",
        ),
        discussion=AITierConfig(
            base_url="http://localhost/v1",
            api_key="disc-key",
            model="disc-model",
        ),
        timeout_seconds=timeout,
    )


def test_parse_clean_json() -> None:
    raw = '{"intent": "note", "name": "Test"}'
    assert parse_categorization_response(raw) == {"intent": "note", "name": "Test"}


def test_parse_json_with_surrounding_whitespace() -> None:
    raw = '  \n  {"intent": "question"}  \n  '
    assert parse_categorization_response(raw) == {"intent": "question"}


def test_parse_fenced_code_block() -> None:
    raw = 'Here is your answer:\n```json\n{"intent": "note", "name": "X"}\n```\nok'
    assert parse_categorization_response(raw) == {"intent": "note", "name": "X"}


def test_parse_balanced_brace_fallback() -> None:
    raw = 'Sure thing. The data is: {"intent": "note", "name": "Brace"} - hope it helps!'
    assert parse_categorization_response(raw) == {"intent": "note", "name": "Brace"}


def test_parse_balanced_brace_with_nested_and_strings() -> None:
    raw = (
        "Some preamble. "
        '{"intent": "note", "meta": {"tags": ["a", "b"]}, "text": "has } inside"}'
        " trailing"
    )
    parsed = parse_categorization_response(raw)
    assert parsed["intent"] == "note"
    assert parsed["meta"] == {"tags": ["a", "b"]}
    assert parsed["text"] == "has } inside"


def test_parse_malformed_raises() -> None:
    with pytest.raises(AIResponseError) as info:
        parse_categorization_response("totally not json and no braces here")
    assert "could not parse" in str(info.value)


def test_parse_malformed_long_is_truncated() -> None:
    raw = "x" * 1000
    with pytest.raises(AIResponseError) as info:
        parse_categorization_response(raw)
    assert len(str(info.value)) < 700


def test_build_categorization_includes_projects_and_aliases() -> None:
    projects = [
        ProjectMeta(name="Auth Service", aliases=["auth", "authn"]),
        ProjectMeta(name="Notes App", aliases=[]),
    ]
    messages = build_categorization_prompt("hello", projects)
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "hello"}
    system = messages[0]["content"]
    assert "Auth Service" in system
    assert "auth" in system
    assert "authn" in system
    assert "Notes App" in system


def test_build_categorization_instructs_omit_fields() -> None:
    messages = build_categorization_prompt("hi", [])
    system = messages[0]["content"]
    assert "Omit" in system
    assert "null" in system.lower()


def test_build_categorization_handles_empty_projects() -> None:
    messages = build_categorization_prompt("hi", [])
    system = messages[0]["content"]
    assert "no existing projects" in system.lower()


def test_build_discussion_injects_summary() -> None:
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    messages = build_discussion_messages("sys", "prev summary", history)
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1]["role"] == "system"
    assert "prev summary" in messages[1]["content"]
    assert messages[2:] == history


def test_build_discussion_no_summary() -> None:
    history = [{"role": "user", "content": "hi"}]
    messages = build_discussion_messages("sys", None, history)
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "hi"}


def test_build_compaction_with_prior() -> None:
    history = [
        {"role": "user", "content": "discuss auth"},
        {"role": "assistant", "content": "sure"},
    ]
    messages = build_compaction_prompt(history, "old summary")
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "old summary" in user
    assert "discuss auth" in user


def test_build_compaction_without_prior() -> None:
    history = [{"role": "user", "content": "a"}]
    messages = build_compaction_prompt(history, None)
    user = messages[1]["content"]
    assert "Previous summary" not in user
    assert "[user] a" in user


class _FakeCompletions:
    def __init__(self, delay: float, content: str = "{}") -> None:
        self._delay = delay
        self._content = content

    async def create(self, **_: Any) -> Any:
        await asyncio.sleep(self._delay)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, delay: float, content: str = "{}") -> None:
        self.chat = _FakeChat(_FakeCompletions(delay, content))


def _make_clients(
    timeout: int,
    *,
    cat_delay: float = 0.0,
    cat_content: str = "{}",
    disc_delay: float = 0.0,
    disc_content: str = "{}",
) -> AIClients:
    return AIClients(
        _make_config(timeout=timeout),
        categorization_client=_FakeClient(cat_delay, cat_content),  # type: ignore[arg-type]
        discussion_client=_FakeClient(disc_delay, disc_content),  # type: ignore[arg-type]
    )


async def test_categorize_timeout_raises() -> None:
    clients = _make_clients(timeout=1, cat_delay=5.0)
    with pytest.raises(AITimeoutError):
        await clients.categorize("hi", [])


async def test_discuss_timeout_raises() -> None:
    clients = _make_clients(timeout=1, disc_delay=5.0)
    with pytest.raises(AITimeoutError):
        await clients.discuss("sys", None, [{"role": "user", "content": "hi"}])


async def test_categorize_returns_parsed_dict() -> None:
    clients = _make_clients(timeout=5, cat_content='{"intent": "note", "name": "Foo"}')
    result = await clients.categorize("write something", [])
    assert result == {"intent": "note", "name": "Foo"}


async def test_discuss_returns_content() -> None:
    clients = _make_clients(timeout=5, disc_content="hello back")
    result = await clients.discuss("sys", None, [{"role": "user", "content": "hi"}])
    assert result == "hello back"


async def test_compact_returns_summary() -> None:
    clients = _make_clients(timeout=5, disc_content="new summary")
    result = await clients.compact([{"role": "user", "content": "x"}], None)
    assert result == "new summary"
