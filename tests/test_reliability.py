"""Regressions from U01 and the architecture audit, without real desktop actions."""
import io
import json
import struct
from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave

import pytest
import requests

from katip.application.session import SessionController, State, JobEvent
from katip.audio import AudioRecorder
from katip.config import ConfigManager
from katip.diagnostics import Diagnostics
from katip.injector import BaseInjector
from katip.services.groq import GroqService


@pytest.mark.parametrize('duration', [20, 24, 25, 26, 40, 60, 180, 300, 600])
def test_long_capture_has_no_25_second_cutoff(duration):
    # A deterministic device produces exactly the specified number of PCM samples.
    # The capture callback stops the device at the final sample, not on wall time.
    pcm = b'\0\x20' * 16000
    remaining = [duration]
    stream = Mock()
    recorder = AudioRecorder(vad_mode=0)
    recorder._vad = None
    def read(*_, **__):
        remaining[0] -= 1
        if remaining[0] == 0:
            recorder._stop.set()
        return pcm
    stream.read.side_effect = read
    with patch('katip.audio.pyaudio.PyAudio') as pa:
        pa.return_value.open.return_value = stream
        recorder.start_recording()
        recorder._thread.join(3)
        assert not recorder._thread.is_alive()
        # Export original samples; do not pay DSP cost for each fixture.
        raw = recorder.raw_wav()
        with wave.open(io.BytesIO(raw)) as wav:
            assert wav.getnframes() == duration * 16000
        if duration < 600:
            assert not recorder.last_error
        else:
            assert 'CAPTURE_LIMIT' in recorder.last_error
        stream.close.assert_called_once()
        recorder.terminate()


def test_vad_rejection_keeps_original_samples_exportable():
    recorder = AudioRecorder()
    recorder._frames = [b'\0\x20' * 16000]
    recorder._vad = Mock()
    recorder._vad.is_speech.return_value = False
    with pytest.raises(RuntimeError, match='VAD_REJECTED'):
        recorder.stop_recording()
    assert recorder.has_pending_audio
    with wave.open(io.BytesIO(recorder.raw_wav())) as wav:
        assert wav.readframes(16000) == b'\0\x20' * 16000
    assert recorder.retry_audio(filtered=False).startswith(b'RIFF')
    with pytest.raises(RuntimeError):
        recorder.start_recording()
    recorder.discard_audio()
    assert not recorder.has_pending_audio


def test_partial_final_frame_survives_vad_and_filtering():
    recorder = AudioRecorder()
    recorder._vad = Mock()
    recorder._vad.is_speech.return_value = True
    pcm = b'\0\x20' * 16001
    assert len(recorder._process_dsp(pcm)) == len(pcm)


@pytest.mark.parametrize('rate', [44100, 48000])
def test_resampling_preserves_one_second_duration(rate):
    recorder = AudioRecorder()
    # Independent duration oracle: one second at each input rate => 16000 output frames.
    pcm = struct.pack('<h', 1000) * rate
    output = recorder._resample_pcm(pcm, rate)
    assert len(output) == 32000


def test_stt_timeout_is_not_a_microphone_error():
    service = GroqService('fake')
    with patch.object(service._session, 'post', side_effect=requests.Timeout('SECRET')):
        with pytest.raises(RuntimeError, match='NETWORK_TIMEOUT') as error:
            service.transcribe_and_format(b'fake')
    assert 'SECRET' not in str(error.value)
    events = service.diagnostics.snapshot()
    assert events[0]['event'] == 'stt_started'
    assert events[-1]['code'] == 'NETWORK_TIMEOUT'


