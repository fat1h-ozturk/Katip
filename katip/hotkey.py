"""
Cross-Platform Global Hotkey Listener and IPC Server for Linux, Windows, and macOS.
Listens to global shortcuts (evdev on Linux / pynput on Windows & macOS) and provides
an IPC trigger so CLI commands, scripts, or OS shortcuts can toggle recording.
"""

import os
import select
import socket
import sys
import threading
from typing import Callable, List, Optional, Set

SOCKET_PATH = "/tmp/katip.sock"
TCP_PORT = 49215

# Safe optional imports
HAS_EVDEV = False
try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
except ImportError:
    evdev = None
    ecodes = None

HAS_PYNPUT = False
try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    pynput_keyboard = None


class HotkeyManager:
    """Manages system-wide hotkeys and IPC socket trigger across OS platforms."""

    def __init__(
        self,
        hotkey_str: str = "Ctrl+Alt+Space",
        trigger_mode: str = "toggle",
        on_toggle: Optional[Callable[[], None]] = None,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        on_notify_running: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
    ):
        self.hotkey_str = hotkey_str
        self.trigger_mode = trigger_mode  # "toggle" or "push_to_talk"
        self.on_toggle = on_toggle
        self.on_press = on_press
        self.on_release = on_release
        self.on_notify_running = on_notify_running
        self.on_open_settings = on_open_settings
        self.is_running = False
        self._threads: List[threading.Thread] = []
        self._active_keys: Set[int] = set()
        self._lock = threading.Lock()
        self._combo_triggered = False
        self._pynput_listener = None

    def start(self) -> None:
        """Starts the platform IPC server and background hotkey listener."""
        self.is_running = True

        # 1. Start IPC Server (TCP on Windows, Unix domain socket on Linux/macOS)
        ipc_thread = threading.Thread(target=self._run_ipc_server, daemon=True)
        ipc_thread.start()
        self._threads.append(ipc_thread)

        # 2. Start Global Hotkey Listener
        if sys.platform.startswith("linux") and HAS_EVDEV:
            evdev_thread = threading.Thread(target=self._run_evdev_listener, daemon=True)
            evdev_thread.start()
            self._threads.append(evdev_thread)
        elif HAS_PYNPUT:
            self._start_pynput_listener()
        else:
            print("[Hotkey] Notice: Neither evdev nor pynput is available. Global shortcuts will rely on CLI IPC (--toggle).")

    def stop(self) -> None:
        self.is_running = False
        if self._pynput_listener:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None

        if not sys.platform.startswith("win") and os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except Exception:
                pass

    # --- IPC SERVER (TCP on Windows, Unix Domain Socket on POSIX) ---
    def _run_ipc_server(self) -> None:
        server = None
        try:
            if sys.platform.startswith("win"):
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", TCP_PORT))
            else:
                if os.path.exists(SOCKET_PATH):
                    try:
                        os.remove(SOCKET_PATH)
                    except Exception:
                        pass
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(SOCKET_PATH)

            server.listen(5)
            server.settimeout(1.0)
        except Exception as e:
            print(f"[Hotkey] Failed to start IPC server: {e}")
            return

        while self.is_running:
            try:
                conn, _ = server.accept()
                with conn:
                    data = conn.recv(128).decode("utf-8").strip()
                    if data == "toggle":
                        if self.on_toggle:
                            self.on_toggle()
                        conn.sendall(b"ok")
                    elif data == "start":
                        if self.on_press:
                            self.on_press()
                        elif self.on_toggle:
                            self.on_toggle()
                        conn.sendall(b"ok")
                    elif data == "stop":
                        if self.on_release:
                            self.on_release()
                        elif self.on_toggle:
                            self.on_toggle()
                        conn.sendall(b"ok")
                    elif data == "ping":
                        conn.sendall(b"pong")
                    elif data == "notify_running":
                        if self.on_notify_running:
                            self.on_notify_running()
                        conn.sendall(b"ok")
                    elif data == "open_settings":
                        if self.on_open_settings:
                            self.on_open_settings()
                        conn.sendall(b"ok")
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    print(f"[Hotkey] IPC connection error: {e}")

        try:
            if server:
                server.close()
            if not sys.platform.startswith("win") and os.path.exists(SOCKET_PATH):
                os.remove(SOCKET_PATH)
        except Exception:
            pass

    # --- PYNPUT LISTENER (Windows & macOS) ---
    def _start_pynput_listener(self) -> None:
        """Sets up cross-platform hotkey listener using pynput."""
        if not HAS_PYNPUT:
            return

        # Format "Ctrl+Alt+Space" into pynput syntax: "<ctrl>+<alt>+<space>"
        parts = [p.strip().lower() for p in self.hotkey_str.split("+")]
        pynput_parts = []
        for p in parts:
            if p in ("ctrl", "control"):
                pynput_parts.append("<ctrl>")
            elif p in ("alt", "option"):
                pynput_parts.append("<alt>")
            elif p in ("shift",):
                pynput_parts.append("<shift>")
            elif p in ("cmd", "command", "super", "win", "meta"):
                pynput_parts.append("<cmd>")
            elif p == "space":
                pynput_parts.append("<space>")
            elif p.startswith("f") and p[1:].isdigit():
                pynput_parts.append(f"<{p}>")
            elif p in ("enter", "return", "tab", "capslock", "pause", "scrolllock", "printscreen", "insert", "home", "end", "pageup", "pagedown", "up", "down", "left", "right"):
                pynput_parts.append(f"<{p}>")
            else:
                pynput_parts.append(p)

        hotkey_combo = "+".join(pynput_parts)

        def on_activate():
            if self.on_toggle:
                self.on_toggle()

        try:
            if self.trigger_mode == "push_to_talk":
                parsed_keys = set(pynput_keyboard.HotKey.parse(hotkey_combo))
                active_keys = set()
                is_triggered = False
                lock = threading.Lock()

                def on_pynput_press(k):
                    nonlocal is_triggered
                    with lock:
                        canonical = listener.canonical(k)
                        if canonical in parsed_keys:
                            active_keys.add(canonical)
                            if active_keys == parsed_keys and not is_triggered:
                                is_triggered = True
                                if self.on_press:
                                    self.on_press()

                def on_pynput_release(k):
                    nonlocal is_triggered
                    with lock:
                        canonical = listener.canonical(k)
                        active_keys.discard(canonical)
                        if is_triggered and active_keys != parsed_keys:
                            is_triggered = False
                            if self.on_release:
                                self.on_release()

                listener = pynput_keyboard.Listener(
                    on_press=on_pynput_press,
                    on_release=on_pynput_release
                )
                self._pynput_listener = listener
                listener.start()
            else:
                self._pynput_listener = pynput_keyboard.GlobalHotKeys({
                    hotkey_combo: on_activate
                })
                self._pynput_listener.start()
        except Exception as e:
            print(f"[Hotkey] Failed to start pynput listener ({hotkey_combo}): {e}")

    # --- EVDEV LISTENER (Linux) ---
    def _run_evdev_listener(self) -> None:
        """Finds keyboards and listens for configured shortcut via evdev."""
        if not HAS_EVDEV:
            return

        key_map = {
            "CTRL": {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL},
            "ALT": {ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT},
            "SHIFT": {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT},
            "SUPER": {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA},
            "SPACE": {ecodes.KEY_SPACE},
            "RETURN": {ecodes.KEY_ENTER},
            "ENTER": {ecodes.KEY_ENTER},
            "TAB": {ecodes.KEY_TAB},
            "CAPSLOCK": {ecodes.KEY_CAPSLOCK},
            "PAUSE": {ecodes.KEY_PAUSE},
            "SCROLLLOCK": {ecodes.KEY_SCROLLLOCK},
            "PRINTSCREEN": {ecodes.KEY_SYSRQ},
            "INSERT": {ecodes.KEY_INSERT},
            "HOME": {ecodes.KEY_HOME},
            "END": {ecodes.KEY_END},
            "PAGEUP": {ecodes.KEY_PAGEUP},
            "PAGEDOWN": {ecodes.KEY_PAGEDOWN},
            "UP": {ecodes.KEY_UP},
            "DOWN": {ecodes.KEY_DOWN},
            "LEFT": {ecodes.KEY_LEFT},
            "RIGHT": {ecodes.KEY_RIGHT},
        }
        # F1-F24 tuşları dinamik olarak eklenir
        for i in range(1, 25):
            attr = f"KEY_F{i}"
            if hasattr(ecodes, attr):
                key_map[f"F{i}"] = {getattr(ecodes, attr)}

        keyboards = []
        try:
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    name_lower = dev.name.lower()
                    if "ydotool" in name_lower:
                        continue
                    caps = dev.capabilities()
                    if ecodes.EV_KEY in caps:
                        keyboards.append(dev)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Hotkey] Error discovering evdev devices: {e}")
            return

        if not keyboards:
            print("[Hotkey] No suitable keyboard devices found for evdev.")
            return

        parts = [p.strip().upper() for p in self.hotkey_str.split("+")]

        while self.is_running:
            try:
                r, _, _ = select.select(keyboards, [], [], 0.5)
                for dev in r:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY:
                            self._handle_evdev_key(event.code, event.value, parts, key_map)
            except Exception:
                pass

    def _handle_evdev_key(self, code: int, value: int, combo_parts: List[str], key_map: dict) -> None:
        with self._lock:
            if value == 1:
                self._active_keys.add(code)
            elif value == 0:
                self._active_keys.discard(code)

            all_satisfied = True
            for part in combo_parts:
                allowed_codes = key_map.get(part)
                if allowed_codes:
                    if not any(k in self._active_keys for k in allowed_codes):
                        all_satisfied = False
                        break
                else:
                    attr_name = f"KEY_{part}"
                    if hasattr(ecodes, attr_name):
                        target_code = getattr(ecodes, attr_name)
                        if target_code not in self._active_keys:
                            all_satisfied = False
                            break
                    else:
                        all_satisfied = False
                        break

            if all_satisfied and not self._combo_triggered:
                self._combo_triggered = True
                if self.trigger_mode == "push_to_talk":
                    if self.on_press:
                        self.on_press()
                else:
                    if self.on_toggle:
                        self.on_toggle()
            elif not all_satisfied and self._combo_triggered:
                self._combo_triggered = False
                if self.trigger_mode == "push_to_talk":
                    if self.on_release:
                        self.on_release()


