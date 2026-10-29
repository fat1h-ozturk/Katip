"""XDG GlobalShortcuts session on a dedicated asyncio/DBus thread."""

import asyncio
from uuid import uuid4


class PortalUnavailable(RuntimeError):
    pass


class ShortcutPortal:
    ROOT = "/org/freedesktop/portal/desktop"
    DEST = "org.freedesktop.portal.Desktop"
    INTERFACE = "org.freedesktop.portal.GlobalShortcuts"

    def __init__(self, hotkey, on_press, on_release, stop_event, status):
        self.hotkey = hotkey
        self.on_press = on_press
        self.on_release = on_release
        self.stop = stop_event
        self.status = status
        self.session = None
        self.pending = {}
        self.bus = None

    def _message(self, message):
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future and not future.done():
                future.set_result(message.body)
        elif message.interface == self.INTERFACE and self.session and len(message.body) >= 2:
            if message.body[0] == self.session and message.body[1] == "dictation":
                if message.member == "Activated":
                    self.on_press()
                elif message.member == "Deactivated":
                    self.on_release()

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
            for _ in range(300):
                if self.stop.is_set():
                    raise asyncio.CancelledError()
                if future.done():
                    return future.result()
                await asyncio.sleep(.1)
            await self._call(path, "org.freedesktop.portal.Request", "Close")
            return [1, {}]
        finally:
            self.pending.pop(path, None)

    async def run(self):
        from dbus_next import Message, Variant
        from dbus_next.aio import MessageBus
        try:
            self.bus = await asyncio.wait_for(MessageBus().connect(), timeout=3)
            self.bus.add_message_handler(self._message)
            for interface in ("org.freedesktop.portal.Request", self.INTERFACE):
                await asyncio.wait_for(self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                    body=[f"type='signal',sender='{self.DEST}',interface='{interface}'"])), timeout=3)
            response, values = await self._request("CreateSession", "a{sv}", [],
                {"session_handle_token": Variant("s", "katip" + uuid4().hex)})
            if response != 0:
                self.status("portal_denied")
                return
            self.session = values["session_handle"].value
            accelerator = self.hotkey.replace("Ctrl", "CTRL").replace("Alt", "ALT").replace("Shift", "SHIFT").replace("Super", "LOGO")
            response, _ = await self._request("BindShortcuts", "oa(sa{sv})sa{sv}",
                [self.session, [["dictation", {"description": Variant("s", "Kâtip dikte"),
                    "preferred_trigger": Variant("s", accelerator)}]], ""], {})
            if response != 0:
                self.status("portal_denied")
                return
            self.status("portal_active")
            while not self.stop.is_set() and self.bus.connected:
                await asyncio.sleep(.1)
        except asyncio.CancelledError:
            pass
        except Exception:
            raise PortalUnavailable("Shortcut portal unavailable") from None
        finally:
            if self.bus:
                if self.session:
                    try:
                        await self._call(self.session, "org.freedesktop.portal.Session", "Close")
                    except Exception:
                        pass
                self.bus.disconnect()
