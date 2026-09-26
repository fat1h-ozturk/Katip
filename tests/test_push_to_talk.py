"""
Unit tests for Push-to-Talk (PTT) functionality and trigger_mode options.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from katip.config import ConfigManager, DEFAULT_CONFIG
from katip.hotkey import HotkeyManager, HAS_EVDEV, send_ipc_message


def test_default_config_trigger_mode():
    assert "trigger_mode" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["trigger_mode"] == "toggle"

    cfg = ConfigManager()
    assert cfg.get("trigger_mode") in ("toggle", "push_to_talk")


def test_hotkey_manager_push_to_talk_evdev_simulation():
    """Verify that in push_to_talk mode, combo press fires on_press, and combo release fires on_release."""
    press_called = []
    release_called = []
    toggle_called = []

    mgr = HotkeyManager(
        hotkey_str="Ctrl+Shift",
        trigger_mode="push_to_talk",
        on_toggle=lambda: toggle_called.append(True),
        on_press=lambda: press_called.append(True),
        on_release=lambda: release_called.append(True),
    )

    fake_key_map = {
        "CTRL": {100},
        "SHIFT": {101},
    }
    combo_parts = ["CTRL", "SHIFT"]

    # 1. Press CTRL (key down, value=1)
    mgr._handle_evdev_key(100, 1, combo_parts, fake_key_map)
    assert len(press_called) == 0
    assert len(release_called) == 0
    assert mgr._combo_triggered is False

    # 2. Press SHIFT (key down, value=1) -> combo satisfied!
    mgr._handle_evdev_key(101, 1, combo_parts, fake_key_map)
    assert len(press_called) == 1
    assert len(release_called) == 0
    assert len(toggle_called) == 0
    assert mgr._combo_triggered is True

    # 3. Key repeat (value=2) while held -> should not fire again
    mgr._handle_evdev_key(100, 2, combo_parts, fake_key_map)
    assert len(press_called) == 1
    assert len(release_called) == 0

    # 4. Release SHIFT (key up, value=0) -> combo broken, fires on_release!
    mgr._handle_evdev_key(101, 0, combo_parts, fake_key_map)
    assert len(press_called) == 1
    assert len(release_called) == 1
    assert mgr._combo_triggered is False

    # 5. Release CTRL (value=0)
    mgr._handle_evdev_key(100, 0, combo_parts, fake_key_map)
    assert len(release_called) == 1


def test_hotkey_manager_toggle_evdev_simulation():
    """Verify that in toggle mode, combo release does NOT fire on_release."""
    toggle_called = []
    release_called = []

    mgr = HotkeyManager(
        hotkey_str="Ctrl+Alt",
        trigger_mode="toggle",
        on_toggle=lambda: toggle_called.append(True),
        on_release=lambda: release_called.append(True),
    )

    fake_key_map = {
        "CTRL": {100},
        "ALT": {102},
    }
    combo_parts = ["CTRL", "ALT"]

    # Press both keys
    mgr._handle_evdev_key(100, 1, combo_parts, fake_key_map)
    mgr._handle_evdev_key(102, 1, combo_parts, fake_key_map)
    assert len(toggle_called) == 1
    assert len(release_called) == 0

    # Release both keys
    mgr._handle_evdev_key(102, 0, combo_parts, fake_key_map)
    mgr._handle_evdev_key(100, 0, combo_parts, fake_key_map)
    assert len(toggle_called) == 1
    assert len(release_called) == 0
