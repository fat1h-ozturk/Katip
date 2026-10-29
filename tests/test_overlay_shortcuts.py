"""Recording-indicator focus safety and hotkey backend fallback, all against fakes."""

import asyncio
import importlib
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from katip import hotkey
from katip.platform.shortcuts import PortalLost, PortalUnavailable, ShortcutPortal

try:
    from dbus_next import Message, MessageType, Variant
except ImportError:
    Message = MessageType = Variant = None

# conftest replaces the Linux listener per test; keep the real one for these tests.
_original_linux_listener = hotkey.HotkeyManager._run_linux_listener
SESSION = '/org/freedesktop/portal/desktop/session/1_42/session'
needs_dbus = pytest.mark.skipif(Message is None, reason="Linux DBus portal dependency")


class RecordingStop(threading.Event):
    """Records backoff waits instead of sleeping through them."""
    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.is_set()


class FakeBus:
    unique_name = ':1.42'

    def __init__(self, responses, after_bind=None):
        self.responses = responses
        self.after_bind = after_bind
        self.connected = True
        self.calls = []

    def add_message_handler(self, handler):
        self.handler = handler

    async def connect(self):
        return self

    def disconnect(self):
        self.connected = False

    def signal(self, path, interface, member, signature, body):
        self.handler(Message(message_type=MessageType.SIGNAL, path=path, interface=interface,
                             member=member, signature=signature, body=body))

    def session_signal(self, member):
        if member == 'Closed':
            self.signal(SESSION, ShortcutPortal.SESSION, 'Closed', 'a{sv}', [{}])
        else:
            self.signal(ShortcutPortal.ROOT, ShortcutPortal.INTERFACE, member, 'osta{sv}',
                        [SESSION, 'dictation', 1, {}])

    async def call(self, message):
        self.calls.append(message)
        response = self.responses.get(message.member)
        if response is not None:
            token = message.body[-1]['handle_token'].value
            self.signal(f'/org/freedesktop/portal/desktop/request/1_42/{token}',
                        'org.freedesktop.portal.Request', 'Response', 'ua{sv}',
                        [response, {'session_handle': Variant('o', SESSION)}])
        if message.member == 'BindShortcuts' and self.after_bind:
            asyncio.get_running_loop().call_later(.05, self.after_bind, self)
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])


def wayland_manager(monkeypatch, bus, trigger_mode='toggle'):
    monkeypatch.setattr('dbus_next.aio.MessageBus', lambda: bus)
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setattr(hotkey, 'HAS_EVDEV', True)
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_linux_listener', _original_linux_listener)
    statuses, triggers, evdev = [], [], []
    def fake_evdev(self):
        evdev.append(True)
        self.hotkey_status = 'evdev_active'
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_evdev_listener', fake_evdev)
    manager = hotkey.HotkeyManager('Ctrl+Alt+Space', trigger_mode,
                                   on_trigger=lambda kind, _source: triggers.append(kind),
                                   on_status=statuses.append)
    manager.is_running = True
    manager._stop_event = RecordingStop()
    return manager, statuses, triggers, evdev


@needs_dbus
@pytest.mark.parametrize('responses', [
    {'CreateSession': 2},
    {'CreateSession': 0, 'BindShortcuts': 2},
    {'CreateSession': None},
    {'CreateSession': 0, 'BindShortcuts': None},
], ids=['create-error', 'bind-error', 'create-timeout', 'bind-timeout'])
def test_portal_backend_error_or_timeout_falls_back_to_evdev(monkeypatch, responses):
    monkeypatch.setattr(ShortcutPortal, 'PERMISSION_WAIT', .3)
    bus = FakeBus(responses)
    manager, statuses, _, evdev = wayland_manager(monkeypatch, bus)
    manager._run_linux_listener()
    assert 'portal_denied' not in statuses
    assert statuses[-2:] == ['portal_unavailable', 'evdev_active']
    assert evdev == [True]
    assert manager._stop_event.waits == [1.0]
    assert not bus.connected
    if None in responses.values():
        assert any(call.member == 'Close' and '/request/' in call.path for call in bus.calls)


