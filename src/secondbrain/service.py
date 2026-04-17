"""Cross-platform service installation for the second-brain bot.

Generates and installs a systemd user unit on Linux or a launchd user agent
on macOS. All operations are user-level (no root required).
"""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

SERVICE_NAME = "second-brain"
LAUNCHD_LABEL = "com.secondbrain.bot"


class UnsupportedOSError(RuntimeError):
    """Raised when the current OS does not support service installation."""


class ServiceStatus(TypedDict):
    active: bool
    enabled: bool
    pid: int | None


# --- binary resolution -----------------------------------------------------


def _binary_path() -> str:
    """Return an absolute command string to launch the bot.

    Prefers a `second-brain` entry point on PATH, falling back to
    `<python> -m secondbrain` with absolute paths so the service file
    remains valid regardless of the shell that starts the service.
    """
    resolved = shutil.which(SERVICE_NAME)
    if resolved:
        return str(Path(resolved).resolve())
    return f"{Path(sys.executable).resolve()} -m secondbrain"


def _program_arguments(binary: str) -> list[str]:
    """Split `_binary_path()` output into argv for launchd ProgramArguments."""
    return [*binary.split(), "run"]


# --- path helpers ----------------------------------------------------------


def _systemd_unit_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user" / f"{SERVICE_NAME}.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_log_path() -> Path:
    return Path.home() / "Library" / "Logs" / f"{SERVICE_NAME}.log"


# --- pure renderers --------------------------------------------------------


def _render_unit(binary: str) -> str:
    """Render the systemd user unit as text. Pure function for easy testing."""
    return (
        "[Unit]\n"
        "Description=Second Brain Telegram bot\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={binary} run\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        'Environment="PYTHONUNBUFFERED=1"\n'
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _render_plist(program_arguments: Sequence[str], log_path: Path) -> bytes:
    """Render the launchd plist as XML bytes. Pure function for easy testing."""
    payload: dict[str, object] = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": list(program_arguments),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }
    return plistlib.dumps(payload)


# --- Linux (systemd --user) ------------------------------------------------


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _install_linux() -> None:
    unit_path = _systemd_unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(_render_unit(_binary_path()))
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", SERVICE_NAME)


def _uninstall_linux() -> None:
    _systemctl("disable", "--now", SERVICE_NAME, check=False)
    unit_path = _systemd_unit_path()
    if unit_path.exists():
        unit_path.unlink()
    _systemctl("daemon-reload", check=False)


def _status_linux() -> ServiceStatus:
    result = _systemctl(
        "show",
        SERVICE_NAME,
        "--property=ActiveState,UnitFileState,MainPID",
        check=False,
    )
    props: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()

    main_pid_raw = props.get("MainPID", "0")
    try:
        main_pid = int(main_pid_raw)
    except ValueError:
        main_pid = 0

    return ServiceStatus(
        active=props.get("ActiveState") == "active",
        enabled=props.get("UnitFileState") == "enabled",
        pid=main_pid if main_pid > 0 else None,
    )


# --- macOS (launchd user agent) --------------------------------------------


def _install_macos() -> None:
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = _launchd_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(
        _render_plist(_program_arguments(_binary_path()), log_path)
    )
    subprocess.run(
        ["launchctl", "load", str(plist_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _uninstall_macos() -> None:
    plist_path = _launchd_plist_path()
    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        plist_path.unlink()


def _status_macos() -> ServiceStatus:
    plist_path = _launchd_plist_path()
    enabled = plist_path.exists()

    result = subprocess.run(
        ["launchctl", "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    pid: int | None = None
    active = False
    for line in result.stdout.splitlines():
        parts = line.split()
        # Format: PID  Status  Label
        if len(parts) >= 3 and parts[-1] == LAUNCHD_LABEL:
            try:
                pid_val = int(parts[0])
                pid = pid_val if pid_val > 0 else None
            except ValueError:
                pid = None
            active = pid is not None
            break

    return ServiceStatus(active=active, enabled=enabled, pid=pid)


# --- public API ------------------------------------------------------------


def _current_system() -> str:
    system = platform.system()
    if system not in ("Linux", "Darwin"):
        raise UnsupportedOSError(
            f"unsupported OS: {system}. Run 'second-brain run' manually "
            "or configure a custom service."
        )
    return system


def install_service() -> None:
    """Install and start the bot as a user-level service for the current OS."""
    if _current_system() == "Linux":
        _install_linux()
    else:
        _install_macos()


def uninstall_service() -> None:
    """Stop and remove the user-level service for the current OS."""
    if _current_system() == "Linux":
        _uninstall_linux()
    else:
        _uninstall_macos()


def service_status() -> ServiceStatus:
    """Return `{active, enabled, pid}` for the installed service."""
    if _current_system() == "Linux":
        return _status_linux()
    return _status_macos()
