"""
Unit tests for Desktop Integration, Autostart, and Single-Instance IPC.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

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

def test_desktop_entry_content():
    content = _generate_desktop_entry_content()
    assert "[Desktop Entry]" in content
    assert "Name=Katip" in content
    assert "Icon=katip" in content
    assert "Exec=" in content
    assert "Keywords=" in content
    assert "dikte" in content

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

def test_single_instance_ipc(tmp_path):
    test_sock = str(tmp_path / "test-katip.sock")
    toggle_called = []
    notify_called = []

    with patch("katip.hotkey.SOCKET_PATH", test_sock), patch("katip.hotkey.TCP_PORT", 59123):
        # Server not running yet
        assert not is_instance_running()

        mgr = HotkeyManager(
            on_toggle=lambda: toggle_called.append(True),
            on_notify_running=lambda: notify_called.append(True)
        )
        mgr.start()

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

def test_detach_windows_console():
    from katip.desktop import detach_windows_console
    # Should not throw any exception regardless of platform
    detach_windows_console()
