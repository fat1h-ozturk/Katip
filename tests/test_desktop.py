"""
Unit tests for Desktop Integration, Autostart, and Single-Instance IPC.
"""

import os
import plistlib
import socket
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from katip.desktop import (
    _generate_desktop_entry_content,
    get_launcher_path,
    get_project_root,
    install_desktop_entry,
    is_autostart_enabled,
    is_desktop_installed,
    set_autostart,
    uninstall_desktop_entry,
)
from katip.hotkey import (
    HotkeyManager,
    is_instance_running,
    notify_running_instance,
    send_ipc_message,
)

def test_project_root_resolution():
    root = get_project_root()
    assert root.exists()
    assert (root / "katip").exists()
    assert (root / "assets").exists()

def test_launcher_path_resolution():
    launcher = get_launcher_path()
    assert launcher.exists()
    expected = get_project_root() / "bin" / ("katip.bat" if sys.platform.startswith("win") else "katip")
    assert launcher == expected.resolve()

def test_linux_icon_install_uses_asset_directory(tmp_path, monkeypatch):
    from katip.desktop import _install_linux_icons
    assets = tmp_path / "assets"
    assets.mkdir()
    for filename in ("katip.svg", "katip-64.png", "katip-128.png", "katip-256.png"):
        (assets / filename).write_bytes(b"icon")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    with patch("katip.desktop.get_assets_dir", return_value=assets), \
         patch("katip.desktop.shutil.which", return_value=None):
        _install_linux_icons()
    assert (tmp_path / "data" / "icons" / "hicolor" / "scalable" / "apps" / "katip.svg").read_bytes() == b"icon"
    assert (tmp_path / "data" / "icons" / "hicolor" / "256x256" / "apps" / "katip.png").read_bytes() == b"icon"

def test_desktop_entry_content():
    content = _generate_desktop_entry_content()
    assert "[Desktop Entry]" in content
    assert "Name=Katip" in content
    assert "Icon=katip" in content
    assert "Exec=" in content
    assert "Keywords=" in content
    assert "dikte" in content

def test_installed_assets_and_python_launcher(tmp_path):
    from katip.desktop import get_assets_dir
    wheel_assets = tmp_path / "share" / "katip" / "assets"
    wheel_assets.mkdir(parents=True)
    with patch("katip.desktop.get_project_root", return_value=tmp_path / "site-packages"), \
         patch("katip.desktop.sys.prefix", str(tmp_path)), \
         patch("katip.desktop.get_launcher_path", return_value=Path(sys.executable).resolve()):
        assert get_assets_dir() == wheel_assets
        assert f'Exec="{Path(sys.executable).resolve()}" -m katip %U' in _generate_desktop_entry_content()

import sys

def test_autostart_toggle_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_autostart = tmp_path / "autostart" / "katip.desktop"
    with patch("katip.desktop._get_linux_autostart_path", return_value=fake_autostart):
        # Initial: not enabled
        assert not is_autostart_enabled()

        # Enable autostart
        assert set_autostart(True)
        assert fake_autostart.exists()
        assert is_autostart_enabled()

        # Disable autostart
        assert set_autostart(False)
        assert not fake_autostart.exists()
        assert not is_autostart_enabled()

def test_desktop_install_uninstall_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_desktop = tmp_path / "applications" / "katip.desktop"
    with patch("katip.desktop._get_linux_desktop_path", return_value=fake_desktop), \
         patch("katip.desktop._install_linux_icons"), \
         patch("katip.desktop._uninstall_linux_icons"), \
         patch("katip.desktop._refresh_linux_desktop_database"):

        assert install_desktop_entry()
        assert fake_desktop.exists()
        assert "Name=Katip" in fake_desktop.read_text()

        assert uninstall_desktop_entry()
        assert not fake_desktop.exists()

def test_autostart_toggle_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_startup = tmp_path / "Startup"
    fake_startup.mkdir(parents=True, exist_ok=True)
    with patch("katip.desktop._get_windows_startup_dir", return_value=fake_startup), \
         patch("katip.desktop._create_windows_shortcut", side_effect=lambda tgt, sc, **kw: sc.touch() or True):

        assert not is_autostart_enabled()
        assert set_autostart(True)
        assert (fake_startup / "Katip.lnk").exists()
        assert is_autostart_enabled()

        assert set_autostart(False)
        assert not (fake_startup / "Katip.lnk").exists()
        assert not is_autostart_enabled()

