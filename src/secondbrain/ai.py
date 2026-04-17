"""AI provider wrapper.

Thin layer around the ``openai`` async client with two tiers (categorization and
discussion), prompt builders, and a defensive JSON response parser.

This module is a leaf - it does not import from ``config`` or ``store``. Call
sites build an :class:`AIConfig` from settings and pass it to :class:`AIClients`.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


class AIError(Exception):
    """Base class for AI provider errors."""


class AITimeoutError(AIError):
    """Raised when an AI call exceeds the configured timeout."""


class AIResponseError(AIError):
    """Raised when a categorization response cannot be parsed as JSON."""


@dataclass(frozen=True)
class ProjectMeta:
    """Minimal project info used to build categorization prompts.

    Kept decoupled from the SQLAlchemy model so ``ai.py`` stays leaf-level.
    """

    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AITierConfig:
    """Configuration for a single AI tier (categorization or discussion)."""

    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class AIConfig:
    """Configuration for both AI tiers plus the shared request timeout."""

    categorization: AITierConfig
    discussion: AITierConfig
    timeout_seconds: int = 30


_CATEGORIZATION_SYSTEM = """\
You are a categorization assistant for a personal project tracker.

Given the user's message and a list of known projects (with their aliases),
decide whether the message is a note to store or a question to discuss, and
extract structured project data.

Respond with a single JSON object only - no prose, no code fences - with these
fields:
- intent: "note" or "question"
- project_slug: stable identifier if the message matches an existing project
- name: project name (prefer matching an existing alias)
- description: short project description
- stack: list of technologies/languages
- tags: list of free-form tags
- status: short lifecycle label (e.g. "idea", "in-progress", "blocked", "done")
- notes: list of new note strings extracted from the message

Omit any field you cannot confidently infer from the message. Do not emit null
or empty placeholders - if you cannot infer a value, leave the key out of the
JSON entirely. Omitted fields are treated as "no change" by the caller.
"""


_COMPACTION_SYSTEM = """\
You are a summarization assistant. Produce an updated rolling summary of the
conversation so far, preserving key decisions, open questions, and any project
context mentioned. Be concise - aim for a few short paragraphs. Return plain
text only, no JSON, no code fences.
"""


_SAVE_SUMMARY_SYSTEM = """\
You are a note-taking assistant. Given a conversation transcript (and an
optional earlier summary), distil the most useful takeaways into concise
bullet points suitable for appending to a project's notes file. Return one
bullet per line, each starting with '- '. No prose, no headers, no code
fences, no JSON.
"""


def _format_projects_block(projects: list[ProjectMeta]) -> str:
    if not projects:
        return "(no existing projects yet)"
    lines: list[str] = []
    for project in projects:
        if project.aliases:
            aliases = ", ".join(project.aliases)
            lines.append(f"- {project.name} (aliases: {aliases})")
        else:
            lines.append(f"- {project.name}")
    return "\n".join(lines)


def build_categorization_prompt(
    user_message: str,
    projects: list[ProjectMeta],
) -> list[dict[str, str]]:
    """Build the messages list for a categorization call."""
    projects_block = _format_projects_block(projects)
    system = (
        f"{_CATEGORIZATION_SYSTEM}\n"
        f"Known projects:\n{projects_block}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]


def build_discussion_messages(
    system_prompt: str,
    rolling_summary: str | None,
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Assemble discussion messages: system prompt, optional summary, history."""
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if rolling_summary:
        messages.append(
            {
                "role": "system",
                "content": f"Conversation summary so far:\n{rolling_summary}",
            }
        )
    messages.extend(history)
    return messages


