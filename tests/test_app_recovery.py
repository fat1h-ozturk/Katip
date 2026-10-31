"""Session/coordinator regressions. Device, HTTP and desktop boundaries are fakes."""
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from katip.app import KatipApp
from katip.application.session import SessionController, State, JobEvent
from katip.config import ConfigManager
from katip.diagnostics import Diagnostics
from katip.services.groq import GroqResult
from katip.platform.target import Target


def make_app(tmp_path):
    app = object.__new__(KatipApp)
    app.config = ConfigManager(tmp_path / 'config.json')
    app.session = SessionController()
    app.session.begin(app.config.data)
    app.session.state = State.TRANSCRIBING
    app.diagnostics = Diagnostics()
    app._capture_job_id = app.session.job.id
    app._target = Target('fake', 'editor')
    app.session.job.target = app._target
    app.recorder = Mock(is_recording=False, is_capturing=False, has_pending_audio=False, last_error='', device_index=-1, device_name='', vad_mode=2)
    app.recorder.raw_wav.return_value = b'original-raw-wav'
    app.recorder.retry_audio.return_value = b'retained-frames'
    app.pending_audio = b'original-audio'
    app.last_text = ''
    app.last_groq_result = None
    app.last_error = ''
    app.settings_dialog = None
    app.q_app = Mock()
    app.q_app.activeModalWidget.return_value = None
    app.events = deque()
    app.signals = SimpleNamespace(work_event=SimpleNamespace(emit=app.events.append))
    app.sound, app.pill, app.tray = Mock(), Mock(), Mock()
    app.injector = Mock(last_error='Paste failed')
    app.injector.inject_text.return_value = True
    service = Mock(last_warning='')
    service.transcribe_and_format.return_value = GroqResult(None, 'Complete text', .2, provider='gemini')
    app._get_gemini_service = lambda: service
    # Execute worker jobs synchronously, but keep GUI commits explicitly queued.
    app._spawn = lambda target, *args: target(*args)
    return app, service


def drain(app):
    while app.events:
        app._on_work_event(app.events.popleft())


@pytest.fixture(autouse=True)
def unchanged_target(monkeypatch):
    monkeypatch.setattr('katip.platform.target.target_unchanged', lambda _: True)
    monkeypatch.setattr('katip.platform.target.capture_target', lambda: Target('fake', 'editor'))


def test_worker_does_not_write_ui_state_and_commit_releases_audio(tmp_path):
    app, _ = make_app(tmp_path)
    app._process_audio_worker(app.pending_audio)
    assert app.last_text == '' and app.pending_audio
    assert app.is_busy_processing
    drain(app)
    assert app.last_text == 'Complete text'
    assert not app.pending_audio and not app.is_busy_processing
    app.recorder.discard_audio.assert_called_once()


@pytest.mark.parametrize('second_status', [200, 429])
def test_groq_rate_limit_wait_is_shown_in_tray_and_result_keeps_recovery_contract(
        tmp_path, monkeypatch, second_status):
    import json
    from katip.infrastructure.http_transport import Response
    from katip.services.groq import GroqService
    app, _ = make_app(tmp_path)
    app.config.data['provider'] = 'groq'
    app.session.job.settings['provider'] = 'groq'
    monkeypatch.setattr(app.session.job.cancelled, 'wait', lambda _: False)
    service = GroqService('fake')
    limited = Response(429, b'{}', {'retry-after': '0.01'})
    success = Response(200, json.dumps({'choices': [{'finish_reason': 'stop',
        'message': {'content': '{"text":"Düzenlenmiş."}'}}]}).encode(), {})
    post = Mock(side_effect=[Response(200, '{"text":"Eksiksiz ham metin."}'.encode(), {}),
                             limited, success if second_status == 200 else limited])
    monkeypatch.setattr(service._session, 'post', post)
    app._service = Mock(return_value=service)
    app._start_processing(app.pending_audio, auto_paste=False)
    app.tray.showMessage.assert_not_called()  # GUI events are still queued.
    drain(app)
    messages = [call.args[1] for call in app.tray.showMessage.call_args_list]
    assert 'Hız sınırı, 1 sn sonra yeniden deneniyor' in messages
    assert post.call_count == 3
    assert app.last_groq_result.raw_transcript == 'Eksiksiz ham metin.'
    app.injector.inject_text.assert_not_called()
    if second_status == 200:
        assert app.last_text == 'Düzenlenmiş.' and app.session.state == State.READY
        assert app.last_error == 'Metin hazır. Son Sonuç menüsünden kopyalayabilirsiniz.'
        assert not app.last_groq_result.warning
    else:
        assert app.last_text == 'Eksiksiz ham metin.' and app.session.state == State.ERROR
        assert 'HTTP 429' in app.last_error and 'Son Sonuç' in app.last_error
        assert 'eksiksiz ham transkript korundu' in app.last_error
        assert app.pending_audio


