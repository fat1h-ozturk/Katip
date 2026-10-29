"""Optional layer-shell helper with an asynchronous ready handshake and Qt fallback."""
import importlib.util
import os
import sys
from ctypes.util import find_library

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer


def _has_gi():
    # Frozen builds ship without PyGObject; any lookup failure means the Qt pill.
    try:
        return importlib.util.find_spec('gi') is not None
    except (ImportError, ValueError):
        return False


class LayerOverlayController(QObject):
    def __init__(self, fallback):
        super().__init__()
        self.fallback = fallback
        self.clicked = fallback.clicked
        self.current_mode = 'dictation'
        self.process = None
        self._closing = False
        self._ready = False
        self._dead = False
        self._last = None
        self._stdout = bytearray()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._failed)
        if (os.environ.get('XDG_SESSION_TYPE') == 'wayland'
                and os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
                and find_library('gtk4-layer-shell') and _has_gi()):
            self._start_overlay()

    def _start_overlay(self):
        process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        layer = find_library('gtk4-layer-shell')
        if layer:
            existing = env.value('LD_PRELOAD')
            env.insert('LD_PRELOAD', f'{layer}:{existing}' if existing else layer)
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read_ready)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.errorOccurred.connect(self._failed)
        process.finished.connect(self._failed)
        self.process = process
        # A frozen executable is a bootloader, not a Python interpreter.
        args = ['--internal-overlay'] if getattr(sys, 'frozen', False) else ['-m', 'katip', '--internal-overlay']
        process.start(sys.executable, args)
        self._timer.start(1500)

    def _read_ready(self):
        if not self.process or self._dead:
            return
        self._stdout.extend(bytes(self.process.readAllStandardOutput()))
        if len(self._stdout) > 1024:
            self._failed()
            return
        if b'READY\n' in self._stdout:
            self._ready = True
            self._timer.stop()
            if self._last:
                self._send_cmd(self._last)

    def _failed(self, *_):
        if self._closing:
            return
        self._ready = False
        self._dead = True
        self._timer.stop()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        # The Qt indicator has retained its current state throughout.
        if self._last and self._last != 'HIDE' and self.fallback.state != 'hidden':
            self.fallback._show_overlay()

    def _send_cmd(self, command):
        self._last = command
        if not self._ready:
            return
        if (self.process and self.process.state() == QProcess.ProcessState.Running
                and self.process.write((command + '\n').encode('utf-8')) >= 0):
            self.fallback.hide()
        else:
            self._failed()

    def _update_fallback(self, method, *args):
        if self.process is None or self._dead:
            method(*args)
            return
        # The helper owns (or may soon own) the indicator: keep the Qt pill's state
        # current for a later fallback, but never map a focus-taking toplevel.
        show = self.fallback._show_overlay
        self.fallback._show_overlay = lambda: None
        try:
            method(*args)
        finally:
            self.fallback._show_overlay = show

    def show_recording(self, mode):
        self.current_mode = mode
        self._update_fallback(self.fallback.show_recording, mode)
        self._send_cmd(f'RECORDING {mode}')

    def show_processing(self):
        self._update_fallback(self.fallback.show_processing)
        self._send_cmd('PROCESSING')

    def show_success(self, latency=0.0):
        self._update_fallback(self.fallback.show_success, latency)
        self._send_cmd(f'SUCCESS {latency}')

    def show_error(self, message):
        self._update_fallback(self.fallback.show_error, message)
        self._send_cmd('ERROR ' + ' '.join(message.splitlines())[:300])

    def hide_pill(self):
        self.fallback.hide_pill()
        self._send_cmd('HIDE')

    def set_mode(self, mode):
        self.current_mode = mode
        self.fallback.set_mode(mode)

    def set_audio_level(self, level):
        self.fallback.set_audio_level(level)

    def close(self):
        self._closing = True
        self._last = None
        self._timer.stop()
        if self.process:
            self.process.kill()
            # QProcess owns reaping; never wait for a subprocess on the GUI thread.
        self.fallback.close()
