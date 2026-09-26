"""
Cross-Platform Text Injection Engine for Linux, Windows, and macOS.
Copies formatted text to system clipboard and synthesizes paste (Ctrl+V / Cmd+V)
into the currently active window.
"""

import abc
import ctypes
import os
import shutil
import subprocess
import sys
import time
from typing import Optional

class BaseInjector(abc.ABC):
    """Abstract base class for platform-specific text injectors."""

    def __init__(self, restore_clipboard: bool = False):
        self.restore_clipboard = restore_clipboard

    @abc.abstractmethod
    def get_current_clipboard(self) -> Optional[str]:
        pass

    @abc.abstractmethod
    def set_clipboard(self, text: str) -> bool:
        pass

    @abc.abstractmethod
    def simulate_paste(self) -> bool:
        pass

    def inject_text(self, text: str) -> bool:
        """
        Main injection routine:
        1. Optionally captures existing clipboard.
        2. Sets formatted text into clipboard.
        3. Waits briefly for compositor/OS clipboard synchronization.
        4. Synthesizes paste shortcut (Ctrl+V on Linux/Win, Cmd+V on macOS).
        5. Optionally restores previous clipboard.
        """
        if not text:
            return False

        old_clipboard = None
        if self.restore_clipboard:
            old_clipboard = self.get_current_clipboard()

        copied = self.set_clipboard(text)
        if not copied:
            print("[Injector] Failed to copy text to clipboard.")
            return False

        # Brief delay so active app sees updated clipboard
        time.sleep(0.06)

        pasted = self.simulate_paste()

        if self.restore_clipboard and old_clipboard is not None:
            time.sleep(0.3)
            self.set_clipboard(old_clipboard)

        return pasted


class LinuxInjector(BaseInjector):
    """Linux text injector using wl-copy/xclip and ydotool/xdotool."""

    def __init__(self, restore_clipboard: bool = False, terminal_paste: bool = False):
        super().__init__(restore_clipboard)
        self.terminal_paste = terminal_paste
        is_linux = sys.platform.startswith("linux")
        self.has_wl_copy = is_linux and (shutil.which("wl-copy") is not None)
        self.has_wl_paste = is_linux and (shutil.which("wl-paste") is not None)
        self.has_xclip = is_linux and (shutil.which("xclip") is not None)
        self.has_ydotool = is_linux and (shutil.which("ydotool") is not None)
        self.has_xdotool = is_linux and (shutil.which("xdotool") is not None)

    def get_current_clipboard(self) -> Optional[str]:
        if self.has_wl_paste:
            try:
                res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    return res.stdout
            except Exception:
                pass
        elif self.has_xclip:
            try:
                res = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    return res.stdout
            except Exception:
                pass
        return None

    def set_clipboard(self, text: str) -> bool:
        if self.has_wl_copy:
            try:
                subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True, timeout=2)
                return True
            except Exception as e:
                print(f"[LinuxInjector] wl-copy error: {e}")

        if self.has_xclip:
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True, timeout=2)
                return True
            except Exception as e:
                print(f"[LinuxInjector] xclip error: {e}")

        # PySide6 fallback if available
        try:
            from PySide6.QtGui import QGuiApplication
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(text)
                return True
        except Exception:
            pass

        return False

    def simulate_paste(self) -> bool:
        # 1. Try ydotool (Wayland & generic Linux input device)
        if self.has_ydotool:
            try:
                if self.terminal_paste:
                    # 29=LEFTCTRL, 42=LEFTSHIFT, 47=V
                    res = subprocess.run(
                        ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
                        capture_output=True, timeout=2
                    )
                else:
                    # 29=LEFTCTRL, 47=V
                    res = subprocess.run(
                        ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                        capture_output=True, timeout=2
                    )
                if res.returncode == 0:
                    return True
            except Exception as e:
                print(f"[LinuxInjector] ydotool error: {e}")

        # 2. Try xdotool (X11)
        if self.has_xdotool:
            try:
                key_combo = "ctrl+shift+v" if self.terminal_paste else "ctrl+v"
                res = subprocess.run(["xdotool", "key", key_combo], capture_output=True, timeout=2)
                if res.returncode == 0:
                    return True
            except Exception as e:
                print(f"[LinuxInjector] xdotool error: {e}")

        return False


