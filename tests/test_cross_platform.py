import sys
from pathlib import Path
from katip.config import get_config_dir
from katip.injector import TextInjector, LinuxInjector, WindowsInjector, MacInjector
from katip.sound import SoundPlayer

def test_config_dir_resolution(monkeypatch):
    # Test Windows
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")
    p_win = get_config_dir()
    assert "katip" in str(p_win)
    assert "Roaming" in str(p_win)

    # Test macOS
    monkeypatch.setattr(sys, "platform", "darwin")
    p_mac = get_config_dir()
    assert "Library" in str(p_mac)
    assert "Application Support" in str(p_mac)

    # Test Linux
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p_linux = get_config_dir()
    assert ".config" in str(p_linux)

def test_injector_platform_selection(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    inj_win = TextInjector()
    assert isinstance(inj_win._backend, WindowsInjector)

    monkeypatch.setattr(sys, "platform", "darwin")
    inj_mac = TextInjector()
    assert isinstance(inj_mac._backend, MacInjector)

    monkeypatch.setattr(sys, "platform", "linux")
    inj_linux = TextInjector()
    assert isinstance(inj_linux._backend, LinuxInjector)

def test_sound_player_cross_platform(monkeypatch):
    # Test Windows branch doesn't throw
    monkeypatch.setattr(sys, "platform", "win32")
    player = SoundPlayer(enabled=True)
    assert "start" in player._cache

    # Test macOS branch doesn't throw
    monkeypatch.setattr(sys, "platform", "darwin")
    player_mac = SoundPlayer(enabled=True)
    assert "stop" in player_mac._cache
