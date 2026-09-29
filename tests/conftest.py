"""Keep test imports and defaults away from the user's desktop state."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


_test_home = TemporaryDirectory(prefix="katip-tests-")
_home = Path(_test_home.name)

# Config paths are evaluated during module import, before fixtures can run.
os.environ["HOME"] = str(_home)
os.environ["USERPROFILE"] = str(_home)
os.environ["APPDATA"] = str(_home / "AppData" / "Roaming")
os.environ["XDG_CONFIG_HOME"] = str(_home / ".config")
os.environ["XDG_DATA_HOME"] = str(_home / ".local" / "share")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from katip.injector import WindowsInjector

_windows_set_clipboard = WindowsInjector.set_clipboard


@pytest.fixture(autouse=True)
def block_desktop_side_effects(monkeypatch):
    import pyaudio
    import requests
    from katip import hotkey, injector, sound

    def deny(*_args, **_kwargs):
        raise AssertionError("Tests must mock desktop devices and HTTP requests")

    monkeypatch.setattr(requests.Session, "request", deny)
    monkeypatch.setattr(pyaudio, "PyAudio", deny)
    for backend in (injector.LinuxInjector, injector.WindowsInjector, injector.MacInjector):
        monkeypatch.setattr(backend, "set_clipboard", deny)
        monkeypatch.setattr(backend, "simulate_paste", deny)
    monkeypatch.setattr(sound.SoundPlayer, "_play_bytes", deny)
    monkeypatch.setattr(hotkey.HotkeyManager, "_start_pynput_listener", deny)
    monkeypatch.setattr(hotkey.HotkeyManager, "_start_macos_listener", deny)
    monkeypatch.setattr(hotkey.HotkeyManager, "_run_evdev_listener", deny)


@pytest.fixture
def allow_mocked_windows_clipboard(monkeypatch):
    """Exercise clipboard logic only with a test-provided Win32 API mock."""
    monkeypatch.setattr(WindowsInjector, "set_clipboard", _windows_set_clipboard)


def pytest_unconfigure():
    _test_home.cleanup()