@pytest.fixture
def ipc_socket_path():
    # macOS AF_UNIX paths cannot fit pytest's long per-test temporary directory.
    with TemporaryDirectory(prefix="katip-ipc-", dir="/tmp" if os.name == "posix" else None) as directory:
        yield str(Path(directory) / "ipc.sock")


def test_single_instance_ipc(ipc_socket_path):
    test_sock = ipc_socket_path
    toggle_called = []
    notify_called = []

    with patch("katip.hotkey.SOCKET_PATH", test_sock), patch("katip.hotkey.TCP_PORT", 59123), \
         patch("katip.hotkey.HAS_EVDEV", False), patch("katip.hotkey.HAS_PYNPUT", False):
        # Server not running yet
        assert not is_instance_running()

        mgr = HotkeyManager(
            on_toggle=lambda: toggle_called.append(True),
            on_notify_running=lambda: notify_called.append(True)
        )
        assert mgr.start()

        # Wait for IPC thread to bind
        ready = False
        for _ in range(20):
            if is_instance_running():
                ready = True
                break
            time.sleep(0.05)

        try:
            assert ready
            assert is_instance_running()

            # Check notify running
            assert notify_running_instance()
            assert len(notify_called) == 1

            # Check toggle
            reply = send_ipc_message("toggle")
            assert reply == "ok"
            assert len(toggle_called) == 1
        finally:
            mgr.stop()

def test_ipc_silent_client_and_duplicate_instance(ipc_socket_path):
    test_sock = ipc_socket_path
    with patch("katip.hotkey.SOCKET_PATH", test_sock), patch("katip.hotkey.TCP_PORT", 59124), \
         patch("katip.hotkey.HAS_EVDEV", False), patch("katip.hotkey.HAS_PYNPUT", False):
        first = HotkeyManager()
        second = HotkeyManager()
        assert first.start()
        try:
            assert not second.start()
            family = socket.AF_INET if sys.platform.startswith("win") else socket.AF_UNIX
            with socket.socket(family, socket.SOCK_STREAM) as silent:
                silent.connect(("127.0.0.1", 59124) if family == socket.AF_INET else test_sock)
                time.sleep(1.1)
                assert send_ipc_message("ping") == "pong"
        finally:
            first.stop()
        assert second.start()
        try:
            assert send_ipc_message("ping") == "pong"
        finally:
            second.stop()

def test_windows_shortcut_quotes_paths(tmp_path):
    from katip.desktop import _create_windows_shortcut
    target = tmp_path / "O'Connor" / "katip.exe"
    shortcut = tmp_path / "Katip.lnk"
    with patch("katip.desktop.subprocess.run") as run:
        run.return_value.returncode = 0
        assert _create_windows_shortcut(target, shortcut)
    command = run.call_args.args[0][-1]
    assert "O''Connor" in command
    assert not shortcut.exists()

def test_mac_autostart_escapes_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    launcher = tmp_path / "A&B" / "katip"
    plist_path = tmp_path / "LaunchAgents" / "katip.plist"
    with patch("katip.desktop.get_launcher_path", return_value=launcher), \
         patch("katip.desktop._get_mac_launch_agent_path", return_value=plist_path):
        assert set_autostart(True)
    assert plistlib.loads(plist_path.read_bytes())["ProgramArguments"] == [str(launcher)]

def test_purge_reports_failed_cleanup(tmp_path):
    from katip.desktop import purge_all
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    with patch("katip.desktop.uninstall_desktop_entry", return_value=True), \
         patch("katip.desktop.set_autostart", return_value=False), \
         patch("katip.config.get_config_dir", return_value=config_dir), \
         patch("katip.desktop.shutil.rmtree", side_effect=OSError("locked")):
        assert not purge_all()

def test_detach_windows_console():
    from katip.desktop import detach_windows_console
    with patch("katip.desktop.sys.platform", "linux"):
        detach_windows_console()
