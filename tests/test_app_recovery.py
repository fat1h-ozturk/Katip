"""Coordinator regressions with no GUI, clipboard, microphone or API side effects."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from katip.app import KatipApp
from katip.config import ConfigManager
from katip.services.groq import GroqResult


def make_app(tmp_path):
    app = object.__new__(KatipApp)
    app.config = ConfigManager(tmp_path / "config.json")
    app.recorder = Mock(is_recording=False, has_pending_audio=False, last_error="")
    app.pending_audio = b"original-audio"
    app.last_text = ""
    app.last_groq_result = None
    app.last_error = ""
    app.is_busy_processing = True
    app.settings_dialog = None
    app.q_app = Mock()
    app.q_app.activeModalWidget.return_value = None
    app.signals = SimpleNamespace(processing_done=Mock(), processing_error=Mock(), processing_ready=Mock(), reformat_done=Mock())
    app.sound = Mock()
    app.pill = Mock()
    app.tray = Mock()
    app.injector = Mock(last_error="Paste failed")
    app.injector.inject_text.return_value = True
    service = Mock(last_warning="")
    service.transcribe_and_format.return_value = ("Complete text", 0.2)
    app._get_gemini_service = lambda: service
    return app, service


def test_failed_injection_never_reports_success_and_keeps_result(tmp_path):
    app, _ = make_app(tmp_path)
    app.injector.inject_text.return_value = False
    app._process_audio_worker(app.pending_audio)
    app.signals.processing_done.emit.assert_not_called()
    app.signals.processing_error.emit.assert_called_once_with("Paste failed")
    assert app.last_text == "Complete text"
    assert app.pending_audio == b"original-audio"
    assert app.is_busy_processing  # GUI callback owns the state transition.


def test_formatter_fallback_requires_review_before_injection(tmp_path):
    app, service = make_app(tmp_path)
    service.last_warning = "Raw transcript preserved"
    app._process_audio_worker(app.pending_audio)
    app.injector.inject_text.assert_not_called()
    app.signals.processing_error.emit.assert_called_once()
    assert app.last_text == "Complete text"
    assert app.pending_audio


def test_service_failure_keeps_audio_and_emits_error(tmp_path):
    app, service = make_app(tmp_path)
    service.transcribe_and_format.side_effect = RuntimeError("Incomplete response")
    app._process_audio_worker(app.pending_audio)
    app.signals.processing_error.emit.assert_called_once_with("Incomplete response")
    app.injector.inject_text.assert_not_called()
    assert app.pending_audio == b"original-audio"


def test_success_clears_audio_only_after_gui_completion(tmp_path):
    app, _ = make_app(tmp_path)
    app._process_audio_worker(app.pending_audio)
    assert app.pending_audio
    app.signals.processing_done.emit.assert_called_once_with("Complete text", 0.2)
    app._on_processing_success("Complete text", 0.2)
    assert not app.pending_audio
    assert not app.is_busy_processing


@pytest.mark.parametrize("state", ["is_recording", "has_pending_audio"])
def test_recording_settings_cannot_replace_recorder(tmp_path, state):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    setattr(app.recorder, state, True)
    original = app.recorder
    assert not app._can_edit_settings()
    app._on_config_updated()
    assert app.recorder is original
    original.terminate.assert_not_called()


def test_capture_error_preserves_frames_for_retry(tmp_path):
    app, _ = make_app(tmp_path)
    app.pending_audio = b""
    app.is_busy_processing = False
    app.recorder.stop_recording.return_value = b"captured-before-disconnect"
    app._on_capture_error("Microphone disconnected")
    assert app.pending_audio == b"captured-before-disconnect"
    assert app.last_error == "Microphone disconnected"
    assert not app.is_busy_processing
    app.tray.set_recording.assert_called_with(False)


def test_pending_capture_can_be_drained_on_explicit_retry(tmp_path):
    app, _ = make_app(tmp_path)
    app.pending_audio = b""
    app.is_busy_processing = False
    app.recorder.stop_recording.return_value = b"retained-frames"
    app._start_processing = Mock()
    app.retry_last_audio()
    app._start_processing.assert_called_once_with(b"retained-frames", auto_paste=False)


def test_new_recording_does_not_overwrite_unprocessed_audio(tmp_path):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    app.show_last_result = Mock()
    app.start_recording()
    app.show_last_result.assert_called_once()
    app.recorder.start_recording.assert_not_called()
    assert app.pending_audio == b"original-audio"


def test_formatter_error_followed_by_hotkey_opens_recovery(tmp_path):
    app, _ = make_app(tmp_path)
    app.config.set("provider", "groq")
    result = groq_result(None, "Seçili metin modeli bulunamadı (HTTP 404).")
    service = Mock()
    service.transcribe_and_format.return_value = result
    app._get_groq_service = Mock(return_value=service)
    app._process_audio_worker(app.pending_audio)
    app._on_processing_error(app.signals.processing_error.emit.call_args.args[0])
    app.show_last_result = Mock()
    app.toggle_recording()
    app.show_last_result.assert_called_once()
    assert not app.is_busy_processing
    assert app.last_groq_result is result
    assert app.pending_audio == b"original-audio"
    app.injector.inject_text.assert_not_called()
    app._discard_last_audio()
    app.toggle_recording()
    app.recorder.start_recording.assert_called_once()


def test_stale_capture_error_cannot_clear_active_processing(tmp_path):
    app, _ = make_app(tmp_path)
    app._on_capture_error("late device notification")
    app.recorder.stop_recording.assert_not_called()
    assert app.pending_audio == b"original-audio"
    assert app.is_busy_processing


def test_retried_result_is_reviewed_without_pasting_into_recovery_window(tmp_path):
    app, _ = make_app(tmp_path)
    app._process_audio_worker(app.pending_audio, auto_paste=False)
    app.injector.inject_text.assert_not_called()
    app.signals.processing_ready.emit.assert_called_once_with("Complete text")
    app._on_processing_ready("Complete text")
    assert not app.is_busy_processing
    assert app.pending_audio == b"original-audio"


def test_interrupted_capture_is_preserved_without_automatic_api_call(tmp_path):
    app, service = make_app(tmp_path)
    app.recorder.is_recording = True
    app.recorder.last_error = "Microphone disconnected"
    app.recorder.stop_recording.return_value = b"partial-recording"
    app._start_processing = Mock()
    app.stop_recording_and_process()
    app._start_processing.assert_not_called()
    service.transcribe_and_format.assert_not_called()
    assert app.pending_audio == b"partial-recording"
    assert not app.is_busy_processing


def test_hotkey_cannot_start_recording_in_modal_result_window(tmp_path):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    app.pending_audio = b""
    app.q_app.activeModalWidget.return_value = object()
    app.start_recording()
    app.recorder.start_recording.assert_not_called()


def test_retry_failure_preserves_previous_recovered_transcript(tmp_path, monkeypatch):
    import katip.app as app_module
    app, service = make_app(tmp_path)
    app.last_text = "Recovered complete transcript"
    service.transcribe_and_format.side_effect = RuntimeError("retry failed")
    monkeypatch.setattr(app_module.threading, "Thread", Mock())
    app._start_processing(app.pending_audio, auto_paste=False)
    app._process_audio_worker(app.pending_audio, auto_paste=False)
    assert app.last_text == "Recovered complete transcript"


@pytest.mark.parametrize("commit_success", [False, True])
def test_audio_save_releases_pending_only_after_success(tmp_path, monkeypatch, commit_success):
    import katip.app as app_module
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    monkeypatch.setattr(app_module.QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "audio.wav"), ""))
    file = Mock()
    file.open.return_value = True
    file.write.return_value = len(app.pending_audio)
    file.commit.return_value = commit_success
    monkeypatch.setattr(app_module, "QSaveFile", lambda path: file)
    app._save_last_audio()
    assert bool(app.pending_audio) is not commit_success


@pytest.mark.parametrize("recording", [False, True])
def test_recovery_actions_cannot_clear_an_active_job(tmp_path, recording):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = not recording
    app.recorder.is_recording = recording
    original = groq_result()
    app.last_groq_result = original
    app.last_text = original.text
    app._discard_last_audio()
    app._save_last_audio()
    assert app.last_groq_result is original
    assert app.last_text == original.text
    assert app.pending_audio == b"original-audio"
    app.recorder.stop_recording.assert_not_called()


def test_modal_result_or_save_window_blocks_reentrant_actions(tmp_path):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    app.q_app.activeModalWidget.return_value = object()
    app.last_groq_result = groq_result()
    app._build_result_dialog = Mock()
    app._start_processing = Mock()
    app._get_groq_service = Mock()
    app.show_last_result()
    app.retry_last_audio()
    app.reformat_last_text()
    app._build_result_dialog.assert_not_called()
    app._start_processing.assert_not_called()
    app._get_groq_service.assert_not_called()


def groq_result(formatted="Düzenlenmiş.", warning=""):
    return GroqResult("özgün ham metin", formatted, 0.2, warning=warning,
                      mode="email", language="tr", custom_vocabulary=("Katip",),
                      vocabulary_aliases=(("paysayd", "PySide6"),),
                      llm_model="qwen/qwen3.8-27b", stt_model="whisper-large-v3-turbo")


@pytest.mark.parametrize("warning", ["", "Ham metin korundu"])
def test_groq_snapshot_survives_formatter_or_paste_failure(tmp_path, warning):
    app, _ = make_app(tmp_path)
    app.config.set("provider", "groq")
    result = groq_result(None if warning else "Düzenlenmiş.", warning)
    service = Mock()
    service.transcribe_and_format.return_value = result
    app._get_groq_service = Mock(return_value=service)
    app.injector.inject_text.return_value = False
    app._process_audio_worker(app.pending_audio)
    assert app.last_groq_result is result
    assert app.last_text == result.text
    assert app.pending_audio == b"original-audio"
    if warning:
        app.injector.inject_text.assert_not_called()
    else:
        app.injector.inject_text.assert_called_once_with(result.text)


@pytest.mark.parametrize("use_current", [False, True])
def test_reformat_uses_original_raw_text_without_stt_or_paste(tmp_path, monkeypatch, use_current):
    import katip.app as app_module
    app, _ = make_app(tmp_path)
    original = groq_result()
    app.last_groq_result = original
    app.last_text = original.text
    app.pending_audio = b""
    app.is_busy_processing = False
    app.config.update({"mode": "chat", "custom_vocabulary": ["Yeni"],
                       "vocabulary_aliases": {"yeni": "Yeni"}, "groq_llm_model": "llama-3.3-70b-versatile"})
    candidate = groq_result("Yeni düzenleme.")
    service = Mock()
    service.format_transcript.return_value = candidate
    app._get_groq_service = Mock(return_value=service)

    def immediate_thread(*, target, args, daemon):
        return SimpleNamespace(start=lambda: target(*args))

    monkeypatch.setattr(app_module.threading, "Thread", immediate_thread)
    app.reformat_last_text(use_current)
    app._get_groq_service.assert_called_once_with(stt_model=original.stt_model, llm_model=original.llm_model)
    service.transcribe_and_format.assert_not_called()
    call = service.format_transcript.call_args
    assert call.args == (original.raw_transcript,)
    assert call.kwargs["mode"] == ("chat" if use_current else "email")
    assert call.kwargs["custom_vocabulary"] == (["Yeni"] if use_current else ["Katip"])
    assert call.kwargs["vocabulary_aliases"] == ({"yeni": "Yeni"} if use_current else {"paysayd": "PySide6"})
    assert app.last_groq_result is original  # Commit waits for GUI signal delivery.
    app.signals.reformat_done.emit.assert_called_once_with(original, candidate)
    app._on_reformat_done(original, candidate)
    assert app.last_groq_result is candidate
    assert app.last_text == "Yeni düzenleme."
    assert not app.is_busy_processing
    assert not app.pending_audio
    app.injector.inject_text.assert_not_called()


def test_reformat_failure_preserves_previous_pair(tmp_path):
    app, _ = make_app(tmp_path)
    original = groq_result()
    app.last_groq_result = original
    app.last_text = original.text
    app._on_reformat_done(original, groq_result(None, "Düzenleme başarısız"))
    assert app.last_groq_result is original
    assert app.last_text == original.text
    assert not app.is_busy_processing
    app.injector.inject_text.assert_not_called()


def test_stale_reformat_cannot_overwrite_another_record(tmp_path):
    app, _ = make_app(tmp_path)
    old, current = groq_result(), groq_result("Son kayıt")
    app.last_groq_result = current
    app.last_text = current.text
    app._on_reformat_done(old, groq_result("Eski yanıt"))
    assert app.last_groq_result is current
    assert app.last_text == current.text
    assert app.is_busy_processing


def test_reformat_busy_guard_and_clear_lifecycle(tmp_path):
    app, _ = make_app(tmp_path)
    app.last_groq_result = groq_result()
    app.last_text = app.last_groq_result.text
    app._get_groq_service = Mock()
    app.reformat_last_text()
    app._get_groq_service.assert_not_called()
    app.is_busy_processing = False
    app._discard_last_audio()
    assert not app.pending_audio
    assert not app.last_text
    assert app.last_groq_result is None


def test_new_recording_does_not_show_previous_transcript(tmp_path):
    app, _ = make_app(tmp_path)
    app.is_busy_processing = False
    app.pending_audio = b""
    app.last_groq_result = groq_result()
    app.last_text = app.last_groq_result.text
    app.start_recording()
    assert app.last_groq_result is None
    assert app.last_text == ""


def test_result_dialog_exposes_both_texts_and_optional_details(tmp_path, monkeypatch):
    import katip.app as app_module
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QTabWidget, QTextEdit
    qapp = QApplication.instance() or QApplication([])
    app, _ = make_app(tmp_path)
    app.last_groq_result = groq_result('"İşte: <think>alıntı</think>"')
    app.last_text = app.last_groq_result.text
    app.pending_audio = b""
    dialog = app._build_result_dialog()
    assert dialog.findChild(QTextEdit, "rawTranscript").toPlainText() == "özgün ham metin"
    assert dialog.findChild(QTextEdit, "formattedTranscript").toPlainText() == app.last_text
    assert not dialog.findChild(QCheckBox, "useCurrentFormattingSettings").isChecked()
    tabs = dialog.findChild(QTabWidget, "resultTabs")
    assert tabs.count() == 3
    tabs.setCurrentIndex(0)
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
    buttons["Gösterilen Metni Kopyala"].click()
    app.injector.set_clipboard.assert_called_once_with("özgün ham metin")
    assert buttons["Metni Yeniden Düzenle"].isEnabled()
    assert not buttons["Sesi Yeniden İşle"].isEnabled()
    app.q_app = qapp
    app.is_busy_processing = False
    app._get_groq_service = Mock()
    worker = Mock()
    monkeypatch.setattr(app_module.threading, "Thread", worker)
    QTimer.singleShot(0, buttons["Metni Yeniden Düzenle"].click)
    dialog.exec()
    worker.return_value.start.assert_called_once()  # accept() releases the modal guard first.
    dialog.deleteLater()
    qapp.processEvents()