def test_stale_rate_limit_wait_does_not_notify_current_job(tmp_path):
    app, _ = make_app(tmp_path)
    app._on_work_event(JobEvent('stale-job', 0, 'rate_limit_wait', 5))
    app.tray.showMessage.assert_not_called()


def test_failed_injection_never_reports_success_and_keeps_result(tmp_path):
    app, _ = make_app(tmp_path)
    app.injector.inject_text.return_value = False
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert app.last_text == 'Complete text' and app.pending_audio
    assert app.session.state == State.READY and app.last_error.startswith('Paste failed')
    app.pill.show_success.assert_not_called()


def test_unverifiable_target_is_pasted_into_the_focused_window(tmp_path):
    # Wayland exposes no window identity; refusing to paste there is itself the failure.
    app, _ = make_app(tmp_path)
    app._target = None
    app.session.job.target = None
    app._process_audio_worker(app.pending_audio)
    drain(app)
    app.injector.inject_text.assert_called_once()
    args, kwargs = app.injector.inject_text.call_args
    assert args == ('Complete text',) and callable(kwargs['before_paste'])
    kwargs['before_paste']()  # No known target to compare, so only cancellation can stop it.
    assert app.session.state == State.COMPLETED and not app.pending_audio
    app.pill.show_success.assert_called_once()
    assert app.diagnostics.snapshot()[-1]['code'] == 'INPUT_SENT'


def test_empty_output_is_actionable_and_preserves_audio(tmp_path):
    app, service = make_app(tmp_path)
    service.transcribe_and_format.return_value = GroqResult('', None, .1)
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert app.session.state == State.ERROR and 'EMPTY_OUTPUT' in app.last_error
    assert app.pending_audio


def test_formatter_fallback_requires_review_before_injection(tmp_path):
    app, service = make_app(tmp_path)
    from dataclasses import replace
    service.transcribe_and_format.return_value = replace(service.transcribe_and_format.return_value, warning='Raw transcript preserved')
    app._process_audio_worker(app.pending_audio)
    drain(app)
    app.injector.inject_text.assert_not_called()
    assert app.last_text == 'Complete text' and app.pending_audio


def test_unexpected_service_error_does_not_expose_private_message(tmp_path):
    app, service = make_app(tmp_path)
    service.transcribe_and_format.side_effect = RuntimeError('SECRET TRANSCRIPT')
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert 'SECRET' not in app.last_error and 'UNEXPECTED_ERROR' in app.last_error
    assert app.pending_audio


@pytest.mark.parametrize('state', ['is_recording', 'is_capturing'])
def test_recording_settings_cannot_replace_recorder(tmp_path, state):
    app, _ = make_app(tmp_path)
    app.session.state = State.READY
    setattr(app.recorder, state, True)
    original = app.recorder
    app._on_config_updated()
    assert app.recorder is original
    original.terminate.assert_not_called()


def test_capture_error_is_drained_off_gui_and_retained(tmp_path):
    app, _ = make_app(tmp_path)
    app.pending_audio = b''
    app.session.state = State.RECORDING
    app.recorder.last_error = '[CAPTURE_READ_ERROR] Kayıt kesildi.'
    app.recorder.stop_recording.return_value = b'partial-recording'
    app._on_capture_error(app.session.job.id, app.recorder.last_error)
    assert app.pending_audio == b''  # GUI has not applied the queued result.
    drain(app)
    assert app.pending_audio == b'partial-recording'
    assert app.session.state == State.ERROR


def test_retry_is_review_only_and_uses_retained_audio(tmp_path):
    app, _ = make_app(tmp_path)
    app.session.state = State.ERROR
    app.pending_audio = b''
    app.retry_last_audio()
    drain(app)
    assert app.last_text == 'Complete text'
    assert app.pending_audio == b'retained-frames'
    app.injector.inject_text.assert_not_called()


def test_new_recording_cannot_overwrite_unprocessed_audio(tmp_path):
    app, _ = make_app(tmp_path)
    app.session.state = State.ERROR
    app.show_last_result = Mock()
    app.start_recording()
    app.show_last_result.assert_called_once()
    app.recorder.start_recording.assert_not_called()


def test_stale_provider_event_cannot_overwrite_new_session(tmp_path):
    app, _ = make_app(tmp_path)
    old = JobEvent(app.session.job.id, app.session.job.attempt, 'error', 'old error')
    app.session.cancel()
    app.session.begin(app.config.data)
    app._on_work_event(old)
    assert app.last_error == '' and app.session.state == State.RECORDING


