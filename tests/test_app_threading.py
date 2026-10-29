"""Real Qt signals and executor: only native devices/IPC/delivery are replaced."""
import threading
import time
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from katip.app import KatipApp
from katip.application.session import State
from katip.config import ConfigManager
from katip.domain.models import DictationResult
from katip.platform.target import Target


def test_capture_dsp_and_provider_run_off_gui_results_commit_on_gui(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    gui_id = threading.get_ident()
    worker_ids, commit_ids = [], []
    class Recorder:
        def __init__(self, **kwargs):
            self.device_index = -1
            self.vad_mode = 2
            self.is_recording = False
            self.is_capturing = False
            self.has_pending_audio = False
            self.last_error = ''
        def start_recording(self): self.is_recording = self.is_capturing = True
        def stop_recording(self):
            worker_ids.append(threading.get_ident())
            time.sleep(.02)
            self.is_recording = self.is_capturing = False
            self.has_pending_audio = True
            return b'RIFF' + b'\0' * 10000
        def discard_audio(self): self.has_pending_audio = False
        def terminate(self): pass
    class CheckedApp(KatipApp):
        def _on_work_event(self, event):
            commit_ids.append(threading.get_ident())
            super()._on_work_event(event)
    monkeypatch.setattr('katip.app.AudioRecorder', Recorder)
    monkeypatch.setattr('katip.app.SoundPlayer', Mock)
    monkeypatch.setattr('katip.app.HotkeyManager', lambda **kw: Mock(start=Mock(return_value=True)))
    monkeypatch.setattr('katip.app.TrayIcon', Mock)
    monkeypatch.setattr('katip.app.TextInjector', lambda **kw: Mock(inject_text=Mock(return_value=True), last_error=''))
    monkeypatch.setattr('katip.ui.pill.ensure_overlay_rule', lambda: True)
    monkeypatch.setattr('katip.app.QTimer.singleShot', lambda *args: None)
    monkeypatch.setattr('katip.platform.target.capture_target', lambda: Target('fake', 'editor'))
    monkeypatch.setattr('katip.platform.target.target_unchanged', lambda _: True)
    config = ConfigManager(tmp_path / 'config.json')
    config.set('provider', 'groq')
    app = CheckedApp(qapp, config=config)
    service = Mock()
    def transcribe(*args, **kwargs):
        worker_ids.append(threading.get_ident())
        return DictationResult('Ham.', 'Sonuç.', .01)
    service.transcribe_and_format.side_effect = transcribe
    app._get_groq_service = lambda **kw: service
    try:
        app.start_recording()
        assert app.session.state == State.RECORDING
        service.transcribe_and_format.assert_not_called()
        app.stop_recording_and_process(source='test')
        assert app.is_busy_processing
        deadline = time.monotonic() + 3
        while app.session.state != State.COMPLETED and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.001)
        assert app.session.state == State.COMPLETED, app.last_error
        assert worker_ids and all(value != gui_id for value in worker_ids)
        assert commit_ids and set(commit_ids) == {gui_id}
        assert app.last_text == 'Sonuç.' and not app.pending_audio
    finally:
        app._pool.shutdown(wait=True, cancel_futures=True)
        app.pill.close()
        app.tray.hide()
