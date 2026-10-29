"""Paste routing per desktop session; tools, portal and Win32 are fakes."""
import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from katip import injector as injector_module
from katip.injector import LinuxInjector, WindowsInjector

_linux_paste = LinuxInjector.simulate_paste
_windows_paste = WindowsInjector.simulate_paste


def linux(monkeypatch, session, tools, socket=False, results=None):
    monkeypatch.setattr(LinuxInjector, 'simulate_paste', _linux_paste)
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(injector_module, '_ydotool_socket_available', lambda: socket)
    calls = []
    def run(command, **_):
        calls.append(command[0])
        outcome = (results or {}).get(command[0], 0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(returncode=outcome)
    monkeypatch.setattr(injector_module, '_system_run', run)
    portal = Mock()
    portal.paste.return_value = True
    monkeypatch.setattr(injector_module, '_portal_keyboard', lambda: portal)
    backend = LinuxInjector()
    for tool in ('ydotool', 'xdotool', 'wtype'):
        setattr(backend, f'has_{tool}', tool in tools)
    return backend, calls, portal


def test_x11_prefers_xdotool_and_clears_held_hotkey_modifiers(monkeypatch):
    backend, calls, _ = linux(monkeypatch, 'x11', {'xdotool', 'ydotool'}, socket=True)
    seen = []
    monkeypatch.setattr(injector_module, '_system_run',
                        lambda command, **_: seen.append(command) or SimpleNamespace(returncode=0))
    assert backend.simulate_paste()
    assert seen == [['xdotool', 'key', '--clearmodifiers', 'ctrl+v']]


def test_wayland_never_counts_xdotool_as_a_paste(monkeypatch):
    # xdotool only reaches XWayland windows and exits 0 for a native editor.
    backend, calls, portal = linux(monkeypatch, 'wayland', {'xdotool'})
    assert backend.simulate_paste()
    assert calls == [] and portal.paste.called


def test_wayland_skips_ydotool_without_its_daemon(monkeypatch):
    backend, calls, portal = linux(monkeypatch, 'wayland', {'ydotool', 'wtype'},
                                   results={'wtype': 1})
    assert backend.simulate_paste()
    assert calls == ['wtype'] and portal.paste.called


def test_wayland_uses_running_ydotool_daemon_first(monkeypatch):
    backend, calls, portal = linux(monkeypatch, 'wayland', {'ydotool', 'wtype'}, socket=True)
    assert backend.simulate_paste()
    assert calls == ['ydotool'] and not portal.paste.called


def test_ydotool_timeout_is_never_followed_by_a_second_paste(monkeypatch):
    backend, calls, portal = linux(monkeypatch, 'wayland', {'ydotool', 'wtype'}, socket=True,
                                   results={'ydotool': subprocess.TimeoutExpired('ydotool', 2)})
    assert not backend.simulate_paste()
    assert calls == ['ydotool'] and not portal.paste.called


def test_wtype_terminal_mode_sends_ctrl_shift_v(monkeypatch):
    backend, _, portal = linux(monkeypatch, 'wayland', {'wtype'})
    backend.terminal_paste = True
    seen = []
    monkeypatch.setattr(injector_module, '_system_run',
                        lambda command, **_: seen.append(command) or SimpleNamespace(returncode=0))
    assert backend.simulate_paste()
    assert seen == [['wtype', '-M', 'ctrl', '-M', 'shift', 'v', '-m', 'shift', '-m', 'ctrl']]
    assert not portal.paste.called


def test_x11_without_tools_reports_failure(monkeypatch):
    backend, calls, portal = linux(monkeypatch, 'x11', set())
    assert not backend.simulate_paste() and not portal.paste.called


def test_ydotool_socket_lookup(monkeypatch, tmp_path):
    socket = tmp_path / '.ydotool_socket'
    monkeypatch.setenv('YDOTOOL_SOCKET', str(socket))
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'none'))
    monkeypatch.setattr(injector_module.os.path, 'exists', lambda path: path == str(socket))
    assert injector_module._ydotool_socket_available()
    monkeypatch.setattr(injector_module.os.path, 'exists', lambda path: False)
    assert not injector_module._ydotool_socket_available()


