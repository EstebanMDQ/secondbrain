from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from secondbrain.store import (
    Base,
    _dedupe_note,
    _slugify,
    _unique_slug,
    add_alias,
    create_project,
    find_project_fuzzy,
    get_project,
    get_state,
    init_db,
    list_projects,
    set_state,
    update_project,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_init_db_creates_file(tmp_path) -> None:
    db_file = tmp_path / "brain.db"
    engine = init_db(db_file)
    assert db_file.exists()
    engine.dispose()


def test_slugify_produces_url_safe_slug() -> None:
    assert _slugify("My Auth Service") == "my-auth-service"
    assert _slugify("  Hello, World!  ") == "hello-world"
    assert _slugify("Cafe con Leche") == "cafe-con-leche"
    assert _slugify("!!!") == "project"


def test_create_project_roundtrip(session: Session) -> None:
    project = create_project(
        session,
        name="My Auth Service",
        description="JWT-based auth",
        stack=["python", "fastapi"],
        tags=["backend"],
        status="idea",
    )
    session.commit()

    fetched = get_project(session, str(project.id))
    assert fetched is not None
    assert fetched.slug == "my-auth-service"
    assert fetched.name == "My Auth Service"
    assert fetched.description == "JWT-based auth"
    assert fetched.stack == ["python", "fastapi"]
    assert fetched.tags == ["backend"]
    assert fetched.status == "idea"
    assert fetched.aliases == ["My Auth Service"]


def test_create_project_with_ideas(session: Session) -> None:
    project = create_project(
        session,
        name="Idea Holder",
        description="tagline",
        ideas="Long-form prose.\n\nMultiple paragraphs.",
    )
    session.commit()

    fetched = get_project(session, str(project.id))
    assert fetched is not None
    assert fetched.ideas == "Long-form prose.\n\nMultiple paragraphs."


def test_create_project_defaults_ideas_to_none(session: Session) -> None:
    project = create_project(session, name="No Ideas")
    session.commit()

    session.refresh(project)
    assert project.ideas is None


def test_update_project_ideas_overwrites(session: Session) -> None:
    project = create_project(session, name="Editable Ideas", ideas="first draft")
    session.commit()

    update_project(session, project.id, ideas="rewritten")
    session.commit()
    session.refresh(project)
    assert project.ideas == "rewritten"

    update_project(session, project.id, ideas=None)
    session.commit()
    session.refresh(project)
    assert project.ideas is None


def test_slug_collision_appends_suffix(session: Session) -> None:
    first = create_project(session, name="Widget")
    second = create_project(session, name="Widget")
    third = create_project(session, name="Widget")
    session.commit()

    assert first.slug == "widget"
    assert second.slug == "widget-2"
    assert third.slug == "widget-3"


def test_unique_slug_helper(session: Session) -> None:
    create_project(session, name="Foo")
    session.commit()
    assert _unique_slug(session, "foo") == "foo-2"
    assert _unique_slug(session, "bar") == "bar"


def test_dedupe_note_ignores_case_and_whitespace() -> None:
    existing = ["Remember the milk"]
    assert _dedupe_note(existing, "remember the milk") == existing
    assert _dedupe_note(existing, "  REMEMBER THE MILK  ") == existing
    assert _dedupe_note(existing, "buy bread") == ["Remember the milk", "buy bread"]


def test_update_project_dedupes_notes(session: Session) -> None:
    project = create_project(session, name="Notes Test", notes=["first note"])
    session.commit()

    update_project(session, project.id, notes="FIRST NOTE")
    update_project(session, project.id, notes="  first note  ")
    update_project(session, project.id, notes="second note")
    session.commit()

    session.refresh(project)
    assert project.notes == ["first note", "second note"]


def test_get_project_by_alias(session: Session) -> None:
    project = create_project(session, name="Main Name")
    add_alias(session, project.id, "Other Name")
    session.commit()

    assert get_project(session, "Main Name").id == project.id
    assert get_project(session, "other name").id == project.id
    assert get_project(session, "main-name").id == project.id
    assert get_project(session, "unknown") is None


def test_add_alias_is_idempotent(session: Session) -> None:
    project = create_project(session, name="Alpha")
    add_alias(session, project.id, "alpha")
    add_alias(session, project.id, "Alpha")
    add_alias(session, project.id, "ALPHA")
    session.commit()

    session.refresh(project)
    assert project.aliases == ["Alpha"]


def test_update_project_omit_semantics(session: Session) -> None:
    project = create_project(
        session,
        name="Omit Test",
        description="original",
        stack=["python"],
        status="idea",
    )
    session.commit()

    update_project(session, project.id, description="updated")
    session.commit()
    session.refresh(project)

    assert project.description == "updated"
    assert project.stack == ["python"]
    assert project.status == "idea"
    assert project.name == "Omit Test"


def test_update_project_explicit_null_clears(session: Session) -> None:
    project = create_project(session, name="Nullable", description="will go away")
    session.commit()

    update_project(session, project.id, description=None)
    session.commit()
    session.refresh(project)

    assert project.description is None


def test_update_project_tags_are_union(session: Session) -> None:
    project = create_project(session, name="Tagged", tags=["a", "b"])
    session.commit()

    update_project(session, project.id, tags=["B", "c"])
    session.commit()
    session.refresh(project)

    assert project.tags == ["a", "b", "c"]


def test_update_project_stack_replaces(session: Session) -> None:
    project = create_project(session, name="Stacked", stack=["python", "fastapi"])
    session.commit()

    update_project(session, project.id, stack=["go"])
    session.commit()
    session.refresh(project)

    assert project.stack == ["go"]


def test_update_project_aliases_union(session: Session) -> None:
    project = create_project(session, name="Alpha")
    session.commit()

    update_project(session, project.id, aliases=["alpha", "A1"])
    session.commit()
    session.refresh(project)

    assert project.aliases == ["Alpha", "A1"]


def test_update_project_unknown_field_raises(session: Session) -> None:
    project = create_project(session, name="Unknown")
    session.commit()

    with pytest.raises(ValueError):
        update_project(session, project.id, not_a_field="x")


def test_update_project_missing_id_raises(session: Session) -> None:
    with pytest.raises(ValueError):
        update_project(session, 9999, name="ghost")


def test_list_projects_ordered_by_name(session: Session) -> None:
    create_project(session, name="charlie")
    create_project(session, name="alpha")
    create_project(session, name="Bravo")
    session.commit()

    projects = list_projects(session)
    assert [p.name for p in projects] == ["alpha", "Bravo", "charlie"]


def test_state_roundtrip(session: Session) -> None:
    assert get_state(session, "missing") is None
    assert get_state(session, "missing", default=False) is False

    set_state(session, "discussion_mode", True)
    set_state(session, "rolling_summary", "we talked about carrots")
    set_state(session, "pending_confirmation", {"slug": "foo", "data": {"name": "Foo"}})
    session.commit()

    assert get_state(session, "discussion_mode") is True
    assert get_state(session, "rolling_summary") == "we talked about carrots"
    assert get_state(session, "pending_confirmation") == {
        "slug": "foo",
        "data": {"name": "Foo"},
    }

    set_state(session, "discussion_mode", False)
    session.commit()
    assert get_state(session, "discussion_mode") is False


def test_find_project_fuzzy_returns_none_for_empty_store(session: Session) -> None:
    assert find_project_fuzzy(session, "anything") is None


def test_find_project_fuzzy_exact_match(session: Session) -> None:
    project = create_project(session, name="facturabot")
    create_project(session, name="morning-news")
    session.commit()

    match = find_project_fuzzy(session, "facturabot")
    assert match is not None
    assert match.id == project.id


def test_find_project_fuzzy_typo_above_threshold(session: Session) -> None:
    project = create_project(session, name="facturabot")
    create_project(session, name="morning-news")
    session.commit()

    match = find_project_fuzzy(session, "facturaabot")
    assert match is not None
    assert match.id == project.id


def test_find_project_fuzzy_near_miss_returns_none(session: Session) -> None:
    create_project(session, name="facturabot")
    session.commit()

    assert find_project_fuzzy(session, "zzzzzzzzzz") is None


def test_find_project_fuzzy_ambiguous_returns_none(session: Session) -> None:
    create_project(session, name="zebra", aliases=["shared"])
    create_project(session, name="tiger", aliases=["shared"])
    session.commit()

    assert find_project_fuzzy(session, "shared") is None


def test_find_project_fuzzy_matches_alias(session: Session) -> None:
    project = create_project(session, name="Morning News", aliases=["auranews"])
    create_project(session, name="facturabot")
    session.commit()

    match = find_project_fuzzy(session, "auranews")
    assert match is not None
    assert match.id == project.id
