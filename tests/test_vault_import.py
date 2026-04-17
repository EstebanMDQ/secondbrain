from __future__ import annotations

from pathlib import Path

import pytest

from secondbrain.vault_import import ParsedProject, parse_file, parse_markdown


def test_parse_markdown_extracts_name_description_ideas_stack() -> None:
    text = """# widget-bot

One-line tagline about the widget.

## Idea

Long form idea body.

Second paragraph of idea.

## Stack

- Python 3.13
- SQLite
- Telegram

## Commands

- /start, /help
"""
    parsed = parse_markdown(text)
    assert parsed.name == "widget-bot"
    assert parsed.description == "One-line tagline about the widget."
    assert parsed.ideas == "Long form idea body.\n\nSecond paragraph of idea."
    assert parsed.stack == ["Python 3.13", "SQLite", "Telegram"]
    assert parsed.tags == []
    assert parsed.status is None


def test_parse_markdown_respects_frontmatter_precedence() -> None:
    text = """---
name: Frontmatter Name
description: frontmatter tagline
status: idea
tags:
  - backend
stack:
  - go
---

# ignored h1

body paragraph.

## Idea

prose.
"""
    parsed = parse_markdown(text)
    assert parsed.name == "Frontmatter Name"
    assert parsed.description == "frontmatter tagline"
    assert parsed.status == "idea"
    assert parsed.tags == ["backend"]
    assert parsed.stack == ["go"]
    assert parsed.ideas == "prose."


def test_parse_markdown_accepts_ideas_heading() -> None:
    text = """# thing

tagline

## Ideas

plural heading works too.
"""
    parsed = parse_markdown(text)
    assert parsed.ideas == "plural heading works too."


def test_parse_markdown_missing_name_uses_fallback() -> None:
    text = "no headings here, just prose.\n"
    parsed = parse_markdown(text, fallback_name="fallback")
    assert parsed.name == "fallback"
    assert parsed.description == "no headings here, just prose."


def test_parse_markdown_raises_without_any_name_source() -> None:
    with pytest.raises(ValueError):
        parse_markdown("just prose, no heading, no fallback\n")


def test_parse_markdown_description_stops_at_blank_line() -> None:
    text = """# thing

first paragraph.

second paragraph should not be part of description.

## Idea

body.
"""
    parsed = parse_markdown(text)
    assert parsed.description == "first paragraph."


def test_parse_markdown_ignores_malformed_frontmatter() -> None:
    text = """---
not: valid: yaml: all: on: one: line:
---

# thing

tagline.
"""
    parsed = parse_markdown(text)
    assert parsed.name == "thing"
    assert parsed.description == "tagline."


def test_parse_file_reads_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "widget.md"
    path.write_text("# widget\n\ntagline.\n", encoding="utf-8")
    parsed = parse_file(path)
    assert isinstance(parsed, ParsedProject)
    assert parsed.name == "widget"
    assert parsed.description == "tagline."


def test_parse_markdown_stack_bullets_accept_asterisks() -> None:
    text = """# thing

tagline

## Stack

* One
* Two
"""
    parsed = parse_markdown(text)
    assert parsed.stack == ["One", "Two"]