@pytest.mark.parametrize('held_polls, expect_forced_release', [(2, False), (10**6, True)])
def test_windows_paste_waits_for_hotkey_modifiers(monkeypatch, held_polls, expect_forced_release):
    import ctypes
    monkeypatch.setattr(WindowsInjector, 'simulate_paste', _windows_paste)
    polls = [0]
    def key_state(_key):
        polls[0] += 1
        return -32768 if polls[0] <= held_polls * 5 else 0
    events = []
    user32 = SimpleNamespace(GetAsyncKeyState=key_state,
                             keybd_event=lambda vk, scan, flags, extra: events.append((vk, flags)))
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32), raising=False)
    clock = iter(range(0, 10**7))
    monkeypatch.setattr(injector_module.time, 'monotonic', lambda: next(clock) * 0.01)
    monkeypatch.setattr(injector_module.time, 'sleep', lambda _: None)
    assert WindowsInjector().simulate_paste()
    forced = [(0x12, 2), (0x20, 2)]
    assert (events[:2] == forced) is expect_forced_release
    assert events[-4:] == [(0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)]


class PortalBus:
    """Answers RemoteDesktop requests the way xdg-desktop-portal does."""
    unique_name = ':1.7'

    def __init__(self, responses, fail_notify=0):
        from dbus_next import Variant
        self.connected = True
        self.calls = []
        self.responses = responses
        self.fail_notify = fail_notify
        self.Variant = Variant

    def add_message_handler(self, handler): self.handler = handler
    async def connect(self): return self
    def disconnect(self): self.connected = False

    async def call(self, message):
        from dbus_next import Message, MessageType
        self.calls.append(message)
        if message.member == 'NotifyKeyboardKeycode' and self.fail_notify:
            self.fail_notify -= 1
            return SimpleNamespace(message_type=MessageType.ERROR, body=[])
        if message.member in self.responses:
            token = message.body[-1]['handle_token'].value
            code, values = self.responses[message.member]
            self.handler(Message(message_type=MessageType.SIGNAL, path=f'/org/freedesktop/portal/desktop/request/1_7/{token}',
                                 interface='org.freedesktop.portal.Request', member='Response',
                                 signature='ua{sv}', body=[code, values]))
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])


def grant(Variant, devices=1, token='restore-1'):
    return {'CreateSession': (0, {'session_handle': Variant('o', '/session/1')}),
            'SelectDevices': (0, {}),
            'Start': (0, {'devices': Variant('u', devices), 'restore_token': Variant('s', token)})}


def run_paste(monkeypatch, tmp_path, bus, terminal=False, keyboard=None):
    pytest.importorskip('dbus_next')
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    monkeypatch.setattr('dbus_next.aio.MessageBus', lambda: bus)
    keyboard = keyboard or RemoteDesktopKeyboard(tmp_path / 'remote-desktop.token', permission_timeout=.2)
    return keyboard, asyncio.run(keyboard._paste([29, 42, 47] if terminal else [29, 47]))


def test_portal_grant_sends_ctrl_v_and_keeps_restore_token(monkeypatch, tmp_path):
    from dbus_next import Variant
    bus = PortalBus(grant(Variant))
    keyboard, sent = run_paste(monkeypatch, tmp_path, bus)
    assert sent
    keys = [(m.body[2], m.body[3]) for m in bus.calls if m.member == 'NotifyKeyboardKeycode']
    assert keys == [(29, 1), (47, 1), (47, 0), (29, 0)]
    assert (tmp_path / 'remote-desktop.token').read_text() == 'restore-1'
    assert (tmp_path / 'remote-desktop.token').stat().st_mode & 0o077 == 0
    # A second paste reuses the session without another permission request.
    bus.calls.clear()
    _, sent = run_paste(monkeypatch, tmp_path, bus, keyboard=keyboard)
    assert sent and [m.member for m in bus.calls] == ['NotifyKeyboardKeycode'] * 4


def test_portal_reuses_stored_grant(monkeypatch, tmp_path):
    from dbus_next import Variant
    (tmp_path / 'remote-desktop.token').write_text('restore-0')
    bus = PortalBus(grant(Variant, token='restore-2'))
    run_paste(monkeypatch, tmp_path, bus)
    select = next(m for m in bus.calls if m.member == 'SelectDevices')
    assert select.body[1]['restore_token'].value == 'restore-0'
    assert select.body[1]['persist_mode'].value == 2 and select.body[1]['types'].value == 1


