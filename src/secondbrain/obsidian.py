"""Obsidian vault sync.

Render projects as markdown files with YAML frontmatter and commit them to the
vault's git repo. Sync functions are synchronous so they can be tested without
an event loop; async wrappers run them under ``asyncio.to_thread`` for use from
the Telegram handler.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import yaml

logger = logging.getLogger(__name__)

SyncStatus = Literal["ok", "conflict", "push_failed", "noop"]


@runtime_checkable
class ProjectLike(Protocol):
    """Minimal shape required to render a project to markdown."""

    name: str
    slug: str
    status: str | None
    stack: list[str]
    tags: list[str]
    description: str | None
    notes: list[str]


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a single sync attempt."""

    status: SyncStatus
    path: Path
    message: str = ""


def _project_field(project: Any, field: str, default: Any) -> Any:
    """Read ``field`` from an object or mapping with a default."""
    if isinstance(project, dict):
        return project.get(field, default)
    return getattr(project, field, default)


def render_project_md(project: Any) -> str:
    """Render a project as a markdown string with YAML frontmatter.

    The frontmatter includes name, status, stack, tags, and description. A
    ``## Notes`` section is appended when the project has any notes.
    """
    frontmatter: dict[str, Any] = {
        "name": _project_field(project, "name", ""),
        "status": _project_field(project, "status", None),
        "stack": list(_project_field(project, "stack", []) or []),
        "tags": list(_project_field(project, "tags", []) or []),
        "description": _project_field(project, "description", None),
    }
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )

    parts = ["---\n", yaml_text, "---\n"]

    notes = list(_project_field(project, "notes", []) or [])
    if notes:
        parts.append("\n## Notes\n")
        for note in notes:
            parts.append(f"- {note}\n")

    return "".join(parts)


def write_project_file(vault_path: Path, subfolder: str, project: Any) -> Path:
    """Write the rendered markdown file for ``project`` into the vault.

    Creates ``vault_path/subfolder`` if it does not yet exist and returns the
    path of the written file.
    """
    slug = _project_field(project, "slug", None)
    if not slug:
        raise ValueError("project is missing a slug")

    target_dir = vault_path / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{slug}.md"
    target.write_text(render_project_md(project), encoding="utf-8")
    return target


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _has_changes(vault_path: Path, rel_path: Path) -> bool:
    """Return True if ``rel_path`` has staged or unstaged changes in the repo."""
    result = _run_git(
        ["status", "--porcelain", "--", str(rel_path)],
        cwd=vault_path,
        check=True,
    )
    return bool(result.stdout.strip())


def sync_project(vault_path: Path, subfolder: str, project: Any) -> SyncResult:
    """Atomically sync a project markdown file to the vault's git remote.

    Sequence: ``git pull --rebase`` -> write file -> ``git add`` -> ``git commit``
    -> ``git push``. On rebase failure a ``{slug}.conflict.md`` sidecar is
    written and the rebase is aborted. On push failure the local commit is
    kept for manual recovery.
    """
    slug = _project_field(project, "slug", None)
    if not slug:
        raise ValueError("project is missing a slug")

    try:
        _run_git(["pull", "--rebase"], cwd=vault_path, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("git pull --rebase failed for %s: %s", slug, exc.stderr.strip())
        _run_git(["rebase", "--abort"], cwd=vault_path, check=False)
        conflict_dir = vault_path / subfolder
        conflict_dir.mkdir(parents=True, exist_ok=True)
        conflict_path = conflict_dir / f"{slug}.conflict.md"
        conflict_path.write_text(render_project_md(project), encoding="utf-8")
        return SyncResult(
            status="conflict",
            path=conflict_path,
            message="git pull failed; wrote conflict sidecar for manual merge",
        )

    target = write_project_file(vault_path, subfolder, project)
    rel_path = target.relative_to(vault_path)

    _run_git(["add", "--", str(rel_path)], cwd=vault_path, check=True)

    if not _has_changes(vault_path, rel_path):
        return SyncResult(status="noop", path=target, message="no changes to commit")

    _run_git(["commit", "-m", f"update {slug}"], cwd=vault_path, check=True)

    try:
        _run_git(["push"], cwd=vault_path, check=True)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "git push failed"
        logger.warning("git push failed for %s: %s", slug, message)
        return SyncResult(status="push_failed", path=target, message=message)

    return SyncResult(status="ok", path=target)


async def sync_project_async(
    vault_path: Path,
    subfolder: str,
    project: Any,
) -> SyncResult:
    """Async wrapper that runs :func:`sync_project` under ``asyncio.to_thread``."""
    return await asyncio.to_thread(sync_project, vault_path, subfolder, project)
