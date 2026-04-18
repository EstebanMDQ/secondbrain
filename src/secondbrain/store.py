"""SQLite-backed project store.

SQLAlchemy 2.0 models and service functions for persisting projects, aliases,
notes, and bot state. The DB is treated as a disposable index - markdown files
in the Obsidian vault are the source of truth.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process
from sqlalchemy import JSON, DateTime, Engine, String, create_engine, func, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    ideas: Mapped[str | None] = mapped_column(String, nullable=True)
    stack: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class State(Base):
    __tablename__ = "state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


def init_db(db_path: Path) -> Engine:
    """Create the SQLite engine and run ``create_all``.

    No migration framework is used - schema changes require dropping the DB
    and re-deriving from markdown.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Turn a project name into a URL-safe ascii slug."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower().strip()
    slug = _SLUG_CLEAN_RE.sub("-", lowered).strip("-")
    return slug or "project"


def _unique_slug(session: Session, desired: str) -> str:
    """Return ``desired`` or ``desired-N`` (N>=2) if the slug is taken."""
    candidate = desired
    counter = 2
    while session.scalar(select(Project.id).where(Project.slug == candidate)) is not None:
        candidate = f"{desired}-{counter}"
        counter += 1
    return candidate


def _dedupe_note(existing: list[str], new: str) -> list[str]:
    """Append ``new`` to ``existing`` unless a whitespace/case match already exists."""
    key = new.strip().lower()
    if not key:
        return list(existing)
    for note in existing:
        if note.strip().lower() == key:
            return list(existing)
    return [*existing, new]


def _union_append(existing: list[str], incoming: list[str]) -> list[str]:
    """Return existing plus any incoming values not already present (case-insensitive)."""
    seen = {item.lower() for item in existing}
    result = list(existing)
    for item in incoming:
        if item.lower() not in seen:
            result.append(item)
            seen.add(item.lower())
    return result


def create_project(
    session: Session,
    *,
    name: str,
    slug: str | None = None,
    description: str | None = None,
    ideas: str | None = None,
    stack: list[str] | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    notes: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Project:
    """Insert a new project. Slug defaults to a slugified ``name`` with collision suffix."""
    desired_slug = slug or _slugify(name)
    final_slug = _unique_slug(session, desired_slug)

    initial_aliases = list(aliases) if aliases is not None else []
    if name not in initial_aliases:
        initial_aliases = [name, *initial_aliases]

    project = Project(
        slug=final_slug,
        name=name,
        description=description,
        ideas=ideas,
        stack=list(stack) if stack is not None else [],
        tags=list(tags) if tags is not None else [],
        status=status,
        notes=list(notes) if notes is not None else [],
        aliases=initial_aliases,
    )
    session.add(project)
    session.flush()
    return project


def get_project(session: Session, identifier: str) -> Project | None:
    """Resolve a project by id (digits), slug, name (case-insensitive), or alias membership."""
    if identifier.isdigit():
        project = session.get(Project, int(identifier))
        if project is not None:
            return project

    lowered = identifier.lower()
    stmt = select(Project).where(
        or_(
            Project.slug == identifier,
            func.lower(Project.name) == lowered,
        )
    )
    project = session.scalars(stmt).first()
    if project is not None:
        return project

    for candidate in session.scalars(select(Project)).all():
        for alias in candidate.aliases or []:
            if alias.lower() == lowered:
                return candidate
    return None


def find_project_fuzzy(session: Session, query: str, threshold: int = 85) -> Project | None:
    """Return the best fuzzy-matched project, or None when ambiguous/no match.

    Builds a haystack of ``(candidate_string, project)`` pairs from each
    project's ``name`` and non-empty ``aliases``. Uses ``rapidfuzz``'s
    ``WRatio`` scorer to pick the top two candidates. The top project is
    returned only when its score meets ``threshold`` AND either there is no
    runner-up from a different project, or that runner-up trails by at
    least ten points. When the top two candidates belong to the same
    project, the next different-project candidate (if any) is used as the
    runner-up.
    """
    pairs: list[tuple[str, Project]] = []
    for project in session.scalars(select(Project)).all():
        pairs.append((project.name, project))
        for alias in project.aliases or []:
            if alias:
                pairs.append((alias, project))

    if not pairs:
        return None

    candidates = [candidate for candidate, _ in pairs]
    results = process.extract(query, candidates, scorer=fuzz.WRatio, limit=2)
    if not results:
        return None

    _, top_score, top_index = results[0]
    if top_score < threshold:
        return None

    top_project = pairs[top_index][1]
    runner_up_score: float | None = None
    for _, score, index in results[1:]:
        if pairs[index][1].id != top_project.id:
            runner_up_score = score
            break

    if runner_up_score is not None and runner_up_score > top_score - 10:
        return None
    return top_project


def list_projects(session: Session) -> list[Project]:
    """Return every project ordered by name (case-insensitive)."""
    stmt = select(Project).order_by(func.lower(Project.name))
    return list(session.scalars(stmt).all())


def update_project(session: Session, project_id: int, **fields: Any) -> Project:
    """Update fields on a project with omit-means-no-change semantics.

    Only keys present in ``fields`` are touched. Special merge rules:
    - ``notes``: appended with case-insensitive/whitespace-stripped dedup.
    - ``aliases`` and ``tags``: union-append (preserve order, add missing).
    - ``stack``: replaced (list[str] overwrite).
    - All other scalar fields are overwritten with the new value (including None).
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"project id {project_id} not found")

    for key, value in fields.items():
        if key == "notes":
            current = list(project.notes or [])
            if isinstance(value, str):
                current = _dedupe_note(current, value)
            else:
                for note in value or []:
                    current = _dedupe_note(current, note)
            project.notes = current
        elif key == "aliases":
            project.aliases = _union_append(list(project.aliases or []), list(value or []))
        elif key == "tags":
            project.tags = _union_append(list(project.tags or []), list(value or []))
        elif key == "stack":
            project.stack = list(value) if value is not None else []
        elif key in {"name", "description", "ideas", "status", "slug"}:
            setattr(project, key, value)
        else:
            raise ValueError(f"unknown project field: {key}")

    session.flush()
    return project


def add_alias(session: Session, project_id: int, alias: str) -> Project:
    """Add an alias to a project if not already present (case-insensitive)."""
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"project id {project_id} not found")

    aliases = list(project.aliases or [])
    if any(existing.lower() == alias.lower() for existing in aliases):
        return project

    aliases.append(alias)
    project.aliases = aliases
    session.flush()
    return project


def get_state(session: Session, key: str, default: Any = None) -> Any:
    """Read a value from the key/value state table."""
    row = session.get(State, key)
    if row is None:
        return default
    return row.value


def set_state(session: Session, key: str, value: Any) -> None:
    """Upsert a value in the key/value state table."""
    row = session.get(State, key)
    if row is None:
        session.add(State(key=key, value=value))
    else:
        row.value = value
    session.flush()
