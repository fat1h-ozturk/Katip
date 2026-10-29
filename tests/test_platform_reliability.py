import asyncio
from types import SimpleNamespace
import threading
import sys
from katip import hotkey as hotkey_module
_original_evdev_listener = hotkey_module.HotkeyManager._run_evdev_listener
from unittest.mock import Mock

import pytest
try:
    from dbus_next import Message, MessageType, Variant
except ImportError:
    Message = MessageType = Variant = None

from katip.platform.shortcuts import ShortcutPortal
from katip.infrastructure.secrets import SecretStore
from katip.runtime import app_id, profile
from katip.config import get_config_dir


@pytest.mark.parametrize('deny', [False, True])
@pytest.mark.skipif(Message is None, reason="Linux DBus portal dependency")
def test_portal_protocol_owns_one_session_and_closes(monkeypatch, deny):
    stop = threading.Event()
    statuses, triggers, calls = [], [], []
    session = '/org/freedesktop/portal/desktop/session/1_42/session'
    class Bus:
        unique_name = ':1.42'
        connected = True
        def add_message_handler(self, handler): self.handler = handler
        async def connect(self): return self
        def disconnect(self): self.connected = False
        async def call(self, message):
            calls.append(message)
            if message.member in ('CreateSession', 'BindShortcuts'):
                token = message.body[-1]['handle_token'].value
                path = f'/org/freedesktop/portal/desktop/request/1_42/{token}'
                self.handler(Message(message_type=MessageType.SIGNAL, path=path,
                    interface='org.freedesktop.portal.Request', member='Response',
                    signature='ua{sv}', body=[1 if deny else 0, {'session_handle': Variant('o', session)}]))
                if message.member == 'BindShortcuts':
                    assert message.signature == 'oa(sa{sv})sa{sv}'
                    for member in ('Activated', 'Deactivated'):
                        self.handler(Message(message_type=MessageType.SIGNAL, path=ShortcutPortal.ROOT,
                            interface=ShortcutPortal.INTERFACE, member=member, signature='osta{sv}',
                            body=[session, 'dictation', 1, {}]))
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])
    bus = Bus()
    monkeypatch.setattr('dbus_next.aio.MessageBus', lambda: bus)
    def status(value):
        statuses.append(value)
        stop.set()
    portal = ShortcutPortal('Ctrl+Alt+Space', lambda: triggers.append('start'),
                            lambda: triggers.append('stop'), stop, status)
    asyncio.run(portal.run())
    assert statuses == ['portal_denied' if deny else 'portal_active']
    assert triggers == ([] if deny else ['start', 'stop'])
    assert not bus.connected
    if not deny:
        assert calls[-1].member == 'Close' and calls[-1].path == session


def test_plaintext_credential_backend_is_rejected(tmp_path, monkeypatch):
    backend = Mock()
    monkeypatch.setattr('keyring.get_keyring', lambda: backend)
    store = SecretStore(tmp_path / 'config.json')
    with pytest.raises(RuntimeError):
        store.put('ref', 'private')
    backend.set_password.assert_not_called()


def test_os_vault_round_trip_and_redacted_failure(tmp_path, monkeypatch):
    class Backend:
        __module__ = 'keyring.backends.SecretService'
        def __init__(self): self.values = {}
        def set_password(self, service, reference, value): self.values[(service, reference)] = value
        def get_password(self, service, reference): return self.values.get((service, reference))
        def delete_password(self, service, reference): self.values.pop((service, reference), None)
    backend = Backend()
    monkeypatch.setattr('keyring.get_keyring', lambda: backend)
    store = SecretStore(tmp_path / 'config.json')
    store.put('reference', 'value')
    assert store.get('reference') == 'value'
    store.delete('reference')
    assert store.get('reference') is None
    monkeypatch.setattr(backend, 'set_password', Mock(side_effect=RuntimeError('SECRET')))
    with pytest.raises(RuntimeError) as error:
        store.put('reference', 'value')
    assert 'SECRET' not in str(error.value)


