from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from secondbrain import config, service
from secondbrain.cli import main


@pytest.fixture(autouse=True)
def _clear_secondbrain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ambient SECONDBRAIN_* and XDG_* so tests are hermetic."""
    for key in list(os.environ):
        if key.startswith("SECONDBRAIN_"):
            monkeypatch.delenv(key, raising=False)


def _build_settings(vault: Path) -> config.Settings:
    return config.Settings(
        log_level="debug",
        telegram=config.TelegramSettings(token="t", allowed_user_id=1),
        ai=config.AISettings(
            categorization=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            discussion=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            timeout_seconds=30,
        ),
        discussion=config.DiscussionSettings(max_history=20, stale_minutes=30),
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="projects"),
    )


def test_help_lists_all_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "init",
        "run",
        "install-service",
        "uninstall-service",
        "status",
        "import-vault",
    ):
        assert cmd in result.output


def test_status_with_mocked_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    expected_db = tmp_path / "data" / "second-brain" / "brain.db"
    settings = _build_settings(vault)

    runner = CliRunner()
    with (
        patch.object(config, "load_config", return_value=settings),
        patch.object(
            service,
            "service_status",
            return_value=service.ServiceStatus(active=False, enabled=False, pid=None),
        ),
    ):
        result = runner.invoke(main, ["status"])

    assert result.exit_code == 0, result.output
    assert str(expected_db) in result.output
    assert "Projects: 0" in result.output
    assert "Service:" in result.output


def test_init_wizard_writes_roundtripable_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Build a real git repo with a remote so validation passes.
    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-C", str(vault), "remote", "add", "origin", "https://example.invalid/v.git"],
        check=True,
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    inputs = "\n".join(
        [
            "bot-token-123",  # telegram token
            "98765",  # allowed user id
            "http://localhost:11434/v1",  # categorization base URL
            "ollama-key",  # categorization api key
            "llama3.2",  # categorization model
            "https://api.openai.com/v1",  # discussion base URL
            "sk-disc",  # discussion api key
            "gpt-4o",  # discussion model
            str(vault),  # vault path
            "",  # timeout (default 30)
            "",  # max_history (default 20)
            "",  # stale_minutes (default 30)
            "",  # trailing newline
        ]
    )

    runner = CliRunner()
    result = runner.invoke(main, ["init"], input=inputs)
    assert result.exit_code == 0, result.output

    config_path = tmp_path / "cfg" / "second-brain" / "config.toml"
    assert config_path.exists()

    settings = config.load_config(config_path)
    assert settings.telegram.token == "bot-token-123"
    assert settings.telegram.allowed_user_id == 98765
    assert settings.ai.categorization.base_url == "http://localhost:11434/v1"
    assert settings.ai.categorization.api_key == "ollama-key"
    assert settings.ai.categorization.model == "llama3.2"
    assert settings.ai.discussion.model == "gpt-4o"
    assert settings.ai.timeout_seconds == 30
    assert settings.discussion.max_history == 20
    assert settings.discussion.stale_minutes == 30
    assert settings.obsidian.vault_path == vault.resolve()

    data_dir = tmp_path / "data" / "second-brain"
    assert data_dir.is_dir()


def test_init_rejects_vault_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "bare-vault"
    vault.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    inputs = "\n".join(
        [
            "tok",
            "42",
            "http://x",
            "k",
            "m",
            "http://y",
            "k",
            "m",
            str(vault),
            "",
        ]
    )

    runner = CliRunner()
    result = runner.invoke(main, ["init"], input=inputs)
    assert result.exit_code != 0
    assert "not a git repository" in result.output


def test_import_vault_ingests_and_rewrites_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    vault = tmp_path / "vault"
    projects_dir = vault / "Projects"
    projects_dir.mkdir(parents=True)

    (projects_dir / "alpha.md").write_text(
        "# alpha\n\nfirst tagline.\n\n## Idea\n\nalpha idea body.\n\n"
        "## Stack\n\n- python\n- sqlite\n",
        encoding="utf-8",
    )
    (projects_dir / "beta.md").write_text(
        "# beta\n\nsecond tagline.\n\n## Ideas\n\nbeta idea body.\n",
        encoding="utf-8",
    )

    settings = _build_settings(vault)
    settings = config.Settings(
        log_level=settings.log_level,
        telegram=settings.telegram,
        ai=settings.ai,
        discussion=settings.discussion,
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="Projects"),
    )

    runner = CliRunner()
    with patch.object(config, "load_config", return_value=settings):
        result = runner.invoke(main, ["import-vault"])

    assert result.exit_code == 0, result.output
    assert "imported=2" in result.output

    # Files rewritten with frontmatter + Ideas section.
    alpha_text = (projects_dir / "alpha.md").read_text(encoding="utf-8")
    assert alpha_text.startswith("---\n")
    assert "name: alpha" in alpha_text
    assert "description: first tagline." in alpha_text
    assert "## Ideas\n\nalpha idea body.\n" in alpha_text

    beta_text = (projects_dir / "beta.md").read_text(encoding="utf-8")
    assert "## Ideas\n\nbeta idea body.\n" in beta_text

    # Second run is a no-op (both slugs already in DB).
    with patch.object(config, "load_config", return_value=settings):
        rerun = runner.invoke(main, ["import-vault"])
    assert rerun.exit_code == 0, rerun.output
    assert "imported=0" in rerun.output
    assert "skipped=2" in rerun.output


def test_import_vault_dry_run_does_not_touch_files_or_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    vault = tmp_path / "vault"
    projects_dir = vault / "Projects"
    projects_dir.mkdir(parents=True)

    original = "# alpha\n\ntagline.\n\n## Idea\n\nbody.\n"
    (projects_dir / "alpha.md").write_text(original, encoding="utf-8")

    settings = config.Settings(
        log_level="info",
        telegram=config.TelegramSettings(token="t", allowed_user_id=1),
        ai=config.AISettings(
            categorization=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            discussion=config.AIProviderSettings(base_url="u", api_key="k", model="m"),
            timeout_seconds=30,
        ),
        discussion=config.DiscussionSettings(max_history=20, stale_minutes=30),
        obsidian=config.ObsidianSettings(vault_path=vault, subfolder="Projects"),
    )

    runner = CliRunner()
    with patch.object(config, "load_config", return_value=settings):
        result = runner.invoke(main, ["import-vault", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would import" in result.output
    # File must be untouched.
    assert (projects_dir / "alpha.md").read_text(encoding="utf-8") == original