@needs_dbus
def test_bind_shortcuts_denial_is_respected_without_raw_devices(monkeypatch):
    bus = FakeBus({'CreateSession': 0, 'BindShortcuts': 1})
    manager, statuses, _, evdev = wayland_manager(monkeypatch, bus)
    manager._run_linux_listener()
    assert statuses[-1] == 'portal_denied'
    assert evdev == []
    assert bus.calls[-1].member == 'Close' and bus.calls[-1].path == SESSION


@needs_dbus
@pytest.mark.parametrize('loss', ['closed', 'disconnect'])
def test_portal_loss_reports_lost_releases_held_key_and_falls_back(monkeypatch, loss):
    def lose(bus):
        bus.session_signal('Activated')
        if loss == 'closed':
            bus.session_signal('Closed')
        else:
            bus.connected = False
    bus = FakeBus({'CreateSession': 0, 'BindShortcuts': 0}, after_bind=lose)
    manager, statuses, triggers, evdev = wayland_manager(monkeypatch, bus, 'push_to_talk')
    manager._run_linux_listener()
    assert statuses[-3:] == ['portal_active', 'portal_lost', 'evdev_active']
    assert triggers == ['start', 'stop']
    assert evdev == [True]
    assert manager._stop_event.waits == [1.0]
    assert not any(call.member == 'Close' and call.path == SESSION for call in bus.calls)


@needs_dbus
def test_portal_loss_raises_portal_lost_and_trigger_errors_are_contained(monkeypatch):
    def lose(bus):
        bus.session_signal('Activated')
        bus.session_signal('Closed')
    bus = FakeBus({'CreateSession': 0, 'BindShortcuts': 0}, after_bind=lose)
    monkeypatch.setattr('dbus_next.aio.MessageBus', lambda: bus)
    statuses = []
    portal = ShortcutPortal('Ctrl+Alt+Space', Mock(side_effect=RuntimeError('boom')), Mock(),
                            threading.Event(), statuses.append)
    with pytest.raises(PortalLost):
        asyncio.run(portal.run())
    assert issubclass(PortalLost, PortalUnavailable)
    assert statuses == ['portal_active', 'portal_lost']
    portal.on_press.assert_called_once()


