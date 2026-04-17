from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from secondbrain.obsidian import (
    SyncResult,
    render_project_md,
    sync_project,
    sync_project_async,
    write_project_file,
)


@dataclass
class FakeProject:
    name: str
    slug: str
    status: str | None = None
    stack: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    notes: list[str] = field(default_factory=list)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_vault(tmp_path: Path) -> tuple[Path, Path]:
    """Initialize a bare repo and a working clone, return (bare, clone)."""
    bare = tmp_path / "vault.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    clone = tmp_path / "vault"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "checkout", "-B", "main")
    (clone / "README.md").write_text("initial\n")
    _git(clone, "add", "README.md")
    _git(clone, "commit", "-m", "init")
    _git(clone, "push", "-u", "origin", "main")
    return bare, clone


def test_render_project_md_with_all_fields() -> None:
    project = FakeProject(
        name="My Auth Service",
        slug="my-auth-service",
        status="idea",
        stack=["python", "fastapi"],
        tags=["backend"],
        description="JWT-based auth",
        notes=["First note", "Second note"],
    )

    expected = (
        "---\n"
        "name: My Auth Service\n"
        "status: idea\n"
        "stack:\n"
        "- python\n"
        "- fastapi\n"
        "tags:\n"
        "- backend\n"
        "description: JWT-based auth\n"
        "---\n"
        "\n"
        "## Notes\n"
        "- First note\n"
        "- Second note\n"
    )
    assert render_project_md(project) == expected


def test_render_project_md_without_notes_or_tags() -> None:
    project = FakeProject(name="Empty Notes", slug="empty-notes")

    expected = (
        "---\n"
        "name: Empty Notes\n"
        "status: null\n"
        "stack: []\n"
        "tags: []\n"
        "description: null\n"
        "---\n"
    )
    assert render_project_md(project) == expected


def test_render_project_md_accepts_mapping() -> None:
    payload = {
        "name": "From Dict",
        "slug": "from-dict",
        "status": "building",
        "stack": ["go"],
        "tags": [],
        "description": None,
        "notes": ["Only one"],
    }
    rendered = render_project_md(payload)
    assert "name: From Dict" in rendered
    assert "## Notes" in rendered
    assert "- Only one" in rendered


def test_write_project_file_creates_subfolder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    project = FakeProject(name="Widget", slug="widget", description="demo")

    path = write_project_file(vault, "projects", project)

    assert path == vault / "projects" / "widget.md"
    assert path.read_text(encoding="utf-8") == render_project_md(project)


def test_write_project_file_requires_slug(tmp_path: Path) -> None:
    project = FakeProject(name="No Slug", slug="")
    with pytest.raises(ValueError):
        write_project_file(tmp_path, "projects", project)


def test_sync_project_writes_and_pushes(tmp_path: Path) -> None:
    bare, clone = _init_vault(tmp_path)
    project = FakeProject(
        name="Widget",
        slug="widget",
        description="widget thing",
        notes=["initial"],
    )

    result = sync_project(clone, "projects", project)

    assert result.status == "ok"
    assert result.path == clone / "projects" / "widget.md"

    log = _git(clone, "log", "--format=%s", "-n", "1").stdout.strip()
    assert log == "update widget"

    # Verify the commit made it to the bare remote.
    remote_log = _git(clone, "log", "origin/main", "--format=%s", "-n", "1").stdout.strip()
    assert remote_log == "update widget"


def test_sync_project_noop_when_content_unchanged(tmp_path: Path) -> None:
    _, clone = _init_vault(tmp_path)
    project = FakeProject(name="Widget", slug="widget", description="same")

    first = sync_project(clone, "projects", project)
    assert first.status == "ok"

    second = sync_project(clone, "projects", project)
    assert second.status == "noop"


def test_sync_project_conflict_writes_sidecar(tmp_path: Path) -> None:
    bare, clone = _init_vault(tmp_path)

    # Seed a shared file on origin so both sides can diverge on it.
    target_rel = Path("projects") / "widget.md"
    (clone / "projects").mkdir()
    (clone / target_rel).write_text("shared baseline\n")
    _git(clone, "add", str(target_rel))
    _git(clone, "commit", "-m", "seed widget")
    _git(clone, "push")

    # Second clone pushes a divergent change to origin.
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other")
    (other / target_rel).write_text("remote wins\n")
    _git(other, "add", str(target_rel))
    _git(other, "commit", "-m", "remote change")
    _git(other, "push")

    # Local clone creates a conflicting commit without pulling first.
    (clone / target_rel).write_text("local wins\n")
    _git(clone, "add", str(target_rel))
    _git(clone, "commit", "-m", "local change")

    project = FakeProject(name="Widget", slug="widget", description="after conflict")
    result = sync_project(clone, "projects", project)

    assert result.status == "conflict"
    assert result.path == clone / "projects" / "widget.conflict.md"
    assert result.path.exists()
    # The rebase was aborted, so HEAD still points at our local change.
    head = _git(clone, "log", "--format=%s", "-n", "1").stdout.strip()
    assert head == "local change"


def test_sync_project_push_failure_preserves_local_commit(tmp_path: Path) -> None:
    _, clone = _init_vault(tmp_path)
    # Point origin at a path that cannot be pushed to so push fails but pull succeeds.
    broken = tmp_path / "broken.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(broken)],
        check=True,
        capture_output=True,
        text=True,
    )
    # Configure broken remote as a no-op for fetch and fail for push by using an
    # unreachable URL only on push.
    _git(clone, "remote", "set-url", "--push", "origin", "/nonexistent/broken.git")

    project = FakeProject(name="Widget", slug="widget", description="pushfail")
    result = sync_project(clone, "projects", project)

    assert result.status == "push_failed"
    assert result.path.exists()
    # Local commit preserved.
    log = _git(clone, "log", "--format=%s", "-n", "1").stdout.strip()
    assert log == "update widget"


def test_sync_project_conflict_via_mocked_pull(tmp_path: Path) -> None:
    """Unit-test conflict handling without spinning up a real remote."""
    vault = tmp_path / "vault"
    vault.mkdir()

    call_log: list[list[str]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        call_log.append(args)
        if args[:2] == ["pull", "--rebase"]:
            raise subprocess.CalledProcessError(
                1, ["git", *args], output="", stderr="CONFLICT"
            )
        return subprocess.CompletedProcess(
            ["git", *args], 0, stdout="", stderr=""
        )

    project = FakeProject(name="Widget", slug="widget", description="oops")
    with patch("secondbrain.obsidian._run_git", side_effect=fake_run):
        result = sync_project(vault, "projects", project)

    assert result.status == "conflict"
    assert result.path == vault / "projects" / "widget.conflict.md"
    assert result.path.exists()
    assert ["rebase", "--abort"] in call_log


async def test_sync_project_async_wraps_sync(tmp_path: Path) -> None:
    _, clone = _init_vault(tmp_path)
    project = FakeProject(name="Widget", slug="widget", description="async")
    result = await sync_project_async(clone, "projects", project)
    assert isinstance(result, SyncResult)
    assert result.status == "ok"
