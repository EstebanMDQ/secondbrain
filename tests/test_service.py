from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from secondbrain import service

# --- binary resolution -----------------------------------------------------


def test_binary_path_prefers_which(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_bin = tmp_path / "second-brain"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(service.shutil, "which", lambda _: str(fake_bin))

    resolved = service._binary_path()

    assert resolved
    assert resolved == str(fake_bin.resolve())


def test_binary_path_falls_back_to_python_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.shutil, "which", lambda _: None)

    resolved = service._binary_path()

    assert resolved
    assert resolved.endswith("-m secondbrain")
    # absolute-path prefix (not just "python")
    assert Path(resolved.split(" ", 1)[0]).is_absolute()


# --- pure renderers --------------------------------------------------------


def test_render_unit_contains_expected_directives() -> None:
    unit = service._render_unit("/usr/local/bin/second-brain")

    assert "ExecStart=/usr/local/bin/second-brain run" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=5" in unit
    assert 'Environment="PYTHONUNBUFFERED=1"' in unit
    assert "WantedBy=default.target" in unit
    assert "[Unit]" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit


def test_render_unit_writes_to_tmp_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "systemd" / "user" / "second-brain.service"
    monkeypatch.setattr(service, "_systemd_unit_path", lambda: target)
    monkeypatch.setattr(service, "_binary_path", lambda: "/opt/bin/second-brain")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        service,
        "_systemctl",
        lambda *args, **_: calls.append(args)
        or subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr=""),
    )

    service._install_linux()

    assert target.exists()
    body = target.read_text()
    assert "ExecStart=/opt/bin/second-brain run" in body
    assert "WantedBy=default.target" in body
    assert ("daemon-reload",) in calls
    assert ("enable", "--now", "second-brain") in calls


def test_render_plist_contains_label_and_run_at_load() -> None:
    raw = service._render_plist(
        ["/opt/bin/second-brain", "run"], Path("/tmp/second-brain.log")
    )
    plist: dict[str, Any] = plistlib.loads(raw)

    assert plist["Label"] == "com.secondbrain.bot"
    assert plist["RunAtLoad"] is True
    assert plist["ProgramArguments"] == ["/opt/bin/second-brain", "run"]
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["StandardOutPath"] == "/tmp/second-brain.log"
    assert plist["StandardErrorPath"] == "/tmp/second-brain.log"


def test_install_macos_writes_plist_and_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plist_target = tmp_path / "LaunchAgents" / "com.secondbrain.bot.plist"
    log_target = tmp_path / "Logs" / "second-brain.log"
    monkeypatch.setattr(service, "_launchd_plist_path", lambda: plist_target)
    monkeypatch.setattr(service, "_launchd_log_path", lambda: log_target)
    monkeypatch.setattr(service, "_binary_path", lambda: "/opt/bin/second-brain")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    service._install_macos()

    assert plist_target.exists()
    plist = plistlib.loads(plist_target.read_bytes())
    assert plist["Label"] == "com.secondbrain.bot"
    assert plist["RunAtLoad"] is True
    assert calls == [["launchctl", "load", str(plist_target)]]


# --- platform dispatch -----------------------------------------------------


def test_install_service_dispatches_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    called = {"linux": 0, "mac": 0}
    monkeypatch.setattr(service, "_install_linux", lambda: called.__setitem__("linux", 1))
    monkeypatch.setattr(service, "_install_macos", lambda: called.__setitem__("mac", 1))

    service.install_service()

    assert called == {"linux": 1, "mac": 0}


def test_install_service_dispatches_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    called = {"linux": 0, "mac": 0}
    monkeypatch.setattr(service, "_install_linux", lambda: called.__setitem__("linux", 1))
    monkeypatch.setattr(service, "_install_macos", lambda: called.__setitem__("mac", 1))

    service.install_service()

    assert called == {"linux": 0, "mac": 1}


def test_install_service_raises_on_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")

    with pytest.raises(service.UnsupportedOSError):
        service.install_service()


def test_uninstall_linux_disables_and_removes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = tmp_path / "second-brain.service"
    unit.write_text("dummy")
    monkeypatch.setattr(service, "_systemd_unit_path", lambda: unit)

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        service,
        "_systemctl",
        lambda *args, **_: calls.append(args)
        or subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr=""),
    )

    service._uninstall_linux()

    assert not unit.exists()
    assert ("disable", "--now", "second-brain") in calls
    assert ("daemon-reload",) in calls


def test_uninstall_macos_unloads_and_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plist_target = tmp_path / "com.secondbrain.bot.plist"
    plist_target.write_text("dummy")
    monkeypatch.setattr(service, "_launchd_plist_path", lambda: plist_target)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    service._uninstall_macos()

    assert not plist_target.exists()
    assert calls == [["launchctl", "unload", str(plist_target)]]


# --- status parsing --------------------------------------------------------


def test_status_linux_parses_active_enabled_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = "ActiveState=active\nUnitFileState=enabled\nMainPID=1234\n"
    monkeypatch.setattr(
        service,
        "_systemctl",
        lambda *args, **_: subprocess.CompletedProcess(
            args=list(args), returncode=0, stdout=stdout, stderr=""
        ),
    )

    status = service._status_linux()

    assert status == {"active": True, "enabled": True, "pid": 1234}


def test_status_linux_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = "ActiveState=inactive\nUnitFileState=disabled\nMainPID=0\n"
    monkeypatch.setattr(
        service,
        "_systemctl",
        lambda *args, **_: subprocess.CompletedProcess(
            args=list(args), returncode=0, stdout=stdout, stderr=""
        ),
    )

    status = service._status_linux()

    assert status == {"active": False, "enabled": False, "pid": None}


def test_status_macos_parses_launchctl_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plist_target = tmp_path / "com.secondbrain.bot.plist"
    plist_target.write_text("dummy")
    monkeypatch.setattr(service, "_launchd_plist_path", lambda: plist_target)

    stdout = (
        "PID\tStatus\tLabel\n"
        "-\t0\tcom.apple.other\n"
        "4321\t0\tcom.secondbrain.bot\n"
    )
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *a, **_: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout=stdout, stderr=""
        ),
    )

    status = service._status_macos()

    assert status == {"active": True, "enabled": True, "pid": 4321}


def test_status_macos_not_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plist_target = tmp_path / "missing.plist"
    monkeypatch.setattr(service, "_launchd_plist_path", lambda: plist_target)
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *a, **_: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout="", stderr=""
        ),
    )

    status = service._status_macos()

    assert status == {"active": False, "enabled": False, "pid": None}


# --- path helpers ----------------------------------------------------------


def test_systemd_unit_path_respects_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert service._systemd_unit_path() == (
        tmp_path / "systemd" / "user" / "second-brain.service"
    )


def test_systemd_unit_path_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert service._systemd_unit_path() == (
        Path.home() / ".config" / "systemd" / "user" / "second-brain.service"
    )