class WindowsInjector(BaseInjector):
    """Windows text injector using native Win32 user32.dll and clipboard."""

    def get_current_clipboard(self) -> Optional[str]:
        """Reads text from Windows clipboard via Win32 API (thread-safe)."""
        try:
            import ctypes
            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

            # Retry up to 5 times in case another app holds the clipboard
            for _ in range(5):
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.03)
            else:
                return None

            try:
                h_data = user32.GetClipboardData(CF_UNICODETEXT)
                text = None
                if h_data:
                    p_data = kernel32.GlobalLock(h_data)
                    if p_data:
                        text = ctypes.c_wchar_p(p_data).value
                        kernel32.GlobalUnlock(h_data)
                return text
            finally:
                user32.CloseClipboard()
        except Exception:
            return None

    def set_clipboard(self, text: str) -> bool:
        """Sets text onto Windows system clipboard via native Win32 API (thread-safe)."""
        try:
            import ctypes
            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

            # Retry up to 10 times in case clipboard is temporarily locked
            for _ in range(10):
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.03)
            else:
                print("[WindowsInjector] Could not open clipboard (locked by another process).")
                return False

            try:
                user32.EmptyClipboard()
                encoded = text.encode("utf-16-le") + b"\x00\x00"
                h_mem = kernel32.GlobalAlloc(0x0042, len(encoded))  # GMEM_MOVEABLE | GMEM_ZEROINIT
                if h_mem:
                    p_mem = kernel32.GlobalLock(h_mem)
                    if p_mem:
                        ctypes.memmove(p_mem, encoded, len(encoded))
                        kernel32.GlobalUnlock(h_mem)
                        res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                        return bool(res)
                return False
            finally:
                user32.CloseClipboard()
        except Exception as e:
            print(f"[WindowsInjector] Clipboard error: {e}")
            return False

    def simulate_paste(self) -> bool:
        """Synthesizes Ctrl+V paste into currently focused window."""
        try:
            import ctypes
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt
            VK_SPACE = 0x20
            VK_V = 0x56
            KEYEVENTF_KEYUP = 0x0002

            user32 = ctypes.windll.user32

            # Ensure modifier keys from shortcut (Alt, Space) are released before Ctrl+V
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)

            # Key down: Ctrl + V
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.02)

            # Key up: V + Ctrl
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            print(f"[WindowsInjector] keybd_event error: {e}")
            return False


class MacInjector(BaseInjector):
    """macOS text injector using pbcopy/pbpaste and AppleScript System Events (Cmd+V)."""

    def get_current_clipboard(self) -> Optional[str]:
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass
        return None

    def set_clipboard(self, text: str) -> bool:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=2)
            return True
        except Exception as e:
            print(f"[MacInjector] pbcopy error: {e}")

        # PySide6 fallback
        try:
            from PySide6.QtGui import QGuiApplication
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(text)
                return True
        except Exception:
            pass
        return False

    def simulate_paste(self) -> bool:
        """Sends Cmd+V keystroke via AppleScript."""
        script = 'tell application "System Events" to keystroke "v" using command down'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)
            return res.returncode == 0
        except Exception as e:
            print(f"[MacInjector] AppleScript error: {e}")
            return False


class TextInjector:
    """Factory and unified proxy for platform-specific text injection."""

    def __init__(self, restore_clipboard: bool = False, terminal_paste_mode: bool = False):
        self.restore_clipboard = restore_clipboard
        if sys.platform.startswith("win"):
            self._backend: BaseInjector = WindowsInjector(restore_clipboard=restore_clipboard)
        elif sys.platform == "darwin":
            self._backend: BaseInjector = MacInjector(restore_clipboard=restore_clipboard)
        else:
            self._backend: BaseInjector = LinuxInjector(restore_clipboard=restore_clipboard, terminal_paste=terminal_paste_mode)

    def get_current_clipboard(self) -> Optional[str]:
        return self._backend.get_current_clipboard()

    def set_clipboard(self, text: str) -> bool:
        return self._backend.set_clipboard(text)

    def simulate_paste(self) -> bool:
        return self._backend.simulate_paste()

    def inject_text(self, text: str) -> bool:
        return self._backend.inject_text(text)