def send_ipc_message(message: str, timeout: float = 1.0) -> Optional[str]:
    """Sends an arbitrary message to a running Katip instance and returns the reply."""
    if sys.platform.startswith("win"):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(("127.0.0.1", TCP_PORT))
            client.sendall(message.encode("utf-8"))
            reply = client.recv(128).decode("utf-8").strip()
            client.close()
            return reply
        except Exception:
            return None
    else:
        if not os.path.exists(SOCKET_PATH):
            return None
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(SOCKET_PATH)
            client.sendall(message.encode("utf-8"))
            reply = client.recv(128).decode("utf-8").strip()
            client.close()
            return reply
        except Exception:
            return None

def is_instance_running() -> bool:
    """Checks if another instance of Katip is actively running and responding."""
    return send_ipc_message("ping") == "pong"

def notify_running_instance() -> bool:
    """Notifies the running instance that the user attempted to launch it again."""
    return send_ipc_message("notify_running") == "ok"

def open_running_settings() -> bool:
    """Requests the running instance to open its Settings window."""
    return send_ipc_message("open_settings") == "ok"

def send_ipc_toggle() -> bool:
    """Sends a toggle trigger to a running Katip instance across OS platforms."""
    res = send_ipc_message("toggle")
    return res in ("ok", "pong", "") or res is not None

def send_ipc_start() -> bool:
    """Sends a start recording trigger to a running Katip instance."""
    res = send_ipc_message("start")
    return res in ("ok", "pong", "") or res is not None

def send_ipc_stop() -> bool:
    """Sends a stop recording trigger to a running Katip instance."""
    res = send_ipc_message("stop")
    return res in ("ok", "pong", "") or res is not None