def test_diagnostic_clocks_and_unknown_private_fields():
    now = [0.0]
    diagnostics = Diagnostics(clock=lambda: now[0])
    diagnostics.event('recording_started', stage='capture', transcript='PRIVATE', api_key='SECRET')
    now[0] = 40
    diagnostics.event('stop_requested', source='ipc')
    diagnostics.event('stt_started', stage='stt')
    now[0] = 65
    diagnostics.event('failed', stage='stt', code='NETWORK_TIMEOUT')
    report = diagnostics.snapshot()
    assert [event['sequence'] for event in report] == [1, 2, 3, 4]
    assert report[-1]['elapsed_ms'] - report[2]['elapsed_ms'] == 25000
    assert 'SECRET' not in json.dumps(report) and 'PRIVATE' not in json.dumps(report)


def test_session_rejects_invalid_transition_and_stale_attempt():
    session = SessionController()
    with pytest.raises(RuntimeError):
        session.transition(State.DELIVERING)
    original_settings = {'provider': 'groq', 'custom_vocabulary': ['A']}
    job = session.begin(original_settings)
    original_settings['custom_vocabulary'].clear()
    assert job.settings['custom_vocabulary'] == ['A']
    session.transition(State.DRAINING)
    session.transition(State.TRANSCRIBING)
    session.cancel()
    old = JobEvent(job.id, job.attempt, 'processed')
    session.retry()
    assert job.cancelled.is_set()
    assert not session.accepts(old)
    assert session.accepts(JobEvent(session.job.id, session.job.attempt, 'processed'))


def test_pano_new_copy_wins_during_restore(monkeypatch):
    class Clipboard(BaseInjector):
        def __init__(self): super().__init__(True); self.value = 'A'
        def can_restore_clipboard(self): return True
        def clipboard_revision(self): return 1
        def get_current_clipboard(self): return self.value
        def set_clipboard(self, value): self.value = value; return True
        def simulate_paste(self): return True
    clipboard = Clipboard()
    monkeypatch.setattr('katip.injector.time.sleep', lambda seconds: setattr(clipboard, 'value', 'B') if seconds == .3 else None)
    assert clipboard.inject_text('Dikte')
    assert clipboard.value == 'B'


class FakeVault:
    def __init__(self): self.values = {}; self.fail = False
    def get(self, ref): return self.values.get(ref)
    def put(self, ref, value):
        if self.fail: raise RuntimeError('vault locked')
        self.values[ref] = value
    def delete(self, ref): self.values.pop(ref, None)


def test_vault_migration_and_failed_update_preserve_old_key(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'groq_api_key': 'old', 'provider': 'groq'}))
    vault = FakeVault()
    config = ConfigManager(path, secret_store=vault)
    config.save()
    assert 'old' not in path.read_text()
    assert ConfigManager(path, secret_store=vault).get('groq_api_key') == 'old'
    vault.fail = True
    with pytest.raises(RuntimeError):
        config.set('groq_api_key', 'new')
    assert ConfigManager(path, secret_store=vault).get('groq_api_key') == 'old'
    assert config.get('groq_api_key') == 'old'
    import os
    if os.name == 'posix':
        assert (tmp_path / 'config.previous.json').stat().st_mode & 0o777 == 0o600


def test_newer_config_schema_is_not_overwritten(tmp_path):
    path = tmp_path / 'config.json'
    original = json.dumps({'schema_version': 99, 'provider': 'groq'})
    path.write_text(original)
    config = ConfigManager(path)
    with pytest.raises(RuntimeError):
        config.set('mode', 'email')
    assert path.read_text() == original


@pytest.mark.parametrize('limit', [6400, 6402])
def test_byte_limit_never_keeps_a_partial_sample_and_reports_once(limit):
    recorder = AudioRecorder(on_error_callback=Mock())
    recorder.MAX_BYTES = limit
    stream = Mock()
    stream.read.return_value = b'\0\x20' * 1600
    with patch('katip.audio.pyaudio.PyAudio') as pa:
        pa.return_value.open.return_value = stream
        recorder.start_recording()
        recorder._thread.join(3)
        with wave.open(io.BytesIO(recorder.raw_wav())) as wav:
            assert wav.getnframes() * 2 == limit
        assert 'CAPTURE_LIMIT' in recorder.last_error
        recorder.on_error_callback.assert_called_once()
        recorder.terminate()