@pytest.mark.parametrize('responses', [
    lambda V: {**grant(V), 'Start': (1, {})},                       # user refused
    lambda V: {**grant(V), 'Start': (0, {'devices': V('u', 2)})},   # pointer only
    lambda V: {'CreateSession': (2, {})},                           # backend error
    lambda V: {**grant(V), 'Start': None},                          # dialog left open
])
def test_portal_refusal_or_timeout_is_a_failed_paste(monkeypatch, tmp_path, responses):
    from dbus_next import Variant
    table = {k: v for k, v in responses(Variant).items() if v is not None}
    bus = PortalBus(table)
    keyboard, sent = run_paste(monkeypatch, tmp_path, bus)
    assert not sent and keyboard.session is None
    assert not any(m.member == 'NotifyKeyboardKeycode' for m in bus.calls)


def test_stale_portal_session_is_restarted_once(monkeypatch, tmp_path):
    from dbus_next import Variant
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    keyboard = RemoteDesktopKeyboard(tmp_path / 'token', permission_timeout=.2)
    bus = PortalBus(grant(Variant), fail_notify=1)
    keyboard.bus, keyboard.session = bus, '/session/old'
    bus.add_message_handler(keyboard._message)
    _, sent = run_paste(monkeypatch, tmp_path, bus, keyboard=keyboard)
    assert sent and keyboard.session == '/session/1'


def test_portal_closed_signal_forgets_the_session(tmp_path):
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    keyboard = RemoteDesktopKeyboard(tmp_path / 'token')
    keyboard.session = '/session/1'
    keyboard._message(SimpleNamespace(interface='org.freedesktop.portal.Session', member='Closed',
                                      path='/session/1', body=[]))
    assert keyboard.session is None


def test_portal_paste_runs_on_its_own_loop_and_times_out(tmp_path):
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    keyboard = RemoteDesktopKeyboard(tmp_path / 'token')
    async def hang(_keys):
        await asyncio.sleep(10)
    keyboard._paste = hang
    assert keyboard.paste(timeout=.05) is False
    async def ok(keys):
        return keys == [29, 42, 47]
    keyboard._paste = ok
    assert keyboard.paste(terminal=True, timeout=1)


@pytest.mark.parametrize('desktop, tools, socket, expected', [
    ('KDE', {'wtype'}, False, True), ('GNOME', set(), False, True),
    ('sway', {'wtype'}, False, False), ('KDE', {'ydotool'}, True, False)])
def test_portal_permission_is_requested_before_the_target_check(monkeypatch, desktop, tools, socket, expected):
    backend, _, portal = linux(monkeypatch, 'wayland', tools, socket=socket)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', desktop)
    backend.prepare_paste()
    assert portal.ensure_session.called is expected


def test_cancelled_portal_paste_releases_pressed_keys(monkeypatch, tmp_path):
    from dbus_next import Variant
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    keyboard = RemoteDesktopKeyboard(tmp_path / 'token', permission_timeout=.2)
    bus = PortalBus(grant(Variant))
    keyboard.bus, keyboard.session = bus, '/session/1'
    bus.add_message_handler(keyboard._message)
    async def scenario():
        real_sleep = asyncio.sleep
        async def stall(_delay):
            await real_sleep(10)
        monkeypatch.setattr('katip.platform.remote_desktop.asyncio.sleep', stall)
        task = asyncio.ensure_future(keyboard._paste([29, 47]))
        await real_sleep(.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    keys = [(m.body[2], m.body[3]) for m in bus.calls if m.member == 'NotifyKeyboardKeycode']
    assert keys == [(29, 1), (47, 1), (47, 0), (29, 0)] and keyboard.session is None


def test_ensure_session_reuses_a_live_session(tmp_path):
    from katip.platform.remote_desktop import RemoteDesktopKeyboard
    keyboard = RemoteDesktopKeyboard(tmp_path / 'token')
    keyboard.session = '/session/1'
    assert keyboard.ensure_session(timeout=1)
    async def broken():
        raise RuntimeError('portal gone')
    keyboard.session = None
    keyboard._start_session = broken
    assert keyboard.ensure_session(timeout=1) is False
