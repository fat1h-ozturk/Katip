"""Conservative target identity: unavailable does not mean verified."""

from dataclasses import dataclass
import ctypes
import os
import shutil
import subprocess
import sys
from ..infrastructure.process_runner import clean_environment


@dataclass(frozen=True)
class Target:
    backend: str
    identity: str


def capture_target():
    try:
        if sys.platform.startswith("win"):
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            identity = user32.GetForegroundWindow()
            return Target("win32", str(identity)) if identity else None
        if sys.platform == "darwin":
            from AppKit import NSWorkspace
            import Quartz
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not app:
                return None
            pid = app.processIdentifier()
            # An application PID alone cannot distinguish two windows of one app.
            windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,
                                                       Quartz.kCGNullWindowID) or []
            for window in windows:
                if (window.get(Quartz.kCGWindowOwnerPID) == pid
                        and window.get(Quartz.kCGWindowLayer) == 0):
                    identity = window.get(Quartz.kCGWindowNumber)
                    return Target("macos", f"{pid}:{identity}") if identity else None
            return None
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return None
        if shutil.which("xdotool"):
            result = subprocess.run(["xdotool", "getactivewindow"], capture_output=True,
                                    text=True, timeout=0.5, env=clean_environment())
            if result.returncode == 0 and result.stdout.strip().isdigit():
                return Target("x11", result.stdout.strip())
    except Exception:
        pass
    return None


def target_unchanged(original):
    return original is not None and capture_target() == original