def test_device_failure_at_25_seconds_keeps_every_received_sample():
    recorder = AudioRecorder(on_error_callback=Mock())
    stream = Mock()
    stream.read.side_effect = [b'\0\x20' * 16000] * 25 + [OSError(-9996, 'PRIVATE DEVICE')]
    with patch('katip.audio.pyaudio.PyAudio') as pa:
        pa.return_value.open.return_value = stream
        recorder.start_recording()
        recorder._thread.join(3)
        with wave.open(io.BytesIO(recorder.raw_wav())) as wav:
            assert wav.getnframes() == 25 * 16000
        assert 'CAPTURE_DEVICE_LOST' in recorder.last_error
        recorder.on_error_callback.assert_called_once()
        events = recorder.diagnostics.snapshot()
        assert 'PRIVATE' not in json.dumps(events)
        # The log alone tells an incident report at which second capture stopped.
        assert events[1] == {**events[1], 'event': 'stream_opened', 'sample_rate': 16000}
        progress = [event['audio_bytes'] for event in events if event['event'] == 'capture_progress']
        assert progress == [5 * 32000 * n for n in range(1, 6)]
        failure = events[-1]
        assert failure['code'] == 'CAPTURE_DEVICE_LOST' and failure['errno'] == -9996
        assert failure['audio_bytes'] / (2 * failure['sample_rate']) == 25
        recorder.terminate()


def test_candidate_profile_does_not_import_legacy_production_keys(tmp_path, monkeypatch):
    legacy = tmp_path / 'talk-to-write'
    legacy.mkdir()
    (legacy / 'config.json').write_text('{"groq_api_key":"PRIVATE"}')
    monkeypatch.setenv('KATIP_PROFILE', 'reliability')
    config = ConfigManager(tmp_path / 'katip-reliability' / 'config.json')
    assert config.get('groq_api_key') != 'PRIVATE'


def test_session_deadline_and_terminal_state_guards():
    from katip.application.session import Job
    import time
    with pytest.raises(RuntimeError, match='DEADLINE'):
        Job({}, deadline=time.monotonic() - 1).check()
    session = SessionController()
    with pytest.raises(RuntimeError):
        session.retry()
    session.transition(State.SHUTTING_DOWN)
    with pytest.raises(RuntimeError):
        session.begin({})


def test_one_hundred_short_sessions_reject_previous_results():
    session = SessionController()
    previous = None
    for _ in range(100):
        job = session.begin({'provider': 'groq'})
        if previous:
            assert not session.accepts(previous)
        for state in (State.DRAINING, State.PREPROCESSING, State.TRANSCRIBING,
                      State.FORMATTING, State.DELIVERING, State.COMPLETED):
            session.transition(state)
        previous = JobEvent(job.id, job.attempt, 'processed', 'old text')
    assert session.state == State.COMPLETED and not session.busy


def test_cancel_during_clipboard_sync_prevents_paste(monkeypatch):
    from katip.application.session import Job
    job = Job({})
    class Clipboard(BaseInjector):
        def get_current_clipboard(self): return None
        def set_clipboard(self, value): return True
        def simulate_paste(self): raise AssertionError('Cancelled dictation must not paste')
    monkeypatch.setattr('katip.injector.time.sleep', lambda _: job.cancelled.set())
    with pytest.raises(RuntimeError, match='CANCELLED'):
        Clipboard().inject_text('Retained text', before_paste=job.check)


def test_diagnostic_disk_failure_keeps_in_memory_events(tmp_path, monkeypatch):
    from katip import diagnostics as module
    monkeypatch.setattr(module, 'RotatingFileHandler', Mock(side_effect=PermissionError('PRIVATE PATH')))
    logger = module.diagnostic_logger(tmp_path / 'unwritable')
    diagnostic = Diagnostics(logger=logger)
    diagnostic.event('failed', code='CAPTURE_READ_ERROR')
    assert diagnostic.snapshot()[0]['code'] == 'CAPTURE_READ_ERROR'