def build_save_summary_prompt(
    history: list[dict[str, str]],
    prior_summary: str | None,
) -> list[dict[str, str]]:
    """Build messages for the /save summarization: bullet notes for a project."""
    transcript_lines: list[str] = []
    for message in history:
        role = message.get("role", "user")
        content = message.get("content", "")
        transcript_lines.append(f"[{role}] {content}")
    transcript = "\n".join(transcript_lines) or "(no messages)"

    if prior_summary:
        user_content = (
            "Earlier conversation summary:\n"
            f"{prior_summary}\n\n"
            "Recent transcript:\n"
            f"{transcript}\n\n"
            "Produce concise bullet-point notes."
        )
    else:
        user_content = (
            "Transcript:\n"
            f"{transcript}\n\n"
            "Produce concise bullet-point notes."
        )

    return [
        {"role": "system", "content": _SAVE_SUMMARY_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def parse_bullets(text: str) -> list[str]:
    """Extract bullet lines from ``text``. Falls back to the full text if empty."""
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            bullets.append(stripped[2:].strip())
        elif stripped.startswith(("-", "*")):
            bullets.append(stripped[1:].strip())
    if bullets:
        return [b for b in bullets if b]
    fallback = text.strip()
    return [fallback] if fallback else []


def build_compaction_prompt(
    messages: list[dict[str, str]],
    prior_summary: str | None,
) -> list[dict[str, str]]:
    """Build messages that ask the model to produce an updated rolling summary."""
    transcript_lines: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        transcript_lines.append(f"[{role}] {content}")
    transcript = "\n".join(transcript_lines) or "(no messages)"

    if prior_summary:
        user_content = (
            "Previous summary:\n"
            f"{prior_summary}\n\n"
            "New messages to fold into the summary:\n"
            f"{transcript}\n\n"
            "Return the updated summary."
        )
    else:
        user_content = (
            "Messages to summarize:\n"
            f"{transcript}\n\n"
            "Return a concise rolling summary."
        )

    return [
        {"role": "system", "content": _COMPACTION_SYSTEM},
        {"role": "user", "content": user_content},
    ]


_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_first_json_object(text: str) -> str | None:
    """Return the substring covering the first balanced {...} block, or None."""
    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start != -1:
                return text[start : index + 1]
    return None


def parse_categorization_response(raw: str) -> dict[str, Any]:
    """Parse a categorization response with three-tier fallback.

    1. ``json.loads`` of the stripped text.
    2. ``json.loads`` of the first fenced ``json`` code block.
    3. ``json.loads`` of the first balanced ``{...}`` block.

    Raises :class:`AIResponseError` if none of the three parses succeeds.
    """
    stripped = raw.strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    match = _JSON_FENCE_RE.search(raw)
    if match is not None:
        try:
            parsed = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    block = _extract_first_json_object(raw)
    if block is not None:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    truncated = raw[:500]
    raise AIResponseError(f"could not parse AI response as JSON: {truncated!r}")


class AIClients:
    """Two ``AsyncOpenAI`` clients plus helper methods wrapped with timeouts."""

    def __init__(
        self,
        config: AIConfig,
        *,
        categorization_client: AsyncOpenAI | None = None,
        discussion_client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        self._categorization_client = categorization_client or AsyncOpenAI(
            base_url=config.categorization.base_url,
            api_key=config.categorization.api_key,
        )
        self._discussion_client = discussion_client or AsyncOpenAI(
            base_url=config.discussion.base_url,
            api_key=config.discussion.api_key,
        )

    @property
    def timeout_seconds(self) -> int:
        return self._config.timeout_seconds

    async def _with_timeout(self, coro: Any) -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=self._config.timeout_seconds)
        except TimeoutError as exc:
            raise AITimeoutError(
                f"AI call exceeded {self._config.timeout_seconds}s timeout"
            ) from exc

    @staticmethod
    def _extract_content(response: Any) -> str:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        return getattr(message, "content", "") or ""

    async def categorize(
        self,
        user_message: str,
        projects: list[ProjectMeta],
    ) -> dict[str, Any]:
        """Run the categorization model and return the parsed JSON payload."""
        messages = build_categorization_prompt(user_message, projects)
        response = await self._with_timeout(
            self._categorization_client.chat.completions.create(
                model=self._config.categorization.model,
                messages=messages,
            )
        )
        return parse_categorization_response(self._extract_content(response))

    async def discuss(
        self,
        system_prompt: str,
        rolling_summary: str | None,
        history: list[dict[str, str]],
    ) -> str:
        """Run the discussion model and return its reply text."""
        messages = build_discussion_messages(system_prompt, rolling_summary, history)
        response = await self._with_timeout(
            self._discussion_client.chat.completions.create(
                model=self._config.discussion.model,
                messages=messages,
            )
        )
        return self._extract_content(response)

    async def compact(
        self,
        messages: list[dict[str, str]],
        prior_summary: str | None,
    ) -> str:
        """Produce an updated rolling summary via the discussion tier."""
        prompt = build_compaction_prompt(messages, prior_summary)
        response = await self._with_timeout(
            self._discussion_client.chat.completions.create(
                model=self._config.discussion.model,
                messages=prompt,
            )
        )
        return self._extract_content(response)

    async def summarize_discussion(
        self,
        history: list[dict[str, str]],
        prior_summary: str | None,
    ) -> list[str]:
        """Summarize a discussion into a list of bullet-point notes."""
        prompt = build_save_summary_prompt(history, prior_summary)
        response = await self._with_timeout(
            self._discussion_client.chat.completions.create(
                model=self._config.discussion.model,
                messages=prompt,
            )
        )
        return parse_bullets(self._extract_content(response))
