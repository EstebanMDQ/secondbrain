from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when the configuration is missing required values or invalid."""


@dataclass(frozen=True)
class TelegramSettings:
    token: str = ""
    allowed_user_id: int = 0


@dataclass(frozen=True)
class AIProviderSettings:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@dataclass(frozen=True)
class AISettings:
    categorization: AIProviderSettings = field(default_factory=AIProviderSettings)
    discussion: AIProviderSettings = field(default_factory=AIProviderSettings)
    timeout_seconds: int = 30


@dataclass(frozen=True)
class DiscussionSettings:
    max_history: int = 20
    stale_minutes: int = 30


@dataclass(frozen=True)
class ObsidianSettings:
    vault_path: Path = Path()
    subfolder: str = "projects"


@dataclass(frozen=True)
class Settings:
    log_level: str = "info"
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    ai: AISettings = field(default_factory=AISettings)
    discussion: DiscussionSettings = field(default_factory=DiscussionSettings)
    obsidian: ObsidianSettings = field(default_factory=ObsidianSettings)


_ENV_PREFIX = "SECONDBRAIN_"


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "second-brain" / "config.toml"


def _coerce_str(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"expected string, got {type(value).__name__}: {value!r}")
    return value


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        # TOML integers parse as int; env overrides pass a str.
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError(f"expected integer, got {value!r}") from exc
        raise ConfigError(f"expected integer, got {type(value).__name__}: {value!r}")
    return value


def _build_provider(raw: dict[str, Any], dotted: str) -> AIProviderSettings:
    if not isinstance(raw, dict):
        raise ConfigError(f"{dotted}: expected table")
    defaults = AIProviderSettings()
    return AIProviderSettings(
        base_url=_coerce_str(raw.get("base_url", defaults.base_url)),
        api_key=_coerce_str(raw.get("api_key", defaults.api_key)),
        model=_coerce_str(raw.get("model", defaults.model)),
    )


def _build_settings(raw: dict[str, Any]) -> Settings:
    defaults = Settings()

    telegram_raw = raw.get("telegram", {})
    if not isinstance(telegram_raw, dict):
        raise ConfigError("telegram: expected table")
    telegram = TelegramSettings(
        token=_coerce_str(telegram_raw.get("token", defaults.telegram.token)),
        allowed_user_id=_coerce_int(
            telegram_raw.get("allowed_user_id", defaults.telegram.allowed_user_id)
        ),
    )

    ai_raw = raw.get("ai", {})
    if not isinstance(ai_raw, dict):
        raise ConfigError("ai: expected table")
    ai = AISettings(
        categorization=_build_provider(ai_raw.get("categorization", {}), "ai.categorization"),
        discussion=_build_provider(ai_raw.get("discussion", {}), "ai.discussion"),
        timeout_seconds=_coerce_int(ai_raw.get("timeout_seconds", defaults.ai.timeout_seconds)),
    )

    discussion_raw = raw.get("discussion", {})
    if not isinstance(discussion_raw, dict):
        raise ConfigError("discussion: expected table")
    discussion = DiscussionSettings(
        max_history=_coerce_int(discussion_raw.get("max_history", defaults.discussion.max_history)),
        stale_minutes=_coerce_int(
            discussion_raw.get("stale_minutes", defaults.discussion.stale_minutes)
        ),
    )

    obsidian_raw = raw.get("obsidian", {})
    if not isinstance(obsidian_raw, dict):
        raise ConfigError("obsidian: expected table")
    vault_raw = obsidian_raw.get("vault_path", "")
    obsidian = ObsidianSettings(
        vault_path=Path(_coerce_str(vault_raw)) if vault_raw else Path(),
        subfolder=_coerce_str(obsidian_raw.get("subfolder", defaults.obsidian.subfolder)),
    )

    return Settings(
        log_level=_coerce_str(raw.get("log_level", defaults.log_level)),
        telegram=telegram,
        ai=ai,
        discussion=discussion,
        obsidian=obsidian,
    )


# Map of SECONDBRAIN_ env var suffixes (lowercase) to (attribute path, kind).
# "kind" selects the coercion applied to the env string.
_ENV_MAP: dict[str, tuple[tuple[str, ...], str]] = {
    "log_level": (("log_level",), "str"),
    "telegram_token": (("telegram", "token"), "str"),
    "telegram_allowed_user_id": (("telegram", "allowed_user_id"), "int"),
    "ai_categorization_base_url": (("ai", "categorization", "base_url"), "str"),
    "ai_categorization_api_key": (("ai", "categorization", "api_key"), "str"),
    "ai_categorization_model": (("ai", "categorization", "model"), "str"),
    "ai_discussion_base_url": (("ai", "discussion", "base_url"), "str"),
    "ai_discussion_api_key": (("ai", "discussion", "api_key"), "str"),
    "ai_discussion_model": (("ai", "discussion", "model"), "str"),
    "ai_timeout_seconds": (("ai", "timeout_seconds"), "int"),
    "discussion_max_history": (("discussion", "max_history"), "int"),
    "discussion_stale_minutes": (("discussion", "stale_minutes"), "int"),
    "obsidian_vault_path": (("obsidian", "vault_path"), "path"),
    "obsidian_subfolder": (("obsidian", "subfolder"), "str"),
}


def _coerce_env(raw: str, kind: str) -> Any:
    if kind == "str":
        return raw
    if kind == "int":
        return _coerce_int(raw)
    if kind == "path":
        return Path(raw)
    raise ConfigError(f"internal: unknown env coercion kind {kind!r}")


def _set_nested(settings: Settings, path: tuple[str, ...], value: Any) -> Settings:
    head, *rest = path
    current = getattr(settings, head)
    if rest:
        new_child = _set_nested(current, tuple(rest), value)
        return replace(settings, **{head: new_child})
    return replace(settings, **{head: value})


def _apply_env_overrides(settings: Settings) -> Settings:
    for env_name, env_value in os.environ.items():
        if not env_name.startswith(_ENV_PREFIX):
            continue
        suffix = env_name[len(_ENV_PREFIX) :].lower()
        mapping = _ENV_MAP.get(suffix)
        if mapping is None:
            continue
        path, kind = mapping
        settings = _set_nested(settings, path, _coerce_env(env_value, kind))
    return settings


def _validate(settings: Settings) -> None:
    if not settings.telegram.token:
        raise ConfigError("missing required config field: telegram.token")
    if not settings.telegram.allowed_user_id:
        raise ConfigError("missing required config field: telegram.allowed_user_id")

    for section_name in ("categorization", "discussion"):
        section: AIProviderSettings = getattr(settings.ai, section_name)
        if not section.base_url:
            raise ConfigError(f"missing required config field: ai.{section_name}.base_url")
        if not section.api_key:
            raise ConfigError(f"missing required config field: ai.{section_name}.api_key")
        if not section.model:
            raise ConfigError(f"missing required config field: ai.{section_name}.model")

    vault_path = settings.obsidian.vault_path
    if not str(vault_path) or str(vault_path) == ".":
        raise ConfigError("missing required config field: obsidian.vault_path")
    if not vault_path.exists():
        raise ConfigError(f"obsidian.vault_path does not exist: {vault_path}")


def load_config(path: Path | None = None) -> Settings:
    """Load settings from a TOML file, apply env overrides, and validate."""
    config_path = path if path is not None else _default_config_path()
    if not config_path.exists():
        raise ConfigError(
            f"config file not found at {config_path}. Run 'second-brain init' to create one."
        )

    with config_path.open("rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc

    settings = _build_settings(raw)
    settings = _apply_env_overrides(settings)
    _validate(settings)
    return settings


def data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    path = base / "second-brain"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "brain.db"
