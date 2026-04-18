from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from secondbrain.config import (
    ConfigError,
    Settings,
    data_dir,
    db_path,
    load_config,
)


def _write_config(
    tmp_path: Path,
    *,
    vault: Path | None = None,
    extra: str = "",
    omit: set[str] | None = None,
) -> Path:
    """Write a complete (by default) TOML config and return its path."""
    omit = omit or set()
    vault_path = vault if vault is not None else tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)

    sections = []
    if "log_level" not in omit:
        sections.append('log_level = "debug"')
    if "telegram" not in omit:
        sections.append(
            textwrap.dedent(
                """
                [telegram]
                token = "123:ABC"
                allowed_user_id = 42
                """
            ).strip()
        )
    if "ai.categorization" not in omit:
        sections.append(
            textwrap.dedent(
                """
                [ai.categorization]
                base_url = "http://localhost:11434/v1"
                api_key = "ollama"
                model = "llama3.2"
                """
            ).strip()
        )
    if "ai.discussion" not in omit:
        sections.append(
            textwrap.dedent(
                """
                [ai.discussion]
                base_url = "https://api.openai.com/v1"
                api_key = "sk-test"
                model = "gpt-4o"
                """
            ).strip()
        )
    if "ai" not in omit:
        sections.append("[ai]\ntimeout_seconds = 45")
    if "discussion" not in omit:
        sections.append(
            textwrap.dedent(
                """
                [discussion]
                max_history = 10
                stale_minutes = 15
                """
            ).strip()
        )
    if "obsidian" not in omit:
        sections.append(
            textwrap.dedent(
                f"""
                [obsidian]
                vault_path = "{vault_path}"
                subfolder = "notes"
                """
            ).strip()
        )
    if extra:
        sections.append(extra)

    path = tmp_path / "config.toml"
    path.write_text("\n\n".join(sections) + "\n")
    return path


@pytest.fixture(autouse=True)
def _clear_secondbrain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any ambient SECONDBRAIN_* vars so tests start clean."""
    for key in list(os.environ):
        if key.startswith("SECONDBRAIN_"):
            monkeypatch.delenv(key, raising=False)


def test_load_complete_config(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    config_path = _write_config(tmp_path, vault=vault)

    settings = load_config(config_path)

    assert isinstance(settings, Settings)
    assert settings.log_level == "debug"
    assert settings.telegram.token == "123:ABC"
    assert settings.telegram.allowed_user_id == 42
    assert settings.ai.categorization.model == "llama3.2"
    assert settings.ai.discussion.model == "gpt-4o"
    assert settings.ai.timeout_seconds == 45
    assert settings.discussion.max_history == 10
    assert settings.discussion.stale_minutes == 15
    assert settings.obsidian.vault_path == vault
    assert settings.obsidian.subfolder == "notes"


def test_env_override_replaces_file_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("SECONDBRAIN_TELEGRAM_TOKEN", "overridden-token")
    monkeypatch.setenv("SECONDBRAIN_AI_CATEGORIZATION_MODEL", "gpt-oss")
    monkeypatch.setenv("SECONDBRAIN_AI_TIMEOUT_SECONDS", "99")

    settings = load_config(config_path)

    assert settings.telegram.token == "overridden-token"
    assert settings.ai.categorization.model == "gpt-oss"
    assert settings.ai.timeout_seconds == 99


def test_capture_fuzzy_threshold_defaults_to_85(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    settings = load_config(config_path)

    assert settings.capture.fuzzy_threshold == 85


def test_capture_fuzzy_threshold_toml_override(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        extra="[capture]\nfuzzy_threshold = 70",
    )

    settings = load_config(config_path)

    assert settings.capture.fuzzy_threshold == 70


def test_capture_fuzzy_threshold_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(
        tmp_path,
        extra="[capture]\nfuzzy_threshold = 70",
    )
    monkeypatch.setenv("SECONDBRAIN_CAPTURE_FUZZY_THRESHOLD", "92")

    settings = load_config(config_path)

    assert settings.capture.fuzzy_threshold == 92


def test_obsidian_auto_stash_dirty_defaults_to_false(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    settings = load_config(config_path)

    assert settings.obsidian.auto_stash_dirty is False


def test_obsidian_auto_stash_dirty_toml_override(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    config_path = _write_config(tmp_path, vault=vault, omit={"obsidian"})
    obsidian_section = textwrap.dedent(
        f"""
        [obsidian]
        vault_path = "{vault}"
        subfolder = "notes"
        auto_stash_dirty = true
        """
    ).strip()
    config_path.write_text(config_path.read_text() + "\n" + obsidian_section + "\n")

    settings = load_config(config_path)

    assert settings.obsidian.auto_stash_dirty is True


def test_obsidian_auto_stash_dirty_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("SECONDBRAIN_OBSIDIAN_AUTO_STASH_DIRTY", "true")

    settings = load_config(config_path)

    assert settings.obsidian.auto_stash_dirty is True


def test_missing_required_field_raises_config_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, omit={"telegram"})

    with pytest.raises(ConfigError) as excinfo:
        load_config(config_path)

    assert "telegram.token" in str(excinfo.value)


def test_missing_vault_path_raises(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, omit={"obsidian"})

    with pytest.raises(ConfigError) as excinfo:
        load_config(config_path)

    assert "obsidian.vault_path" in str(excinfo.value)


def test_nonexistent_vault_path_raises(tmp_path: Path) -> None:
    missing_vault = tmp_path / "does-not-exist"
    config_path = _write_config(tmp_path, vault=tmp_path / "vault")
    # Overwrite with a vault that doesn't exist.
    text = config_path.read_text().replace(str(tmp_path / "vault"), str(missing_vault))
    config_path.write_text(text)

    with pytest.raises(ConfigError) as excinfo:
        load_config(config_path)

    assert "does not exist" in str(excinfo.value)


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "missing.toml")

    assert "config file not found" in str(excinfo.value)


def test_xdg_config_home_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xdg = tmp_path / "xdg-config"
    target = xdg / "second-brain" / "config.toml"
    target.parent.mkdir(parents=True)

    vault = tmp_path / "vault"
    _write_config(tmp_path, vault=vault)
    target.write_text((tmp_path / "config.toml").read_text())

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    settings = load_config()  # no explicit path -> use XDG lookup

    assert settings.obsidian.vault_path == vault


def test_defaults_for_optional_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    minimal = textwrap.dedent(
        f"""
        [telegram]
        token = "t"
        allowed_user_id = 1

        [ai.categorization]
        base_url = "u"
        api_key = "k"
        model = "m"

        [ai.discussion]
        base_url = "u"
        api_key = "k"
        model = "m"

        [obsidian]
        vault_path = "{vault}"
        """
    ).strip()
    config_path = tmp_path / "config.toml"
    config_path.write_text(minimal + "\n")

    settings = load_config(config_path)

    assert settings.log_level == "info"
    assert settings.ai.timeout_seconds == 30
    assert settings.discussion.max_history == 20
    assert settings.discussion.stale_minutes == 30
    assert settings.obsidian.subfolder == "projects"


def test_data_dir_uses_xdg_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    d = data_dir()

    assert d == tmp_path / "second-brain"
    assert d.is_dir()


def test_db_path_under_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert db_path() == tmp_path / "second-brain" / "brain.db"