def test_crashing_evdev_listener_retries_with_backoff(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    monkeypatch.setattr(hotkey, 'HAS_EVDEV', True)
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_linux_listener', _original_linux_listener)
    runs = []
    def flaky(self):
        runs.append(True)
        if len(runs) < 3:
            raise OSError('device vanished')
        self.hotkey_status = 'evdev_active'
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_evdev_listener', flaky)
    statuses = []
    manager = hotkey.HotkeyManager(on_status=statuses.append)
    manager.is_running = True
    manager._stop_event = RecordingStop()
    manager._run_linux_listener()
    assert len(runs) == 3
    assert manager._stop_event.waits == [1.0, 2.0]
    assert 'listener_error' in statuses and statuses[-1] == 'evdev_active'


def test_crashing_evdev_listener_stops_retrying_when_stopped(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    monkeypatch.setattr(hotkey, 'HAS_EVDEV', True)
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_linux_listener', _original_linux_listener)
    broken = Mock(side_effect=OSError('broken'))
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_evdev_listener', lambda self: broken())
    manager = hotkey.HotkeyManager()
    manager.is_running = True
    manager._stop_event = RecordingStop()
    manager._stop_event.set()
    manager._run_linux_listener()
    broken.assert_called_once()


# --- Recording indicator ---------------------------------------------------

@pytest.fixture
def overlay(monkeypatch):
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication
    import katip.ui.overlay_controller as module
    from katip.ui.pill import FloatingPill
    QApplication.instance() or QApplication([])
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    pill = FloatingPill()
    class Shows(QObject):
        count = 0
        def eventFilter(self, _watched, event):
            if event.type() == QEvent.Type.Show:
                self.count += 1
            return False
    shows = Shows()
    pill.installEventFilter(shows)
    pill.shows = shows
    controller = module.LayerOverlayController(pill)
    process = Mock()
    process.readAllStandardOutput.return_value = b'READY\n'
    process.state.return_value = module.QProcess.ProcessState.Running
    process.write.return_value = 1
    controller.process = process
    yield controller, pill, process
    controller.close()


def test_ready_helper_keeps_qt_fallback_unmapped_but_current(overlay):
    controller, pill, process = overlay
    controller._read_ready()
    controller.show_recording('chat')
    assert not pill.isVisible() and pill.state == 'recording' and pill.mode == 'chat'
    controller.show_processing()
    controller.show_error('Ağ hatası')
    controller.hide_pill()
    controller.show_error('Ağ hatası')
    # Showing-then-hiding would still flash a focus-taking toplevel; it must never map.
    assert pill.shows.count == 0
    assert not pill.isVisible() and pill.state == 'error'
    assert process.write.call_args.args[0] == 'ERROR Ağ hatası\n'.encode('utf-8')
    # Helper death still hands the retained state to the Qt pill.
    controller._failed()
    assert pill.isVisible() and pill.state == 'error'
    controller.show_success(0.5)
    assert pill.isVisible() and pill.state == 'success'


def test_pending_helper_does_not_map_qt_pill_until_timeout(overlay):
    controller, pill, process = overlay
    controller.show_recording('dictation')
    assert pill.shows.count == 0 and pill.state == 'recording'
    controller._failed()  # READY timeout
    assert pill.isVisible()
    process.kill.assert_called_once()
    # A late READY from the killed helper must not take the indicator back.
    controller._read_ready()
    controller.show_processing()
    process.write.assert_not_called()
    assert pill.isVisible() and pill.state == 'processing'


def test_ready_helper_write_failure_falls_back_to_qt(overlay):
    controller, pill, process = overlay
    controller._read_ready()
    process.write.return_value = -1
    controller.show_recording('dictation')
    assert pill.isVisible() and pill.state == 'recording'


@pytest.mark.parametrize('find_spec', [lambda _name: None, Mock(side_effect=ValueError('gi.__spec__ is None'))])
def test_frozen_build_without_pygobject_uses_qt_overlay(monkeypatch, find_spec):
    from PySide6.QtWidgets import QApplication
    import katip.ui.overlay_controller as module
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'wayland')
    monkeypatch.setattr(module, 'find_library', lambda _name: 'libgtk4-layer-shell.so.0')
    monkeypatch.setattr(module.importlib.util, 'find_spec', find_spec)
    monkeypatch.setattr(module.LayerOverlayController, '_start_overlay',
                        Mock(side_effect=AssertionError('helper must not start')))
    fallback = Mock(state='recording')
    controller = module.LayerOverlayController(fallback)
    assert controller.process is None
    controller.show_recording('dictation')
    fallback.show_recording.assert_called_once_with('dictation')
    controller.close()


@pytest.mark.parametrize('supported', [True, False, None], ids=['supported', 'unsupported', 'old-library'])
def test_gtk_helper_prints_ready_only_with_layer_shell(monkeypatch, capsys, supported):
    gi = types.ModuleType('gi')
    gi.require_version = lambda *_: None
    repository = types.ModuleType('gi.repository')
    for name in ('Gtk', 'Gtk4LayerShell', 'Gdk', 'GLib'):
        setattr(repository, name, MagicMock(name=name))
    if supported is None:
        del repository.Gtk4LayerShell.is_supported
    else:
        repository.Gtk4LayerShell.is_supported.return_value = supported
    repository.Gtk.Application.return_value.run.return_value = 0
    gi.repository = repository
    monkeypatch.setitem(sys.modules, 'gi', gi)
    monkeypatch.setitem(sys.modules, 'gi.repository', repository)
    monkeypatch.delitem(sys.modules, 'katip.ui.overlay_gtk', raising=False)
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(fileno=lambda: 0))
    try:
        module = importlib.import_module('katip.ui.overlay_gtk')
        helper = module.LayerOverlayApp()
        app = Mock()
        helper.on_activate(app)
        out = capsys.readouterr().out
        if supported:
            assert out == 'READY\n'
            repository.Gtk4LayerShell.init_for_window.assert_called_once()
            helper.run()
        else:
            assert 'READY' not in out
            app.quit.assert_called_once()
            repository.Gtk.ApplicationWindow.assert_not_called()
            repository.Gtk4LayerShell.init_for_window.assert_not_called()
            with pytest.raises(SystemExit) as exit_info:
                helper.run()
            assert exit_info.value.code != 0
    finally:
        sys.modules.pop('katip.ui.overlay_gtk', None)
        import katip.ui
        if hasattr(katip.ui, 'overlay_gtk'):
            delattr(katip.ui, 'overlay_gtk')