def test_cancel_then_late_result_cannot_paste(tmp_path):
    app, _ = make_app(tmp_path)
    app._process_audio_worker(app.pending_audio)
    app.cancel_processing()
    drain(app)
    app.injector.inject_text.assert_not_called()
    assert app.pending_audio and 'CANCELLED' in app.last_error


def test_interrupted_capture_does_not_call_api(tmp_path):
    app, service = make_app(tmp_path)
    app.recorder.is_recording = True
    app.session.state = State.RECORDING
    app.recorder.last_error = '[CAPTURE_READ_ERROR] Interrupted'
    app.recorder.stop_recording.return_value = b'partial'
    app.stop_recording_and_process()
    drain(app)
    service.transcribe_and_format.assert_not_called()
    assert app.pending_audio == b'partial'


def test_modal_window_blocks_new_capture(tmp_path):
    app, _ = make_app(tmp_path)
    app.session.state = State.READY
    app.pending_audio = b''
    app.q_app.activeModalWidget.return_value = object()
    app.start_recording()
    app.recorder.start_recording.assert_not_called()


@pytest.mark.parametrize('commit_success', [False, True])
def test_audio_save_releases_raw_only_after_success(tmp_path, monkeypatch, commit_success):
    app, _ = make_app(tmp_path)
    app.session.state = State.ERROR
    monkeypatch.setattr('katip.app.QFileDialog.getSaveFileName', lambda *a: (str(tmp_path / 'audio.wav'), ''))
    file = Mock()
    file.open.return_value = True
    file.write.return_value = len(b'original-raw-wav')
    file.commit.return_value = commit_success
    monkeypatch.setattr('katip.app.QSaveFile', lambda _: file)
    app._save_last_audio()
    file.write.assert_called_once_with(b'original-raw-wav')
    assert bool(app.pending_audio) is not commit_success
    assert app.recorder.discard_audio.called is commit_success


def groq_result(formatted='Düzenlenmiş.', warning=''):
    return GroqResult('özgün ham metin', formatted, .2, warning=warning, mode='email', language='tr',
        custom_vocabulary=('Katip',), vocabulary_aliases=(('paysayd', 'PySide6'),),
        llm_model='qwen/qwen3.8-27b', stt_model='whisper-large-v3-turbo')


@pytest.mark.parametrize('current', [False, True])
def test_reformat_uses_original_context_without_stt_or_paste(tmp_path, current):
    app, _ = make_app(tmp_path)
    original = groq_result()
    app.session.state = State.READY
    app.last_groq_result = original
    app.last_text = original.text
    app.config.update({'mode': 'chat', 'custom_vocabulary': ['Yeni']})
    service = Mock()
    service.format_transcript.return_value = groq_result('Yeni metin')
    app._get_groq_service = Mock(return_value=service)
    app.reformat_last_text(current)
    assert app.last_groq_result is original
    drain(app)
    assert app.last_text == 'Yeni metin'
    call = service.format_transcript.call_args
    assert call.args == (original.raw_transcript,)
    assert call.kwargs['mode'] == ('chat' if current else 'email')
    assert call.kwargs['custom_vocabulary'] == (['Yeni'] if current else ['Katip'])
    app.injector.inject_text.assert_not_called()
    service.transcribe_and_format.assert_not_called()


@pytest.mark.parametrize('provider', ['openai', 'claude', 'codex', 'agy'])
def test_reformat_keeps_originating_provider(tmp_path, provider):
    from dataclasses import replace
    app, _ = make_app(tmp_path)
    app.last_groq_result = replace(groq_result(), provider=provider)
    app.session.state = State.READY
    service = Mock()
    service.format_transcript.return_value = replace(groq_result('Yeni'), provider=provider)
    app._service = Mock(return_value=service)
    app.reformat_last_text()
    drain(app)
    app._service.assert_called_once_with(provider)
    assert app.last_groq_result.provider == provider
    assert app.last_text == 'Yeni'


def test_reformat_failure_preserves_previous_pair(tmp_path):
    app, _ = make_app(tmp_path)
    original = groq_result()
    app.last_groq_result = original
    app.last_text = original.text
    app._on_reformat_done(original, groq_result(None, 'Failed'))
    assert app.last_groq_result is original and app.last_text == original.text


