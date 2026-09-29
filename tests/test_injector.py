from types import SimpleNamespace
from unittest.mock import MagicMock

from katip.injector import BaseInjector, LinuxInjector, MacInjector, TextInjector, WindowsInjector


class FakeInjector(BaseInjector):
    def __init__(self, restore_clipboard=False, plain=True, paste=True):
        super().__init__(restore_clipboard)
        self.clipboard = "previous"
        self.plain = plain
        self.paste = paste

    def can_restore_clipboard(self):
        return self.plain

    def get_current_clipboard(self):
        return self.clipboard

    def set_clipboard(self, text):
        self.clipboard = text
        return True

    def simulate_paste(self):
        return self.paste


def test_restore_setting_reaches_backend(monkeypatch):
    monkeypatch.setattr("katip.injector.sys.platform", "win32")
    injector = TextInjector()
    injector._backend = FakeInjector()
    injector.restore_clipboard = True
    assert injector._backend.restore_clipboard is True
    monkeypatch.setattr("katip.injector.time.sleep", lambda _: None)
    assert injector.inject_text("generated") is True
    assert injector.get_current_clipboard() == "previous"


def test_failed_paste_keeps_generated_text(monkeypatch):
    monkeypatch.setattr("katip.injector.time.sleep", lambda _: None)
    backend = FakeInjector(restore_clipboard=True, paste=False)
    assert backend.inject_text("generated") is False
    assert backend.clipboard == "generated"
    assert "panoda" in backend.last_error


def test_unrestorable_clipboard_is_left_untouched():
    backend = FakeInjector(restore_clipboard=True, plain=False)
    assert backend.inject_text("generated") is False
    assert backend.clipboard == "previous"
    assert "geri yüklenemiyor" in backend.last_error


def test_linux_nontext_clipboard_blocks_restore(monkeypatch):
    backend = LinuxInjector(restore_clipboard=True)
    backend.has_wl_paste = True
    backend.has_xclip = False
    monkeypatch.setattr("katip.injector.subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="text/plain;charset=utf-8\nimage/png\n"
    ))
    assert not backend.can_restore_clipboard()


def test_mac_nontext_clipboard_blocks_restore(monkeypatch):
    backend = MacInjector(restore_clipboard=True)
    monkeypatch.setattr("katip.injector.subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="{{«class utf8», 4}, {«class PNGf», 120}}"
    ))
    assert not backend.can_restore_clipboard()


def test_windows_clipboard_uses_owner_and_frees_failed_transfer(monkeypatch, allow_mocked_windows_clipboard):
    user32 = SimpleNamespace(**{name: MagicMock() for name in (
        "OpenClipboard", "CloseClipboard", "GetClipboardData", "CountClipboardFormats",
        "CreateWindowExW", "DestroyWindow", "EmptyClipboard", "SetClipboardData",
    )})
    kernel32 = SimpleNamespace(**{name: MagicMock() for name in (
        "GlobalAlloc", "GlobalLock", "GlobalUnlock", "GlobalFree",
    )})
    user32.OpenClipboard.return_value = 1
    user32.GetClipboardData.return_value = 0
    user32.CountClipboardFormats.return_value = 0
    user32.CreateWindowExW.return_value = 42
    user32.EmptyClipboard.return_value = 1
    user32.SetClipboardData.side_effect = [0, 0]
    kernel32.GlobalAlloc.return_value = 100
    kernel32.GlobalLock.return_value = 200
    monkeypatch.setattr("katip.injector.ctypes.windll", SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)
    monkeypatch.setattr("katip.injector.ctypes.memmove", lambda *_: None)

    assert WindowsInjector().set_clipboard("new") is False
    assert user32.OpenClipboard.call_args_list[-1].args == (42,)
    assert kernel32.GlobalFree.call_count == 2
    user32.DestroyWindow.assert_called_once_with(42)