def test_diagnostic_loggers_reuse_one_bounded_handler(tmp_path):
    from katip.diagnostics import diagnostic_logger
    logger = diagnostic_logger(tmp_path)
    assert diagnostic_logger(tmp_path) is logger and len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert handler.maxBytes == 1024 * 1024 and handler.backupCount == 4
    handler.maxBytes = 150
    diagnostic = Diagnostics(logger=logger)
    for _ in range(30):
        diagnostic.event('failed', code='NETWORK_TIMEOUT', transcript='PRIVATE')
    paths = list(tmp_path.glob('diagnostics.jsonl*'))
    assert 1 < len(paths) <= 5
    assert all('PRIVATE' not in path.read_text() for path in paths)
    handler.close()
    logger.removeHandler(handler)


def test_diagnostic_records_carry_utc_wall_time():
    diagnostics = Diagnostics(clock=lambda: 0.0, wall_clock=lambda: 1793273366)
    assert diagnostics.event('app_started')['ts'] == '2026-10-29T11:29:26Z'


@pytest.mark.parametrize('previous, unclean', [
    (None, False), ('app_stopped', False), ('stt_started', True), ('capture_progress', True)])
def test_start_marks_a_previous_run_that_never_stopped(tmp_path, previous, unclean):
    from katip.diagnostics import LOG_NAME, record_app_start
    if previous:
        lines = ['not json', json.dumps({'event': 'recording_started'}), json.dumps({'event': previous}), '']
        (tmp_path / LOG_NAME).write_text('\n'.join(lines), encoding='utf-8')
    diagnostics = record_app_start(tmp_path, None, '9.9.9')
    events = diagnostics.snapshot()
    assert events[-1]['event'] == 'app_started' and events[-1]['version'] == '9.9.9'
    assert (events[0]['event'] == 'previous_run_unclean') is unclean
    if unclean:
        # The last stage written before the crash is the first thing to inspect.
        assert events[0]['code'] == 'PROCESS_EXIT_UNCLEAN' and events[0]['source'] == previous


def test_unreadable_or_contentless_log_is_not_an_unclean_exit(tmp_path):
    from katip.diagnostics import LOG_NAME, last_logged_event
    (tmp_path / LOG_NAME).write_text('[]\ngarbage\n', encoding='utf-8')
    assert last_logged_event(tmp_path) is None
    assert last_logged_event(tmp_path / 'missing') is None


def test_crash_reporting_logs_only_exception_types(tmp_path, monkeypatch):
    import sys
    import threading
    import faulthandler
    from katip import diagnostics as module
    enable = Mock()
    monkeypatch.setattr(faulthandler, 'enable', enable)
    monkeypatch.setattr(sys, 'excepthook', Mock())
    monkeypatch.setattr(threading, 'excepthook', Mock())
    (tmp_path / module.CRASH_LOG_NAME).write_text('x' * (module._CRASH_LOG_LIMIT + 1))
    diagnostics = Diagnostics()
    try:
        assert module.install_crash_reporting(tmp_path, diagnostics)
        assert enable.call_args.kwargs == {'file': module._crash_file, 'all_threads': True}
        sys.excepthook(ValueError, ValueError('PRIVATE TRANSCRIPT'), None)
        threading.excepthook(SimpleNamespace(exc_type=KeyError))
    finally:
        module._crash_file.close()
    # An oversized trace file is replaced instead of growing without bound.
    assert (tmp_path / module.CRASH_LOG_NAME).stat().st_size == 0
    events = diagnostics.snapshot()
    assert [event['exception_type'] for event in events] == ['ValueError', 'KeyError']
    assert 'PRIVATE' not in json.dumps(events)
    blocked = tmp_path / 'file'
    blocked.write_text('')
    assert not module.install_crash_reporting(blocked / 'sub', diagnostics)


