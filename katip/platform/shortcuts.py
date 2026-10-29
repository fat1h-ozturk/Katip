"""XDG GlobalShortcuts session on a dedicated asyncio/DBus thread."""

import asyncio
from uuid import uuid4


class PortalUnavailable(RuntimeError):
    """The portal could not serve the shortcut; the caller may use another backend."""


class PortalLost(PortalUnavailable):
    """An active shortcut session ended underneath us (bus loss or Session.Closed)."""


class ShortcutPortal:
    ROOT = "/org/freedesktop/portal/desktop"
    DEST = "org.freedesktop.portal.Desktop"
    INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
    SESSION = "org.freedesktop.portal.Session"
    PERMISSION_WAIT = 30.0

    def __init__(self, hotkey, on_press, on_release, stop_event, status):
        self.hotkey = hotkey
        self.on_press = on_press
        self.on_release = on_release
        self.stop = stop_event
        self.status = status
        self.session = None
        self.closed = False
        self.pending = {}
        self.bus = None

    def _message(self, message):
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future and not future.done():
                future.set_result(message.body)
        elif message.interface == self.SESSION and message.member == "Closed":
            if self.session and message.path == self.session:
                self.closed = True
        elif message.interface == self.INTERFACE and self.session and len(message.body) >= 2:
            if message.body[0] == self.session and message.body[1] == "dictation":
                callback = {"Activated": self.on_press, "Deactivated": self.on_release}.get(message.member)
                if callback:
                    try:
                        callback()
                    except Exception as error:
                        # A trigger bug must not take the DBus reader down with it.
                        print(f"[Hotkey] Portal trigger failed: {error}")

    async def _call(self, path, interface, member, signature="", body=None):
        from dbus_next import Message, MessageType
        reply = await asyncio.wait_for(self.bus.call(Message(destination=self.DEST, path=path,
            interface=interface, member=member, signature=signature, body=body or [])), timeout=3)
        if reply.message_type == MessageType.ERROR:
            raise PortalUnavailable("Shortcut portal unavailable")
        return reply.body

    async def _request(self, member, signature, body, options):
        from dbus_next import Variant
        token = "katip" + uuid4().hex
        sender = self.bus.unique_name.lstrip(":").replace(".", "_")
        path = f"{self.ROOT}/request/{sender}/{token}"
        options["handle_token"] = Variant("s", token)
        future = asyncio.get_running_loop().create_future()
        self.pending[path] = future
        try:
            await self._call(self.ROOT, self.INTERFACE, member, signature, body + [options])
            # Waiting for permission is cancellable; never start a second backend in parallel.
            for _ in range(int(self.PERMISSION_WAIT * 10)):
                if self.stop.is_set():
                    raise asyncio.CancelledError()
                if future.done():
                    return future.result()
                await asyncio.sleep(.1)
            try:
                await self._call(path, "org.freedesktop.portal.Request", "Close")
            except Exception:
                pass
            # No answer is not a refusal; let the caller try another backend.
            raise PortalUnavailable(f"{member} timed out")
        finally:
            self.pending.pop(path, None)

    def _accepted(self, response):
        # 1 is the user's refusal; 2 (and anything unknown) is a backend failure.
        if response == 1:
            self.status("portal_denied")
            return False
        if response != 0:
            raise PortalUnavailable(f"portal response {response}")
        return True

    async def run(self):
        from dbus_next import Message, Variant
        from dbus_next.aio import MessageBus
        try:
            self.bus = await asyncio.wait_for(MessageBus().connect(), timeout=3)
            self.bus.add_message_handler(self._message)
            for interface in ("org.freedesktop.portal.Request", self.INTERFACE, self.SESSION):
                await asyncio.wait_for(self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                    body=[f"type='signal',sender='{self.DEST}',interface='{interface}'"])), timeout=3)
            response, values = await self._request("CreateSession", "a{sv}", [],
                {"session_handle_token": Variant("s", "katip" + uuid4().hex)})
            if not self._accepted(response):
                return
            self.session = values["session_handle"].value
            accelerator = self.hotkey.replace("Ctrl", "CTRL").replace("Alt", "ALT").replace("Shift", "SHIFT").replace("Super", "LOGO")
            response, _ = await self._request("BindShortcuts", "oa(sa{sv})sa{sv}",
                [self.session, [["dictation", {"description": Variant("s", "Kâtip dikte"),
                    "preferred_trigger": Variant("s", accelerator)}]], ""], {})
            if not self._accepted(response):
                return
            self.status("portal_active")
            while not self.stop.is_set() and self.bus.connected and not self.closed:
                await asyncio.sleep(.1)
            if not self.stop.is_set():
                self.status("portal_lost")
                raise PortalLost("Shortcut portal session ended")
        except asyncio.CancelledError:
            pass
        except PortalUnavailable:
            raise
        except Exception:
            raise PortalUnavailable("Shortcut portal unavailable") from None
        finally:
            if self.bus:
                if self.session and not self.closed and self.bus.connected:
                    try:
                        await self._call(self.session, self.SESSION, "Close")
                    except Exception:
                        pass
                try:
                    self.bus.disconnect()
                except Exception:
                    pass
