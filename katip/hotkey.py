"""
Cross-Platform Global Hotkey Listener and IPC Server for Linux, Windows, and macOS.
Listens to global shortcuts (evdev on Linux / pynput on Windows / Quartz on macOS)
and provides an IPC trigger so CLI commands, scripts, or OS shortcuts can toggle recording.
"""

import os
import select
import socket
import sys
import threading
from typing import Callable, List, Optional, Set

SOCKET_PATH = "/tmp/katip.sock"
TCP_PORT = 49215

# macOS virtual key codes (US hardware positions). Reading these directly from
# CGEvents avoids pynput's Carbon keyboard-layout lookup, which can abort on
# recent macOS versions when it runs on the listener thread.
_MACOS_KEY_CODES = {
    "A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04,
    "G": 0x05, "Z": 0x06, "X": 0x07, "C": 0x08, "V": 0x09,
    "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E, "R": 0x0F,
    "Y": 0x10, "T": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
    "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19,
    "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "O": 0x1F, "U": 0x20, "[": 0x21, "I": 0x22, "P": 0x23,
    "L": 0x25, "J": 0x26, "'": 0x27, "K": 0x28, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, "N": 0x2D, "M": 0x2E,
    ".": 0x2F, "`": 0x32,
    "RETURN": 0x24, "ENTER": 0x4C, "TAB": 0x30, "SPACE": 0x31,
    "BACKSPACE": 0x33, "ESC": 0x35, "ESCAPE": 0x35,
    "CAPSLOCK": 0x39, "HOME": 0x73, "END": 0x77,
    "PAGEUP": 0x74, "PAGEDOWN": 0x79, "INSERT": 0x72,
    "PAUSE": 0x71, "SCROLLLOCK": 0x6B, "PRINTSCREEN": 0x69,
    "DELETE": 0x75, "UP": 0x7E, "DOWN": 0x7D,
    "LEFT": 0x7B, "RIGHT": 0x7C,
    # Turkish Q keyboard layout keys.
    "Ğ": 0x21, "Ü": 0x1E, "Ş": 0x29, "İ": 0x27,
    "Ö": 0x2B, "Ç": 0x2F,
    "!": 0x12, "@": 0x13, "#": 0x14, "$": 0x15, "%": 0x17,
    "^": 0x16, "&": 0x1A, "*": 0x1C, "(": 0x19, ")": 0x1D,
    "+": 0x18, "_": 0x1B, "{": 0x21, "}": 0x1E, ":": 0x29,
    '"': 0x27, "|": 0x2A, "<": 0x2B, ">": 0x2F, "?": 0x2C,
    "~": 0x32,
}
_MACOS_KEY_CODES.update({
    f"F{i}": code for i, code in enumerate(
        (0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D,
         0x67, 0x6F, 0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F, 0x50, 0x5A),
        start=1,
    )
})

_MACOS_MODIFIER_ALIASES = {
    "CTRL": "ctrl", "CONTROL": "ctrl",
    "ALT": "alt", "OPTION": "alt",
    "SHIFT": "shift",
    "CMD": "cmd", "COMMAND": "cmd", "SUPER": "cmd",
    "WIN": "cmd", "META": "cmd",
}

# CGEventFlags on the affected macOS/Qt combination can report the wrong
# modifier bit even though the modifier key event itself has the correct
# virtual key code. Track modifier key transitions directly so configured
# Command and Control shortcuts match the actual key events.
_MACOS_MODIFIER_KEY_CODES = {
    0x37: ("cmd", "cmd-left"), 0x36: ("cmd", "cmd-right"),
    0x3B: ("ctrl", "ctrl-left"), 0x3E: ("ctrl", "ctrl-right"),
    0x3A: ("alt", "alt-left"), 0x3D: ("alt", "alt-right"),
    0x38: ("shift", "shift-left"), 0x3C: ("shift", "shift-right"),
}

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
        self._macos_thread = None
        self._macos_run_loop = None
        self._macos_event_callback = None
        self._macos_pressed_keys: Set[int] = set()
        self._macos_pressed_modifiers: Set[int] = set()
        self._macos_combo = None

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
        elif sys.platform == "darwin":
            self._start_macos_listener()
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

        if sys.platform == "darwin":
            run_loop = self._macos_run_loop
            if run_loop is not None:
                try:
                    from Quartz import CFRunLoopStop
                    CFRunLoopStop(run_loop)
                except Exception:
                    pass
            thread = self._macos_thread
            if thread and thread is not threading.current_thread():
                thread.join(timeout=1.0)
            self._macos_thread = None

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

    # --- macOS LISTENER (Quartz virtual key codes) ---
    def _start_macos_listener(self) -> None:
        """Starts a raw virtual-key listener that avoids Carbon layout APIs."""
        parts = [part.strip().upper() for part in self.hotkey_str.split("+") if part.strip()]
        modifiers = set()
        key_code = None
        key_seen = False
        for part in parts:
            modifier = _MACOS_MODIFIER_ALIASES.get(part)
            if modifier:
                modifiers.add(modifier)
            elif not key_seen:
                key_seen = True
                key_code = _MACOS_KEY_CODES.get(part)
                if key_code is None:
                    print(f"[Hotkey] Unsupported macOS key: {part}")
                    return
            else:
                print(f"[Hotkey] Invalid macOS shortcut: {self.hotkey_str}")
                return

        if not parts or (key_code is None and not modifiers):
            print(f"[Hotkey] Unsupported macOS shortcut: {self.hotkey_str}")
            return

        self._macos_combo = (frozenset(modifiers), key_code)
        self._macos_pressed_keys.clear()
        self._macos_pressed_modifiers.clear()
        print(
            f"[Hotkey] macOS kısayolu yapılandırıldı: {self.hotkey_str} "
            f"(modifier={','.join(sorted(modifiers)) or 'yok'}, keycode={key_code})"
        )
        self._macos_thread = threading.Thread(
            target=self._run_macos_listener,
            name="talk-to-write-macos-hotkey",
            daemon=True,
        )
        self._macos_thread.start()

    def _run_macos_listener(self) -> None:
        """Reads only CGEvent key codes and modifier flags on macOS."""
        try:
            from Quartz import (
                CFMachPortCreateRunLoopSource,
                CFRunLoopAddSource,
                CFRunLoopGetCurrent,
                CFRunLoopRunInMode,
                CGEventGetFlags,
                CGEventGetIntegerValueField,
                CGEventMaskBit,
                CGEventTapCreate,
                CGEventTapEnable,
                kCFRunLoopDefaultMode,
                kCGEventFlagsChanged,
                kCGEventKeyDown,
                kCGEventKeyUp,
                kCGHeadInsertEventTap,
                kCGSessionEventTap,
                kCGEventTapOptionListenOnly,
                kCGKeyboardEventKeycode,
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
            )
        except ImportError as error:
            print(f"[Hotkey] macOS global shortcut support unavailable: {error}")
            return

        event_mask = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)
        )

        def handle_event(proxy, event_type, event, refcon):
            if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                if tap is not None:
                    CGEventTapEnable(tap, True)
                return event

            key_code = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
            if event_type == kCGEventKeyDown:
                self._macos_pressed_keys.add(key_code)
            elif event_type == kCGEventKeyUp:
                self._macos_pressed_keys.discard(key_code)

            flags = CGEventGetFlags(event)
            modifier_info = _MACOS_MODIFIER_KEY_CODES.get(key_code)
            if event_type == kCGEventFlagsChanged and modifier_info:
                modifier_name, key_label = modifier_info
                if key_code in self._macos_pressed_modifiers:
                    self._macos_pressed_modifiers.remove(key_code)
                    action = "bırakıldı"
                else:
                    self._macos_pressed_modifiers.add(key_code)
                    action = "basıldı"
                print(
                    f"[Hotkey] macOS modifier tuşu {action}: {key_label} "
                    f"(keycode={key_code}, flags=0x{int(flags):x})"
                )

            # Modifier transitions are delivered as flags-changed events. Use
            # their virtual key codes to distinguish Command from Control even
            # when macOS reports a contradictory aggregate flag for key-down.
            active_modifiers = {
                name for code, (name, _label) in _MACOS_MODIFIER_KEY_CODES.items()
                if code in self._macos_pressed_modifiers
            }

            required_modifiers, required_key = self._macos_combo
            if event_type == kCGEventKeyDown and key_code == required_key:
                actual = ",".join(sorted(active_modifiers)) or "yok"
                print(
                    f"[Hotkey] macOS hedef tuşu görüldü: keycode={key_code}, "
                    f"modifier={actual}, beklenen={','.join(sorted(required_modifiers)) or 'yok'}"
                )
            active = required_modifiers.issubset(active_modifiers)
            if required_key is not None:
                active = active and required_key in self._macos_pressed_keys

            if active and not self._combo_triggered:
                self._combo_triggered = True
                print(f"[Hotkey] macOS kısayolu tetiklendi: {self.hotkey_str}")
                if self.trigger_mode == "push_to_talk":
                    if self.on_press:
                        self.on_press()
                elif self.on_toggle:
                    self.on_toggle()
            elif not active and self._combo_triggered:
                self._combo_triggered = False
                if self.trigger_mode == "push_to_talk" and self.on_release:
                    self.on_release()
            return event

        self._macos_event_callback = handle_event
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            event_mask,
            handle_event,
            None,
        )
        if tap is None:
            print(
                "[Hotkey] macOS keyboard monitoring is disabled. Grant Accessibility "
                "permission to Terminal (or Talk-to-Write) in System Settings."
            )
            return

        loop_source = CFMachPortCreateRunLoopSource(None, tap, 0)
        run_loop = CFRunLoopGetCurrent()
        self._macos_run_loop = run_loop
        CFRunLoopAddSource(run_loop, loop_source, kCFRunLoopDefaultMode)
        CGEventTapEnable(tap, True)
        print(f"[Hotkey] macOS kısayolu dinleniyor: {self.hotkey_str}")
        try:
            while self.is_running:
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.5, False)
        finally:
            CGEventTapEnable(tap, False)
            self._macos_run_loop = None
            self._macos_event_callback = None

    # --- PYNPUT LISTENER (Windows) ---
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
