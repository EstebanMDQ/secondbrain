"""Parse existing project markdown files into the bot's project model.

The importer reads human-authored notes from the vault and extracts the fields
the bot cares about (name, description, ideas, stack). Sections the bot does
not model (for example, ``## Commands``, ``## Risks``) are dropped when the
file is rewritten in the canonical format.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ParsedProject:
    """Fields extracted from a single markdown file."""

    name: str
    description: str | None = None
    ideas: str | None = None
    stack: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str | None = None


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")


def _strip_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Return (frontmatter dict, body) - empty dict if no frontmatter."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        logger.warning("skipping malformed frontmatter")
        data = {}
    body = text[match.end():]
    if not isinstance(data, dict):
        data = {}
    return data, body


def _split_h2_sections(body: str) -> tuple[str, dict[str, str]]:
    """Return (pre-section text, mapping of H2 heading -> section body).

    Pre-section text is everything before the first ``## heading``. Section
    bodies are stripped of surrounding whitespace.
    """
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return body.strip(), {}

    pre = body[: matches[0].start()].strip()
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[heading] = body[start:end].strip()
    return pre, sections


def _extract_description(pre_body: str, h1_name: str | None) -> str | None:
    """Pick the first non-empty paragraph after the title as description."""
    text = pre_body
    if h1_name:
        h1_match = re.match(r"^#\s+.+?\s*$", text, re.MULTILINE)
        if h1_match:
            text = text[h1_match.end():]
    text = text.strip()
    if not text:
        return None
    first_paragraph = text.split("\n\n", 1)[0].strip()
    return first_paragraph or None


def _parse_bullet_list(section_body: str) -> list[str]:
    """Extract each ``- item`` or ``* item`` line. Ignores non-bullet lines."""
    items: list[str] = []
    for line in section_body.splitlines():
        match = _BULLET_RE.match(line)
        if match:
            items.append(match.group(1).strip())
    return items


def _find_section(sections: dict[str, str], *candidates: str) -> str | None:
    """Return the body of the first heading (case-insensitive) that matches."""
    lowered = {key.lower(): key for key in sections}
    for candidate in candidates:
        key = lowered.get(candidate.lower())
        if key is not None:
            value = sections[key].strip()
            return value or None
    return None


def parse_markdown(text: str, *, fallback_name: str | None = None) -> ParsedProject:
    """Extract project fields from a markdown file's contents.

    The parser is lenient: fields that are missing yield ``None`` or empty
    defaults rather than raising. Frontmatter values take precedence over
    values derived from the body so that previously-imported files round-trip
    cleanly.
    """
    frontmatter, body = _strip_frontmatter(text)

    h1_match = _H1_RE.search(body)
    h1_name = h1_match.group(1).strip() if h1_match else None

    pre, sections = _split_h2_sections(body)

    name = str(frontmatter.get("name") or h1_name or fallback_name or "").strip()
    if not name:
        raise ValueError("could not determine project name from markdown")

    description = frontmatter.get("description")
    if description is None:
        description = _extract_description(pre, h1_name)
    elif isinstance(description, str):
        description = description.strip() or None
    else:
        description = None

    ideas = _find_section(sections, "Ideas", "Idea")

    raw_stack = frontmatter.get("stack")
    if isinstance(raw_stack, list):
        stack = [str(item).strip() for item in raw_stack if str(item).strip()]
    else:
        stack_section = _find_section(sections, "Stack")
        stack = _parse_bullet_list(stack_section) if stack_section else []

    raw_tags = frontmatter.get("tags")
    tags = (
        [str(item).strip() for item in raw_tags if str(item).strip()]
        if isinstance(raw_tags, list)
        else []
    )

    status_raw = frontmatter.get("status")
    status = str(status_raw).strip() if isinstance(status_raw, str) and status_raw.strip() else None

    return ParsedProject(
        name=name,
        description=description,
        ideas=ideas,
        stack=stack,
        tags=tags,
        status=status,
    )


def parse_file(path: Path) -> ParsedProject:
    """Read ``path`` and parse it; uses the filename stem as a name fallback."""
    text = path.read_text(encoding="utf-8")
    return parse_markdown(text, fallback_name=path.stem)