def fake_portaudio(devices, stream=None, open_error=None):
    pa = Mock()
    pa.get_device_count.return_value = len(devices)
    def info(index):
        if index >= len(devices):
            raise OSError(-9996, 'Invalid device')
        return {'name': devices[index], 'maxInputChannels': 1, 'hostApi': 0}
    pa.get_device_info_by_index.side_effect = info
    if open_error:
        pa.open.side_effect = open_error
    else:
        pa.open.return_value = stream
    return pa


def one_second_stream(recorder, chunk=b'\0\x20' * 16000):
    stream = Mock()
    def read(*_, **__):
        recorder._stop.set()
        return chunk
    stream.read.side_effect = read
    return stream


@pytest.mark.parametrize('devices, expected, code', [
    (['Built-in', 'USB Headset'], 1, None),
    (['USB Headset', 'Built-in'], 0, 'DEVICE_MOVED'),
    (['Built-in'], None, 'DEVICE_NOT_FOUND'),
])
def test_saved_microphone_is_found_by_name_after_hot_plug(devices, expected, code):
    notices = []
    recorder = AudioRecorder(device_index=1, device_name='USB Headset', on_notice_callback=notices.append)
    recorder._vad = None
    stream = one_second_stream(recorder)
    with patch('katip.audio.pyaudio.PyAudio', return_value=fake_portaudio(devices, stream)) as pa:
        recorder.start_recording()
        recorder._thread.join(3)
        kwargs = pa.return_value.open.call_args.kwargs
        assert kwargs.get('input_device_index') == expected
        codes = [e.get('code') for e in recorder.diagnostics.snapshot() if e['event'] == 'device_resolved']
        assert codes == ([code] if code else [])
        assert bool(notices) is (code == 'DEVICE_NOT_FOUND')
        recorder.discard_audio()
        recorder.terminate()


def test_open_failure_reinitializes_portaudio_once_then_reports_clearly():
    errors = []
    recorder = AudioRecorder(on_error_callback=errors.append)
    stream = one_second_stream(recorder)
    stale = fake_portaudio(['Built-in'], open_error=OSError(-9996, 'PRIVATE'))
    fresh = fake_portaudio(['Built-in'], stream)
    with patch('katip.audio.pyaudio.PyAudio', side_effect=[stale, fresh]):
        recorder.start_recording()
        recorder._thread.join(3)
    assert not errors and stale.terminate.called and recorder.raw_wav()
    recorder.discard_audio()
    broken = fake_portaudio(['Built-in'], open_error=OSError(-9996, 'PRIVATE'))
    recorder = AudioRecorder(on_error_callback=errors.append)
    with patch('katip.audio.pyaudio.PyAudio', return_value=broken):
        recorder.start_recording()
        recorder._thread.join(3)
    assert len(errors) == 1 and errors[0].startswith('[CAPTURE_OPEN_FAILED]')
    assert 'kayıt korunuyor' not in errors[0] and 'PRIVATE' not in json.dumps(recorder.diagnostics.snapshot())
    assert broken.open.call_count == 6


def test_digital_silence_is_reported_as_a_microphone_problem_not_no_speech():
    recorder = AudioRecorder()
    stream = one_second_stream(recorder, chunk=b'\0\0' * 16000)
    with patch('katip.audio.pyaudio.PyAudio', return_value=fake_portaudio(['Built-in'], stream)):
        recorder.start_recording()
        recorder._thread.join(3)
        with pytest.raises(RuntimeError, match='CAPTURE_SILENT'):
            recorder.stop_recording()
        # The samples stay recoverable; the user may still save them.
        assert recorder.has_pending_audio and recorder.raw_wav()
        recorder.terminate()
