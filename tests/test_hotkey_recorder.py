"""
Unit tests for HotkeyRecorderWidget and hotkey parsing / key mapping.
"""

import os
import sys
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Ensure single QApplication instance
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from katip.ui.hotkey_recorder import HotkeyRecorderWidget
from katip.hotkey import HotkeyManager, HAS_EVDEV


def test_hotkey_recorder_initial_and_set_get():
    widget = HotkeyRecorderWidget()
    assert widget.get_hotkey() == ""

    widget.set_hotkey("Ctrl+Alt+Space")
    assert widget.get_hotkey() == "Ctrl+Alt+Space"
    assert widget.text() == "Ctrl+Alt+Space"


def test_hotkey_recorder_clear_via_backspace():
    widget = HotkeyRecorderWidget()
    widget.set_hotkey("Ctrl+Alt+Space")
    widget._start_recording()

    # Simulate Backspace key
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(event)

    assert widget.get_hotkey() == ""
    assert widget.text() == ""


def test_hotkey_recorder_escape_cancels():
    widget = HotkeyRecorderWidget()
    widget.set_hotkey("Ctrl+Alt+Space")
    widget._start_recording()

    # Press a modifier
    mod_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    widget.keyPressEvent(mod_event)
    assert widget._recording is True

    # Press Escape
    esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(esc_event)

    assert widget._recording is False
    assert widget.get_hotkey() == "Ctrl+Alt+Space"
    assert widget.text() == "Ctrl+Alt+Space"


def test_hotkey_recorder_capture_combo():
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    emitted_hotkeys = []
    widget.hotkey_changed.connect(emitted_hotkeys.append)

    # Press Ctrl
    e1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    widget.keyPressEvent(e1)

    # Press Alt
    e2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    widget.keyPressEvent(e2)

    # Press F9
    e3 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F9, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(e3)

    assert widget.get_hotkey() == "Ctrl+Alt+F9"
    assert widget.text() == "Ctrl+Alt+F9"
    assert widget._recording is False
    assert emitted_hotkeys == ["Ctrl+Alt+F9"]


def test_hotkey_recorder_canonical_order():
    """Even if Alt is pressed before Ctrl, canonical output is Ctrl+Alt+Key."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    # Press Alt first
    e1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    widget.keyPressEvent(e1)

    # Press Ctrl second
    e2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    widget.keyPressEvent(e2)

    # Press Space
    e3 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(e3)

    assert widget.get_hotkey() == "Ctrl+Alt+Space"


def test_hotkey_recorder_single_key():
    """Single keys like F8 or Pause should be valid hotkeys."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    e = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F8, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(e)

    assert widget.get_hotkey() == "F8"


def test_hotkey_recorder_super_modifier():
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    e1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Meta, Qt.KeyboardModifier.MetaModifier)
    widget.keyPressEvent(e1)

    e2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(e2)

    assert widget.get_hotkey() == "Super+Space"


@pytest.mark.skipif(not HAS_EVDEV, reason="evdev only available on Linux")
def test_evdev_key_map_coverage():
    from evdev import ecodes
    # Check that common keys exist in ecodes
    mgr = HotkeyManager()
    # Test that key names match expected ecodes
    assert hasattr(ecodes, "KEY_LEFTCTRL")
    assert hasattr(ecodes, "KEY_LEFTALT")
    assert hasattr(ecodes, "KEY_SPACE")
    assert hasattr(ecodes, "KEY_F1")
    assert hasattr(ecodes, "KEY_F12")
    assert hasattr(ecodes, "KEY_LEFTMETA")


def test_hotkey_recorder_ctrl_letter_with_control_char():
    """Verify Ctrl+A works even when Qt sends unprintable ASCII control char '\x01'."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    # User presses Ctrl
    e1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    widget.keyPressEvent(e1)

    # User presses A while holding Ctrl (Qt sets text to '\x01')
    e2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "\x01")
    widget.keyPressEvent(e2)

    assert widget.get_hotkey() == "Ctrl+A"
    assert widget.text() == "Ctrl+A"


def test_hotkey_recorder_super_letter_with_empty_text():
    """Verify Super+D works even when Wayland sends empty text for Super shortcuts."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    # User presses Super (Meta)
    e1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Meta, Qt.KeyboardModifier.MetaModifier)
    widget.keyPressEvent(e1)

    # User presses D while holding Super (Qt sets text to '')
    e2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_D, Qt.KeyboardModifier.MetaModifier, "")
    widget.keyPressEvent(e2)

    assert widget.get_hotkey() == "Super+D"
    assert widget.text() == "Super+D"


def test_hotkey_recorder_ctrl_shift_letter():
    """Verify Ctrl+Shift+S multi-modifier combination works."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    # Press Ctrl
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
    # Press Shift
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
    # Press S
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, "\x13"))

    assert widget.get_hotkey() == "Ctrl+Shift+S"
    assert widget.text() == "Ctrl+Shift+S"


def test_hotkey_recorder_single_letters():
    """Verify single keys like A, S, D still assign properly."""
    for key, char in [(Qt.Key.Key_A, "A"), (Qt.Key.Key_S, "S"), (Qt.Key.Key_D, "D")]:
        widget = HotkeyRecorderWidget()
        widget._start_recording()
        widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, char.lower()))
        assert widget.get_hotkey() == char


def test_hotkey_recorder_ctrl_shift_only():
    """Verify pressing and releasing Ctrl+Shift captures 'Ctrl+Shift'."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    # Press Ctrl
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
    # Press Shift
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
    # Release Shift
    widget.keyReleaseEvent(QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier))

    assert widget.get_hotkey() == "Ctrl+Shift"
    assert widget.text() == "Ctrl+Shift"
    assert widget._recording is False


def test_hotkey_recorder_ctrl_alt_only():
    """Verify pressing and releasing Ctrl+Alt captures 'Ctrl+Alt'."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
    widget.keyReleaseEvent(QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.ControlModifier))

    assert widget.get_hotkey() == "Ctrl+Alt"
    assert widget.text() == "Ctrl+Alt"
    assert widget._recording is False


def test_hotkey_recorder_single_modifier_release_ignored():
    """Verify pressing and releasing a single modifier (Ctrl) does NOT assign it as a shortcut."""
    widget = HotkeyRecorderWidget()
    widget._start_recording()

    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
    widget.keyReleaseEvent(QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Control, Qt.KeyboardModifier.NoModifier))

    assert widget.get_hotkey() == ""
    assert widget._recording is True