def test_candidate_config_and_desktop_are_isolated(tmp_path, monkeypatch):
    from katip import desktop
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'AppData'))
    monkeypatch.setenv('HOME', str(tmp_path))
    normal = get_config_dir()
    monkeypatch.setenv('KATIP_PROFILE', 'candidate')
    assert app_id() == 'katip-candidate'
    assert get_config_dir() != normal
    assert not desktop.install_desktop_entry()
    assert not desktop.uninstall_desktop_entry()
    assert not desktop.set_autostart(True)
    assert not normal.exists()


@pytest.mark.parametrize('value', ['../elsewhere', 'A', 'a' * 33])
def test_invalid_profile_cannot_escape_directories(monkeypatch, value):
    monkeypatch.setenv('KATIP_PROFILE', value)
    with pytest.raises(RuntimeError): profile()


def test_layer_helper_ready_failure_and_close_use_qt_fallback(monkeypatch):
    from PySide6.QtWidgets import QApplication
    import katip.ui.overlay_controller as module
    qapp = QApplication.instance() or QApplication([])
    assert qapp is not None
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    fallback = Mock(state='recording')
    overlay = module.LayerOverlayController(fallback)
    overlay.show_recording('dictation')
    fallback.show_recording.assert_called_once_with('dictation')
    process = Mock()
    process.readAllStandardOutput.return_value = b'READY\n'
    process.state.return_value = module.QProcess.ProcessState.Running
    process.write.return_value = 1
    overlay.process = process
    overlay._read_ready()
    process.write.assert_called_once_with(b'RECORDING dictation\n')
    fallback.hide.assert_called_once()
    overlay._failed()
    process.kill.assert_called_once()
    fallback._show_overlay.assert_called_once()
    fallback._show_overlay.reset_mock()
    overlay.close()
    overlay._failed()
    fallback._show_overlay.assert_not_called()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux input-device backend")
def test_evdev_disconnect_is_closed_and_does_not_spin(monkeypatch):
    from katip import hotkey
    original = _original_evdev_listener
    # conftest blocks real devices; re-enable only against these fake descriptors.
    monkeypatch.setattr(hotkey.HotkeyManager, '_run_evdev_listener', original)
    manager = hotkey.HotkeyManager()
    manager.is_running = True
    device = Mock(name='device')
    device.name = 'USB Keyboard'
    device.capabilities.return_value = {hotkey.ecodes.EV_KEY: [hotkey.ecodes.KEY_A]}
    monkeypatch.setattr(hotkey.evdev, 'list_devices', lambda: ['/dev/fake'])
    monkeypatch.setattr(hotkey.evdev, 'InputDevice', lambda _: device)
    def read():
        manager.is_running = False
        raise OSError('disconnected')
    device.read.side_effect = read
    monkeypatch.setattr(hotkey.select, 'select', lambda *_: ([device], [], []))
    manager._run_evdev_listener()
    device.close.assert_called_once()
    assert manager.hotkey_status == 'stopped'


def test_mac_target_detects_window_change_inside_same_application(monkeypatch):
    from katip.platform import target
    app = Mock()
    app.processIdentifier.return_value = 77
    workspace = Mock()
    workspace.sharedWorkspace.return_value.frontmostApplication.return_value = app
    windows = [{'owner': 77, 'layer': 0, 'number': 123}]
    quartz = SimpleNamespace(kCGWindowListOptionOnScreenOnly=1, kCGNullWindowID=0,
        kCGWindowOwnerPID='owner', kCGWindowLayer='layer', kCGWindowNumber='number',
        CGWindowListCopyWindowInfo=lambda *_: windows)
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(NSWorkspace=workspace))
    monkeypatch.setitem(sys.modules, 'Quartz', quartz)
    monkeypatch.setattr(target.sys, 'platform', 'darwin')
    original = target.capture_target()
    assert original.identity == '77:123'
    windows[0]['number'] = 124
    assert not target.target_unchanged(original)
    windows.clear()
    assert target.capture_target() is None
