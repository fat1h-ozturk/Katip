import threading
from unittest.mock import MagicMock, patch

import pytest

from katip.audio import AudioRecorder, no_alsa_err


def test_linux_audio_context_preserves_error_and_restores_handler():
    library = MagicMock()
    with patch("katip.audio.sys.platform", "linux"), patch(
        "katip.audio.ctypes.cdll.LoadLibrary", return_value=library
    ):
        with pytest.raises(OSError, match="device failed"):
            with no_alsa_err():
                raise OSError("device failed")
    assert library.snd_lib_error_set_handler.call_count == 2
    library.snd_lib_error_set_handler.assert_called_with(None)


def test_failed_capture_notifies_and_retains_audio():
    stream = MagicMock()
    chunk = b"\x00\x20" * 2048
    stream.read.side_effect = [chunk, OSError("disconnected")]
    errors = []
    with patch("katip.audio.pyaudio.PyAudio") as pa:
        pa.return_value.open.return_value = stream
        recorder = AudioRecorder(on_error_callback=errors.append)
        recorder._vad = None
        recorder.start_recording()
        recorder._thread.join(1)
        assert not recorder.is_recording
        assert len(errors) == 1
        assert recorder.last_error == errors[0]
        assert recorder.stop_recording().startswith(b"RIFF")
        assert recorder.stop_recording() == b""
        entered, release = threading.Event(), threading.Event()

        def recovered_read(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            recorder._stop.set()
            return chunk

        stream.read.side_effect = recovered_read
        recorder.start_recording()
        try:
            assert entered.wait(1)
            assert recorder.last_error == ""
        finally:
            release.set()
            recorder._thread.join(1)
        recorder.stop_recording()
        recorder.terminate()
        assert stream.close.call_count == 2
        pa.return_value.terminate.assert_called_once()


def test_blocked_worker_cannot_restart_or_lose_frames():
    entered = threading.Event()
    release = threading.Event()
    chunk = b"\x00\x20" * 2048
    stream = MagicMock()

    def read(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return chunk

    stream.read.side_effect = read
    with patch("katip.audio.pyaudio.PyAudio") as pa:
        pa.return_value.open.return_value = stream
        recorder = AudioRecorder()
        recorder._vad = None
        recorder.start_recording()
        assert entered.wait(1)
        worker = recorder._thread
        real_join = worker.join
        try:
            with patch.object(worker, "join", side_effect=lambda timeout: real_join(0.01)):
                with pytest.raises(RuntimeError, match="korunuyor"):
                    recorder.stop_recording()
                assert recorder.has_pending_audio
                with pytest.raises(RuntimeError, match="henüz kapanmadı"):
                    recorder.start_recording()
            assert recorder._thread is worker
            assert pa.return_value.open.call_count == 1
        finally:
            release.set()
            worker.join(1)
        assert recorder.stop_recording().startswith(b"RIFF")
        assert not recorder.has_pending_audio
        recorder.terminate()


def test_terminate_leaves_blocked_stream_cleanup_to_worker():
    entered, release = threading.Event(), threading.Event()
    stream = MagicMock()

    def read(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return b"\x00\x00"

    stream.read.side_effect = read
    with patch("katip.audio.pyaudio.PyAudio") as pa:
        pa.return_value.open.return_value = stream
        recorder = AudioRecorder()
        recorder.start_recording()
        assert entered.wait(1)
        worker = recorder._thread
        real_join = worker.join
        try:
            with patch.object(worker, "join", side_effect=lambda timeout: real_join(0.01)):
                recorder.terminate()
            assert not recorder.is_recording
            stream.close.assert_not_called()
            pa.return_value.terminate.assert_not_called()
        finally:
            release.set()
            worker.join(1)
        stream.close.assert_called_once()
        pa.return_value.terminate.assert_called_once()


def test_open_failure_notifies_without_stuck_recording_state():
    errors = []
    with patch("katip.audio.pyaudio.PyAudio") as pa:
        pa.return_value.open.side_effect = OSError("no microphone")
        recorder = AudioRecorder(on_error_callback=errors.append)
        recorder.start_recording()
        recorder._thread.join(1)
        assert not recorder.is_recording
        assert len(errors) == 1
        assert recorder.stop_recording() == b""
        recorder.terminate()