def test_target_change_prevents_delivery(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    monkeypatch.setattr('katip.platform.target.target_unchanged', lambda _: False)
    app._process_audio_worker(app.pending_audio)
    drain(app)
    app.injector.inject_text.assert_not_called()
    assert app.session.state == State.READY
    assert app.last_text and app.pending_audio and 'değiştiği' in app.last_error


def test_result_dialog_exposes_text_and_diagnostics(tmp_path):
    from PySide6.QtWidgets import QApplication, QTextEdit, QPushButton
    qapp = QApplication.instance() or QApplication([])
    app, _ = make_app(tmp_path)
    app.last_groq_result = groq_result()
    app.last_text = app.last_groq_result.text
    dialog = app._build_result_dialog()
    assert dialog.findChild(QTextEdit, 'rawTranscript').toPlainText() == 'özgün ham metin'
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    assert buttons['Metni Yeniden Düzenle'].isEnabled()
    buttons['Gösterilen Metni Kopyala'].click()
    app.injector.set_clipboard.assert_called_once_with('Düzenlenmiş.')
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_target_change_during_clipboard_sync_prevents_paste(tmp_path, monkeypatch):
    from katip.injector import BaseInjector
    class Clipboard(BaseInjector):
        last_error = ''
        def get_current_clipboard(self): return None
        def set_clipboard(self, value): return True
        def simulate_paste(self): raise AssertionError('Changed target must not receive input')
    app, _ = make_app(tmp_path)
    app.injector = Clipboard()
    monkeypatch.setattr('katip.injector.time.sleep', lambda _: None)
    monkeypatch.setattr('katip.platform.target.target_unchanged', Mock(side_effect=[True, True, False]))
    app._process_audio_worker(app.pending_audio)
    drain(app)
    # The text was already on the clipboard; the user is told to paste it themselves.
    assert not app.pending_audio and app.session.state == State.READY
    assert 'değiştiği' in app.last_error and 'panoya kopyalandı' in app.last_error


def test_failure_log_names_the_stage_that_was_running(tmp_path):
    from katip.domain.errors import ProviderError
    app, service = make_app(tmp_path)
    service.transcribe_and_format.side_effect = ProviderError('NETWORK_TIMEOUT', 'stt', 'timeout')
    app._process_audio_worker(app.pending_audio)
    drain(app)
    failure = app.diagnostics.snapshot()[-1]
    assert failure['event'] == 'failed'
    assert failure['stage'] == 'transcribing' and failure['code'] == 'NETWORK_TIMEOUT'


def test_clean_exit_is_recorded_once_for_tray_quit_and_logout(tmp_path):
    app, _ = make_app(tmp_path)
    app.app_diagnostics = Diagnostics()
    app._app_stopped = False
    app._record_app_stopped()
    app._record_app_stopped()
    assert [event['event'] for event in app.app_diagnostics.snapshot()] == ['app_stopped']


def test_failed_paste_copies_to_clipboard_and_frees_next_dictation(tmp_path):
    app, _ = make_app(tmp_path)
    app.session.job.target = None
    app.injector.restore_clipboard = False
    app.injector.inject_text.return_value = False
    app.injector.last_error = 'Otomatik yapıştırma başarısız.'
    app.injector.set_clipboard.return_value = True
    app._process_audio_worker(app.pending_audio)
    drain(app)
    app.injector.set_clipboard.assert_called_once_with('Complete text')
    assert app.session.state == State.READY and not app.pending_audio
    assert 'panoya kopyalandı' in app.last_error and app.last_text == 'Complete text'
    assert app.diagnostics.snapshot()[-1]['code'] == 'COPIED'


def test_failed_clipboard_copy_keeps_audio_for_manual_recovery(tmp_path):
    app, _ = make_app(tmp_path)
    app.injector.restore_clipboard = False
    app.injector.inject_text.return_value = False
    app.injector.set_clipboard.return_value = False
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert app.session.state == State.READY and app.pending_audio
    assert 'Son Sonuç' in app.last_error


def test_restore_warning_after_sent_input_is_not_a_failure(tmp_path):
    app, _ = make_app(tmp_path)
    app.injector.last_warning = 'Girdi gönderildi ancak önceki pano geri yüklenemedi.'
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert app.session.state == State.COMPLETED
    app.pill.show_success.assert_called_once()
    assert 'geri yüklenemedi' in app.tray.showMessage.call_args.args[1]


def test_defect_in_gui_commit_returns_to_a_recoverable_state(tmp_path):
    app, _ = make_app(tmp_path)
    app.recorder.discard_audio.side_effect = KeyError('PRIVATE')
    app._process_audio_worker(app.pending_audio)
    drain(app)
    assert app.session.state == State.ERROR and not app.is_busy_processing
    assert app.pending_audio and 'UNEXPECTED_ERROR' in app.last_error
    failure = app.diagnostics.snapshot()[-1]
    assert failure['event'] == 'unhandled_exception' and failure['exception_type'] == 'KeyError'
    assert 'PRIVATE' not in str(app.diagnostics.snapshot())
