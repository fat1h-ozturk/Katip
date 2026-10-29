"""Paste keystrokes through the XDG RemoteDesktop portal (KDE/GNOME Wayland).

One keyboard-only session lives on a dedicated asyncio/DBus thread. The first
use shows the desktop's permission dialog; its restore token is kept so later
runs reuse the grant without asking again.
"""

import asyncio
import os
import threading
from pathlib import Path
from uuid import uuid4

KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V = 29, 42, 47
_KEYBOARD = 1
_PERSIST_UNTIL_REVOKED = 2


class RemoteDesktopKeyboard:
    ROOT = "/org/freedesktop/portal/desktop"
    DEST = "org.freedesktop.portal.Desktop"
    INTERFACE = "org.freedesktop.portal.RemoteDesktop"

    def __init__(self, token_file: Path, permission_timeout=60.0):
        self.token_file = token_file
        self.permission_timeout = permission_timeout
        self.session = None
        self.bus = None
        self.pending = {}
        self._loop = None
        self._lock = threading.Lock()

    def paste(self, terminal=False, timeout=None) -> bool:
        """Send Ctrl+V (or Ctrl+Shift+V); False when the portal is unavailable or refused."""
        loop = self._ensure_loop()
        keys = [KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V] if terminal else [KEY_LEFTCTRL, KEY_V]
        future = asyncio.run_coroutine_threadsafe(self._paste(keys), loop)
        try:
            return future.result(timeout or self.permission_timeout + 5)
        except Exception:
            future.cancel()
            return False

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, name="katip-remote-desktop", daemon=True).start()
            return self._loop

    def _message(self, message):
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future and not future.done():
                future.set_result(message.body)
        elif (message.interface == "org.freedesktop.portal.Session" and message.member == "Closed"
              and message.path == self.session):
            # The user revoked access or the portal restarted; the next paste starts again.
            self.session = None

    async def _call(self, path, interface, member, signature="", body=None):
        from dbus_next import Message, MessageType
        reply = await asyncio.wait_for(self.bus.call(Message(destination=self.DEST, path=path,
            interface=interface, member=member, signature=signature, body=body or [])), timeout=3)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError("Remote desktop portal call failed")
        return reply.body

    async def _request(self, member, signature, body, options, timeout):
        from dbus_next import Variant
        token = "katip" + uuid4().hex
        sender = self.bus.unique_name.lstrip(":").replace(".", "_")
        path = f"{self.ROOT}/request/{sender}/{token}"
        options["handle_token"] = Variant("s", token)
        future = asyncio.get_running_loop().create_future()
        self.pending[path] = future
        try:
            await self._call(self.ROOT, self.INTERFACE, member, signature, body + [options])
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            try:
                await self._call(path, "org.freedesktop.portal.Request", "Close")
            except Exception:
                pass
            return [2, {}]
        finally:
            self.pending.pop(path, None)

    async def _connect(self):
        from dbus_next import Message
        from dbus_next.aio import MessageBus
        self.bus = await asyncio.wait_for(MessageBus().connect(), timeout=3)
        self.bus.add_message_handler(self._message)
        for interface in ("org.freedesktop.portal.Request", "org.freedesktop.portal.Session"):
            await asyncio.wait_for(self.bus.call(Message(destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus", interface="org.freedesktop.DBus", member="AddMatch",
                signature="s", body=[f"type='signal',sender='{self.DEST}',interface='{interface}'"])), timeout=3)

    async def _start_session(self):
        from dbus_next import Variant
        if self.bus is None or not self.bus.connected:
            await self._connect()
        response, values = await self._request("CreateSession", "a{sv}", [],
            {"session_handle_token": Variant("s", "katip" + uuid4().hex)}, 10)
        if response != 0:
            return False
        session = values["session_handle"].value
        options = {"types": Variant("u", _KEYBOARD), "persist_mode": Variant("u", _PERSIST_UNTIL_REVOKED)}
        token = self._read_token()
        if token:
            options["restore_token"] = Variant("s", token)
        response, _ = await self._request("SelectDevices", "oa{sv}", [session], options, 10)
        if response == 0:
            response, values = await self._request("Start", "osa{sv}", [session, ""], {}, self.permission_timeout)
        if response != 0 or not values.get("devices") or values["devices"].value & _KEYBOARD == 0:
            try:
                await self._call(session, "org.freedesktop.portal.Session", "Close")
            except Exception:
                pass
            return False
        if "restore_token" in values:
            self._write_token(values["restore_token"].value)
        self.session = session
        return True

    async def _paste(self, keys):
        # A session left over from a restarted portal fails on first use; start one fresh once.
        for _ in range(2):
            reused = self.session is not None
            try:
                if not self.session and not await self._start_session():
                    return False
                await self._call(self.ROOT, self.INTERFACE, "NotifyKeyboardKeycode", "oa{sv}iu",
                                 [self.session, {}, keys[0], 1])
            except Exception:
                self.session = None
                if reused:
                    continue
                return False
            try:
                for key in keys[1:]:
                    await self._call(self.ROOT, self.INTERFACE, "NotifyKeyboardKeycode", "oa{sv}iu",
                                     [self.session, {}, key, 1])
                await asyncio.sleep(.02)
                for key in reversed(keys):
                    await self._call(self.ROOT, self.INTERFACE, "NotifyKeyboardKeycode", "oa{sv}iu",
                                     [self.session, {}, key, 0])
                return True
            except Exception:
                # Keys may already be down in the target; never repeat a partial paste.
                self.session = None
                return False
        return False

    def _read_token(self):
        try:
            return self.token_file.read_text(encoding="utf-8").strip()[:256]
        except OSError:
            return ""

    def _write_token(self, token):
        # The token only re-grants this portal permission; it is still user-private.
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
        except OSError:
            pass
