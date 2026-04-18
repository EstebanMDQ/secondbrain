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
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import yaml

logger = logging.getLogger(__name__)

SyncStatus = Literal["ok", "conflict", "dirty", "push_failed", "noop"]


@runtime_checkable
class ProjectLike(Protocol):
    """Minimal shape required to render a project to markdown."""

    name: str
    slug: str
    status: str | None
    stack: list[str]
    tags: list[str]
    description: str | None
    ideas: str | None
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

    The frontmatter includes name, status, stack, tags, and description. An
    ``## Ideas`` section is appended when the project has ideas content, and
    a ``## Notes`` section is appended when the project has any notes.
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

    ideas = _project_field(project, "ideas", None)
    if ideas and str(ideas).strip():
        parts.append("\n## Ideas\n\n")
        parts.append(str(ideas).strip())
        parts.append("\n")

    notes = list(_project_field(project, "notes", []) or [])
    if notes:
        parts.append("\n## Notes\n")
        for note in notes:
            parts.append(_format_note_bullet(note))

    return "".join(parts)


def _format_note_bullet(note: str) -> str:
    """Render ``note`` as a single markdown bullet.

    Continuation lines are indented by two spaces so CommonMark keeps them
    attached to the bullet. Internal blank lines are preserved verbatim so
    multi-paragraph notes render as a single list item.
    """
    lines = note.split("\n")
    rendered: list[str] = [f"- {lines[0]}\n"]
    for line in lines[1:]:
        rendered.append(f"  {line}\n" if line else "\n")
    return "".join(rendered)


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


def _dirty_paths(vault_path: Path, skip_rel_path: Path | None) -> list[str]:
    """Return paths with non-empty git status, excluding ``skip_rel_path``.

    Runs ``git status --porcelain -uall`` across the whole repo. Porcelain
    lines are of the form ``XY <path>`` where ``XY`` is a two-char status and
    a space follows - the path is everything after the 3-character prefix.
    ``-uall`` lists untracked files individually so the skip filter can
    match on a specific file even inside a brand-new directory.
    """
    result = _run_git(
        ["status", "--porcelain", "-uall"],
        cwd=vault_path,
        check=True,
    )
    skip = str(skip_rel_path) if skip_rel_path is not None else None
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if skip is not None and path == skip:
            continue
        paths.append(path)
    return paths


def _top_stash_ref(vault_path: Path) -> str | None:
    """Return the ref of the topmost stash (``stash@{0}``) or None if empty."""
    result = _run_git(["stash", "list"], cwd=vault_path, check=False)
    first = result.stdout.splitlines()[:1]
    if not first:
        return None
    line = first[0]
    ref, _, _ = line.partition(":")
    ref = ref.strip()
    return ref or None


def sync_project(
    vault_path: Path,
    subfolder: str,
    project: Any,
    *,
    auto_stash_dirty: bool = False,
) -> SyncResult:
    """Atomically sync a project markdown file to the vault's git remote.

    Sequence: optional pre-sync dirty check -> ``git pull --rebase`` ->
    write file -> ``git add`` -> ``git commit`` -> ``git push`` -> optional
    ``git stash pop``. On rebase failure a ``{slug}.conflict.md`` sidecar is
    written and the rebase is aborted. On push failure the local commit is
    kept for manual recovery.

    When ``auto_stash_dirty`` is False and the working tree has uncommitted
    changes unrelated to the project file, the sync is aborted with
    ``status='dirty'`` and no git operations are performed. When True, those
    changes are stashed before the pull and restored with ``git stash pop``
    after a successful push; a failing pop leaves the stash in place.
    """
    slug = _project_field(project, "slug", None)
    if not slug:
        raise ValueError("project is missing a slug")

    rel_path = Path(subfolder) / f"{slug}.md"
    target = vault_path / rel_path

    dirty = _dirty_paths(vault_path, rel_path)
    stash_ref: str | None = None
    if dirty:
        if not auto_stash_dirty:
            preview = ", ".join(dirty[:5])
            return SyncResult(
                status="dirty",
                path=target,
                message=f"vault has uncommitted changes; commit or stash them: {preview}",
            )
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        stash_msg = f"secondbrain-autostash-{slug}-{timestamp}"
        stash_result = _run_git(
            ["stash", "push", "-u", "-m", stash_msg],
            cwd=vault_path,
            check=True,
        )
        if "No local changes to save" in stash_result.stdout:
            stash_ref = None
        else:
            stash_ref = _top_stash_ref(vault_path)

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

    if stash_ref is not None:
        try:
            _run_git(["stash", "pop"], cwd=vault_path, check=True)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "git stash pop failed for %s (%s): %s",
                slug,
                stash_ref,
                (exc.stderr or "").strip(),
            )
            return SyncResult(
                status="ok",
                path=target,
                message=f"stash left in place: {stash_ref}",
            )

    return SyncResult(status="ok", path=target)


async def sync_project_async(
    vault_path: Path,
    subfolder: str,
    project: Any,
    *,
    auto_stash_dirty: bool = False,
) -> SyncResult:
    """Async wrapper that runs :func:`sync_project` under ``asyncio.to_thread``."""
    return await asyncio.to_thread(
        sync_project,
        vault_path,
        subfolder,
        project,
        auto_stash_dirty=auto_stash_dirty,
    )
