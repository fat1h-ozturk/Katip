"""
Main Application Coordinator for Katip.
Connects Audio, AI Services, Text Injector, System Tray, Floating Pill, and Hotkeys.
"""

import os
import json
import threading
from ctypes.util import find_library
from typing import Optional
from PySide6.QtCore import QIODevice, QObject, QSaveFile, Signal, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                              QPushButton, QSystemTrayIcon, QTabWidget, QTextEdit, QVBoxLayout)

from .audio import AudioRecorder
from .config import ConfigManager, DEFAULT_GEMINI_MODEL
from .hotkey import HotkeyManager
from .injector import TextInjector
from .services.gemini import GeminiService
from .services.groq import GroqResult, GroqService
from .services.openai import OpenAIService
from .services.claude import ClaudeService
from .services.codex import CodexService
from .sound import SoundPlayer
from .ui.overlay_controller import LayerOverlayController
from .ui.pill import FloatingPill
from .ui.settings import SettingsDialog
from .ui.tray import TrayIcon

class WorkerSignals(QObject):
    """Thread-safe signals for background transcription, injection, and IPC events."""
    level_changed = Signal(float)
    processing_done = Signal(str, float)
    processing_error = Signal(str)
    processing_ready = Signal(str)
    reformat_done = Signal(object, object)
    capture_error = Signal(str)
    toggle_received = Signal()
    start_received = Signal()
    stop_received = Signal()
    notify_received = Signal()
    settings_received = Signal()

class KatipApp:
    """The central Katip application."""

    def __init__(self, q_app: QApplication):
        self.q_app = q_app
        self.config = ConfigManager()
        self.is_busy_processing = False
        self.pending_audio = b""
        self.last_text = ""
        self.last_groq_result: Optional[GroqResult] = None
        self.last_error = ""
        self._processing_thread = None

        # Thread-safe Qt signal bridge
        self.signals = WorkerSignals()
        self.signals.level_changed.connect(self._on_audio_level)
        self.signals.processing_done.connect(self._on_processing_success)
        self.signals.processing_error.connect(self._on_processing_error)
        self.signals.processing_ready.connect(self._on_processing_ready)
        self.signals.reformat_done.connect(self._on_reformat_done)
        self.signals.capture_error.connect(self._on_capture_error)
        self.signals.toggle_received.connect(self.toggle_recording)
        self.signals.start_received.connect(self.start_recording)
        self.signals.stop_received.connect(self.stop_recording_and_process)
        self.signals.notify_received.connect(self._on_notify_running)
        self.signals.settings_received.connect(self.open_settings)

        # Core Engines
        self.sound = SoundPlayer(enabled=self.config.get("sound_effects", True))
        self.injector = TextInjector(
            restore_clipboard=self.config.get("restore_clipboard", False),
            terminal_paste_mode=self.config.get("terminal_paste_mode", False)
        )
        self.recorder = AudioRecorder(
            on_level_callback=lambda lvl: self.signals.level_changed.emit(lvl),
            on_error_callback=lambda error: self.signals.capture_error.emit(error),
            device_index=self.config.get("input_device_index", -1),
            vad_mode=self.config.get("vad_mode", 2)
        )

        # UI Components: Use Wayland Layer Shell overlay (guarantees zero focus loss) if available
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" and find_library("gtk4-layer-shell"):
            self.pill = LayerOverlayController()
            self.pill.set_mode(self.config.get("mode", "dictation"))
        else:
            self.pill = FloatingPill()
            self.pill.clicked.connect(self.toggle_recording)
            self.pill.set_mode(self.config.get("mode", "dictation"))

        self.tray = TrayIcon()
        self.tray.set_active_mode(self.config.get("mode", "dictation"))
        self.tray.mode_changed.connect(self._on_mode_changed)
        self.tray.toggle_requested.connect(self.toggle_recording)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.quit_requested.connect(self.quit)
        self.tray.result_requested.connect(self.show_last_result)
        self.tray.show()

        self.settings_dialog: Optional[SettingsDialog] = None

        # Hotkey & IPC listener
        self.hotkey_mgr = HotkeyManager(
            hotkey_str=self.config.get("hotkey", "Ctrl+Alt+Space"),
            trigger_mode=self.config.get("trigger_mode", "toggle"),
            on_toggle=lambda: self.signals.toggle_received.emit(),
            on_press=lambda: self.signals.start_received.emit(),
            on_release=lambda: self.signals.stop_received.emit(),
            on_notify_running=lambda: self.signals.notify_received.emit(),
            on_open_settings=lambda: self.signals.settings_received.emit()
        )
        if not self.hotkey_mgr.start():
            self.recorder.terminate()
            self.pill.close()
            self.tray.hide()
            raise RuntimeError("Katip zaten çalışıyor veya uygulama iletişim kanalı açılamadı.")

        # Lazy-initialized AI service singletons (avoids re-creating per request)
        self._gemini_service: Optional[GeminiService] = None
        self._groq_service: Optional[GroqService] = None
        self._openai_service: Optional[OpenAIService] = None
        self._claude_service: Optional[ClaudeService] = None
        self._codex_service: Optional[CodexService] = None

        # Guide user: if API key is not configured yet, open Settings on first run
        if not self.config.get_api_key():
            QTimer.singleShot(400, self.open_settings)

    def _get_gemini_service(self) -> GeminiService:
        """Returns a cached GeminiService, recreating only if config changed."""
        api_key = self.config.get("gemini_api_key", "")
        model = self.config.get("gemini_model", DEFAULT_GEMINI_MODEL)
        if self._gemini_service is None or \
           self._gemini_service.api_key != api_key.strip() or \
           self._gemini_service.model != model:
            self._gemini_service = GeminiService(api_key=api_key, model=model)
        return self._gemini_service

    def _get_groq_service(self, stt_model: Optional[str] = None,
                          llm_model: Optional[str] = None) -> GroqService:
        """Returns a cached GroqService, recreating only if config changed."""
        api_key = self.config.get("groq_api_key", "")
        stt_model = stt_model or self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        llm_model = llm_model or self.config.get("groq_llm_model", "qwen/qwen3.8-27b")
        if self._groq_service is None or \
           self._groq_service.api_key != api_key.strip() or \
           self._groq_service.stt_model != stt_model or \
           self._groq_service.llm_model != llm_model:
            if self._groq_service is not None:
                self._groq_service._session.close()
            self._groq_service = GroqService(api_key=api_key, stt_model=stt_model, llm_model=llm_model)
        return self._groq_service

    def _get_openai_service(self) -> OpenAIService:
        api_key = self.config.get("openai_api_key", "")
        stt_model = self.config.get("openai_stt_model", "whisper-1")
        llm_model = self.config.get("openai_llm_model", "gpt-5-mini")
        if self._openai_service is None or \
           self._openai_service.api_key != api_key.strip() or \
           self._openai_service.stt_model != stt_model or \
           self._openai_service.llm_model != llm_model:
            if self._openai_service is not None:
                self._openai_service._session.close()
            self._openai_service = OpenAIService(api_key=api_key, stt_model=stt_model, llm_model=llm_model)
        return self._openai_service

    def _get_claude_service(self) -> ClaudeService:
        api_key = self.config.get("anthropic_api_key", "")
        llm_model = self.config.get("claude_llm_model", "claude-5-sonnet")
        
        groq_key = self.config.get("groq_api_key", "")
        openai_key = self.config.get("openai_api_key", "")
        
        if groq_key:
            stt_provider = "groq"
            stt_api_key = groq_key
            stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        elif openai_key:
            stt_provider = "openai"
            stt_api_key = openai_key
            stt_model = self.config.get("openai_stt_model", "whisper-1")
        else:
            stt_provider = ""
            stt_api_key = ""
            stt_model = ""

        if self._claude_service is None or \
           self._claude_service.api_key != api_key.strip() or \
           self._claude_service.llm_model != llm_model or \
           self._claude_service.stt_provider != stt_provider or \
           self._claude_service.stt_api_key != stt_api_key.strip():
            if self._claude_service is not None:
                self._claude_service._session.close()
            self._claude_service = ClaudeService(api_key=api_key, llm_model=llm_model,
                                                 stt_provider=stt_provider, stt_api_key=stt_api_key, stt_model=stt_model)
        return self._claude_service

    def _get_codex_service(self) -> CodexService:
        codex_model = self.config.get("codex_model", "")
        
        groq_key = self.config.get("groq_api_key", "")
        openai_key = self.config.get("openai_api_key", "")
        
        if groq_key:
            stt_provider = "groq"
            stt_api_key = groq_key
            stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        elif openai_key:
            stt_provider = "openai"
            stt_api_key = openai_key
            stt_model = self.config.get("openai_stt_model", "whisper-1")
        else:
            stt_provider = ""
            stt_api_key = ""
            stt_model = ""

        if self._codex_service is None or \
           self._codex_service.codex_model != codex_model or \
           self._codex_service.stt_provider != stt_provider or \
           self._codex_service.stt_api_key != stt_api_key.strip():
            self._codex_service = CodexService(codex_model=codex_model,
                                               stt_provider=stt_provider, stt_api_key=stt_api_key, stt_model=stt_model)
        return self._codex_service

    def start_recording(self) -> None:
        """Starts audio recording if not already recording or busy."""
        if self.is_busy_processing or self.recorder.is_recording:
            return
        if self.pending_audio or self.recorder.has_pending_audio:
            self._notify_recovery("Önceki kayıt korunuyor. Son Sonuç menüsünden yeniden işleyin veya kaydedin.")
            # Surface the recovery actions even when OS tray notifications are disabled.
            self.show_last_result()
            return
        if self.q_app.activeModalWidget() is not None:
            return
        if self.settings_dialog and self.settings_dialog.isVisible():
            self._notify_recovery("Dikteyi başlatmadan önce ayarlar penceresini kapatın.")
            return
        try:
            self.recorder.start_recording()
        except RuntimeError as error:
            self._on_processing_error(str(error))
            return
        # ASVS 14.2.7: keep only the current recording's in-memory result.
        self.last_text = ""
        self.last_groq_result = None
        self.last_error = ""
        current_mode = self.config.get("mode", "dictation")
        print(f"[App] Kayıt başladı (Mod: {current_mode})")
        self.sound.play("start")
        self.pill.show_recording(mode=current_mode)
        self.tray.set_recording(True)

    def stop_recording_and_process(self) -> None:
        """Stops audio recording and sends audio to AI pipeline."""
        if not self.recorder.is_recording:
            return
        print("[App] Kayıt durduruldu, ses işleniyor...")
        self.sound.play("stop")
        self.pill.show_processing()
        self.tray.set_recording(False)
        self.is_busy_processing = True
        try:
            audio_bytes = self.recorder.stop_recording()
        except RuntimeError as error:
            self._on_processing_error(str(error))
            return
        if self.recorder.last_error:
            self.pending_audio = audio_bytes
            self._on_processing_error(self.recorder.last_error)
            return

        if not audio_bytes or len(audio_bytes) < 3200:  # < 0.1s
            print("[App] Çok kısa ses veya ses algılanamadı.")
            self.is_busy_processing = False
            self.sound.play("error")
            self.pill.show_error("Ses algılanamadı.")
            return

        self._start_processing(audio_bytes)

    def _start_processing(self, audio_bytes: bytes, auto_paste: bool = True) -> None:
        self.pending_audio = audio_bytes
        if auto_paste:
            self.last_text = ""
            self.last_groq_result = None
        self.last_error = ""
        self.is_busy_processing = True
        self.pill.show_processing()
        self._processing_thread = threading.Thread(target=self._process_audio_worker,
                                                  args=(audio_bytes, auto_paste), daemon=True)
        self._processing_thread.start()

    def toggle_recording(self) -> None:
        """Toggles between starting audio capture and sending to AI."""
        if self.is_busy_processing:
            print("[App] Henüz önceki işlem devam ediyor, bekleniyor...")
            return

        if not self.recorder.is_recording:
            self.start_recording()
        else:
            self.stop_recording_and_process()

    def _process_audio_worker(self, audio_bytes: bytes, auto_paste: bool = True) -> None:
        """Runs in background thread to query AI and inject text."""
        provider = self.config.get("provider", "gemini")
        mode = self.config.get("mode", "dictation")
        custom_vocab = self.config.get("custom_vocabulary", [])

        try:
            print(f"[App] {provider.upper()} API isteği gönderiliyor ({len(audio_bytes)} bayt)...")
            if provider == "gemini":
                service = self._get_gemini_service()
                text, latency = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab
                )
                warning = service.last_warning
                result = None
            elif provider == "openai":
                lang = self.config.get("language", "tr")
                service = self._get_openai_service()
                result = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab, language=lang,
                    vocabulary_aliases=self.config.get("vocabulary_aliases", {}),
                )
                text, latency, warning = result.text, result.latency, result.warning
            elif provider == "claude":
                lang = self.config.get("language", "tr")
                service = self._get_claude_service()
                result = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab, language=lang,
                    vocabulary_aliases=self.config.get("vocabulary_aliases", {}),
                )
                text, latency, warning = result.text, result.latency, result.warning
            elif provider == "codex":
                lang = self.config.get("language", "tr")
                service = self._get_codex_service()
                result = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab, language=lang,
                    vocabulary_aliases=self.config.get("vocabulary_aliases", {}),
                )
                text, latency, warning = result.text, result.latency, result.warning
            else:
                lang = self.config.get("language", "tr")
                service = self._get_groq_service()
                result = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab, language=lang,
                    vocabulary_aliases=self.config.get("vocabulary_aliases", {}),
                )
                text, latency, warning = result.text, result.latency, result.warning

            if not text.strip():
                print("[App] AI boş yanıt döndürdü.")
                self.signals.processing_error.emit("Boş yanıt veya ses anlaşılmadı.")
                return

            # Keep the result accessible even when clipboard or paste fails.
            # ASVS 15.4.1: one worker publishes a complete snapshot while UI reads are gated by busy.
            self.last_groq_result = result
            self.last_text = text
            if warning:
                self.signals.processing_error.emit(warning + " Son Sonuç menüsünden metni alın.")
                return
            if not auto_paste:
                self.signals.processing_ready.emit(text)
                return
            print(f"[App] Metin alındı ({latency}s).")

            # Inject text into active window
            success = self.injector.inject_text(text)
            if success:
                print("[App] Metin aktif pencereye başarıyla yapıştırıldı!")
            else:
                self.signals.processing_error.emit(self.injector.last_error or "Metin eklenemedi; Son Sonuç menüsünde korundu.")
                return

            self.signals.processing_done.emit(text, latency)

        except Exception as e:
            print(f"[App] Hata oluştu: {e}")
            self.signals.processing_error.emit(str(e))
        # Only the GUI completion handler releases busy state (ASVS 15.4.1).

    def _on_audio_level(self, level: float) -> None:
        if self.recorder.is_recording:
            self.pill.set_audio_level(level)

    def _on_processing_success(self, text: str, latency: float) -> None:
        self.is_busy_processing = False
        self.pending_audio = b""
        self.last_error = ""
        self.sound.play("success")
        self.pill.show_success(latency=latency)

    def _on_processing_error(self, error_message: str) -> None:
        self.is_busy_processing = False
        self.last_error = error_message
        self.tray.set_recording(False)
        self.sound.play("error")
        self.pill.show_error(error_message)
        self._notify_recovery(error_message)

    def _on_capture_error(self, error_message: str) -> None:
        # A queued device error may arrive after stop has already drained the frames.
        if self.is_busy_processing or self.pending_audio:
            self._notify_recovery(error_message)
            return
        try:
            self.pending_audio = self.recorder.stop_recording()
        except RuntimeError as error:
            error_message = str(error)
        self._on_processing_error(error_message)

    def _on_processing_ready(self, text: str) -> None:
        self.is_busy_processing = False
        self.last_text = text
        self.last_error = "Metin hazır. Son Sonuç menüsünden kopyalayabilirsiniz."
        self.pill.hide_pill()
        self.sound.play("success")
        self.tray.showMessage("Katip", self.last_error, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _notify_recovery(self, message: str) -> None:
        self.tray.showMessage("Katip", message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def retry_last_audio(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        if self.q_app.activeModalWidget() is not None:
            return
        try:
            if not self.pending_audio:
                self.pending_audio = self.recorder.stop_recording()
        except RuntimeError as error:
            self._on_processing_error(str(error))
            return
        if self.pending_audio:
            self._start_processing(self.pending_audio, auto_paste=False)

    def show_last_result(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            self._notify_recovery("Son sonucu açmadan önce kayıt ve işleme tamamlanmalıdır.")
            return
        if self.q_app.activeModalWidget() is not None:
            return
        self._build_result_dialog().exec()

    def _build_result_dialog(self) -> QDialog:
        """Build the existing recovery window without starting a nested event loop."""
        dialog = QDialog()
        dialog.setWindowTitle("Katip — Son Sonuç")
        dialog.resize(700, 480)
        layout = QVBoxLayout(dialog)
        label = QLabel(self.last_error or "Son kayıt yalnız uygulama açıkken bellekte tutulur.")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        result = self.last_groq_result
        tabs = QTabWidget()
        tabs.setObjectName("resultTabs")
        contents = [("Son Metin", self.last_text, "lastText")]
        if result is not None:
            contents = [
                ("Ham Metin", result.raw_transcript, "rawTranscript"),
                ("Düzenlenmiş Metin", result.formatted_text or "", "formattedTranscript"),
            ]
        for title, content, name in contents:
            text = QTextEdit()
            text.setObjectName(name)
            text.setReadOnly(True)
            text.setPlainText(content)
            text.setPlaceholderText("Henüz doğrulanmış düzenlenmiş metin yok.")
            tabs.addTab(text, title)
        if result is not None:
            details = QTextEdit()
            details.setObjectName("resultDetails")
            details.setReadOnly(True)
            changes = "\n".join(result.literal_changes) or "Belirgin literal farkı bulunmadı. Bu, anlamın korunduğunu kanıtlamaz."
            details.setPlainText(
                f"Mod: {result.mode}\nDil: {result.language}\n"
                f"STT: {result.stt_model}\nMetin modeli: {result.llm_model}\n\n"
                f"STT bağlamına sığmayan terim: {result.omitted_stt_terms}\n"
                f"Formatter bağlamına sığmayan ipucu: {result.omitted_formatter_terms}\n\n"
                "İnceleme bilgisi (öz düzeltme ve özetleme bu farkları açıklayabilir):\n"
                f"{changes}\n\nSegment bilgisi (kelime güveni veya doğruluk yüzdesi değildir):\n"
                + json.dumps(result.segments, ensure_ascii=False, indent=2)
            )
            tabs.addTab(details, "Ayrıntılar")
            tabs.setCurrentIndex(1 if result.formatted_text is not None else 0)
        layout.addWidget(tabs)
        copy_button = QPushButton("Gösterilen Metni Kopyala")
        copy_button.setEnabled(bool(tabs.currentWidget().toPlainText()))
        tabs.currentChanged.connect(lambda _: copy_button.setEnabled(bool(tabs.currentWidget().toPlainText())))
        copy_button.clicked.connect(lambda: self._copy_text(tabs.currentWidget().toPlainText()))
        layout.addWidget(copy_button)
        if result is not None:
            current_settings = QCheckBox("Güncel mod ve sözlüğü kullan")
            current_settings.setObjectName("useCurrentFormattingSettings")
            layout.addWidget(current_settings)
            reformat = QPushButton("Metni Yeniden Düzenle")
            reformat.setEnabled(bool(result.raw_transcript))
            reformat.clicked.connect(lambda: (dialog.accept(), self.reformat_last_text(current_settings.isChecked())))
            layout.addWidget(reformat)
        buttons = QHBoxLayout()
        for title, action, enabled in (
            ("Sesi Yeniden İşle", self.retry_last_audio, bool(self.pending_audio or self.recorder.has_pending_audio)),
            ("Sesi Kaydet", self._save_last_audio, bool(self.pending_audio or self.recorder.has_pending_audio)),
            ("Kaydı Temizle", self._discard_last_audio, bool(self.last_text or result or self.pending_audio or self.recorder.has_pending_audio)),
        ):
            button = QPushButton(title)
            button.setEnabled(enabled)
            button.clicked.connect(lambda checked=False, fn=action: (dialog.accept(), fn()))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return dialog

    def reformat_last_text(self, use_current_settings: bool = False) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        if self.q_app.activeModalWidget() is not None:
            return
        original = self.last_groq_result
        if original is None or not original.raw_transcript:
            return
        mode = self.config.get("mode", "dictation") if use_current_settings else original.mode
        vocabulary = list(self.config.get("custom_vocabulary", [])) if use_current_settings else list(original.custom_vocabulary)
        aliases = dict(self.config.get("vocabulary_aliases", {})) if use_current_settings else dict(original.vocabulary_aliases)
        # Keep the original models even if settings were changed after this recording.
        service = self._get_groq_service(stt_model=original.stt_model, llm_model=original.llm_model)
        self.is_busy_processing = True
        self.last_error = ""
        self.pill.show_processing()
        self._processing_thread = threading.Thread(
            target=self._reformat_text_worker,
            args=(original, service, mode, vocabulary, aliases), daemon=True,
        )
        self._processing_thread.start()

    def _reformat_text_worker(self, original: GroqResult, service: GroqService,
                              mode: str, vocabulary: list, aliases: dict) -> None:
        try:
            candidate = service.format_transcript(
                original.raw_transcript, mode=mode, custom_vocabulary=vocabulary,
                language=original.language, vocabulary_aliases=aliases,
                segments=original.segments, omitted_stt_terms=original.omitted_stt_terms,
            )
            self.signals.reformat_done.emit(original, candidate)
        except Exception:
            # ASVS 16.5.1: don't publish request bodies or credentials in unexpected errors.
            self.signals.processing_error.emit("Metin yeniden düzenlenemedi; önceki sonuç korundu.")

    def _on_reformat_done(self, original: GroqResult, candidate: GroqResult) -> None:
        # ASVS 15.4.1: commit a complete candidate only on the GUI thread, for the same record.
        if self.last_groq_result is not original:
            return
        if candidate.warning or candidate.formatted_text is None:
            self._on_processing_error(candidate.warning or "Metin düzenlenemedi; önceki sonuç korundu.")
            return
        self.last_groq_result = candidate
        self._on_processing_ready(candidate.text)

    def _copy_last_text(self) -> None:
        self._copy_text(self.last_text)

    def _copy_text(self, text: str) -> None:
        if not self.injector.set_clipboard(text):
            self._notify_recovery("Metin panoya kopyalanamadı; Son Sonuç menüsünde korunuyor.")

    def _save_last_audio(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        try:
            if not self.pending_audio:
                self.pending_audio = self.recorder.stop_recording()
            path, _ = QFileDialog.getSaveFileName(None, "Ses Kaydını Kaydet", "katip-kayit.wav", "WAV (*.wav)")
            if path and self.pending_audio:
                file = QSaveFile(path)
                if not file.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise RuntimeError("Dosya açılamadı.")
                if file.write(self.pending_audio) != len(self.pending_audio) or not file.commit():
                    raise RuntimeError("Ses kaydı dosyaya yazılamadı.")
                self.pending_audio = b""
                self.last_error = ""
        except RuntimeError as error:
            self._notify_recovery(str(error))

    def _discard_last_audio(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        try:
            self.recorder.stop_recording()
        except RuntimeError as error:
            self._notify_recovery(str(error))
            return
        self.pending_audio = b""
        self.last_error = ""
        self.last_text = ""
        self.last_groq_result = None

    def _on_mode_changed(self, new_mode: str) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            self.tray.set_active_mode(self.config.get("mode", "dictation"))
            return
        try:
            self.config.set("mode", new_mode)
        except RuntimeError as error:
            self.tray.set_active_mode(self.config.get("mode", "dictation"))
            self._notify_recovery(str(error))
            return
        self.pill.set_mode(new_mode)

    def _on_notify_running(self) -> None:
        hotkey = self.config.get("hotkey", "Ctrl+Alt+Space")
        self.tray.showMessage(
            "Katip",
            f"Uygulama zaten arka planda çalışıyor.\n🎙️ Dikte Kısayolu: {hotkey}",
            QSystemTrayIcon.MessageIcon.Information,
            3500
        )
        self.open_settings()

    def open_settings(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            self._notify_recovery("Ayarları açmadan önce kayıt ve işleme tamamlanmalıdır.")
            return
        if not self.settings_dialog:
            self.settings_dialog = SettingsDialog(self.config, can_edit=self._can_edit_settings)
            self.settings_dialog.config_updated.connect(self._on_config_updated)
        elif not self.settings_dialog.isVisible():
            self.settings_dialog._load_values()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _on_config_updated(self) -> None:
        if not self._can_edit_settings():
            return
        self.sound.enabled = self.config.get("sound_effects", True)
        self.injector.restore_clipboard = self.config.get("restore_clipboard", False)
        
        # Re-initialize injector if terminal paste mode changed
        new_term_mode = self.config.get("terminal_paste_mode", False)
        if getattr(self.injector._backend, "terminal_paste", False) != new_term_mode:
            self.injector = TextInjector(
                restore_clipboard=self.config.get("restore_clipboard", False),
                terminal_paste_mode=new_term_mode
            )

        # Update audio input device if changed
        new_dev_idx = self.config.get("input_device_index", -1)
        new_vad_mode = self.config.get("vad_mode", 2)
        if getattr(self.recorder, "device_index", -1) != new_dev_idx or getattr(self.recorder, "vad_mode", 2) != new_vad_mode:
            self.recorder.terminate()
            self.recorder = AudioRecorder(
                on_level_callback=lambda lvl: self.signals.level_changed.emit(lvl),
                on_error_callback=lambda error: self.signals.capture_error.emit(error),
                device_index=new_dev_idx,
                vad_mode=self.config.get("vad_mode", 2)
            )
        # Invalidate cached services so they pick up new config on next use
        for service in (self._gemini_service, self._groq_service):
            if service is not None:
                service._session.close()
        self._gemini_service = None
        self._groq_service = None
        # Refresh hotkey manager
        self.hotkey_mgr.stop()
        self.hotkey_mgr = HotkeyManager(
            hotkey_str=self.config.get("hotkey", "Ctrl+Alt+Space"),
            trigger_mode=self.config.get("trigger_mode", "toggle"),
            on_toggle=lambda: self.signals.toggle_received.emit(),
            on_press=lambda: self.signals.start_received.emit(),
            on_release=lambda: self.signals.stop_received.emit(),
            on_notify_running=lambda: self.signals.notify_received.emit(),
            on_open_settings=lambda: self.signals.settings_received.emit()
        )
        if not self.hotkey_mgr.start():
            self._notify_recovery("Kısayol iletişimi başlatılamadı. Katip'i yeniden açın.")

    def _can_edit_settings(self) -> bool:
        return not (self.is_busy_processing or self.recorder.is_recording or self.recorder.has_pending_audio)

    def quit(self) -> None:
        if self.is_busy_processing:
            self._notify_recovery("Çıkmadan önce işleme tamamlanmalıdır.")
            return
        if self.recorder.is_recording:
            try:
                self.pending_audio = self.recorder.stop_recording()
            except RuntimeError as error:
                self._on_processing_error(str(error))
                return
            self.tray.set_recording(False)
        if self.pending_audio or self.recorder.has_pending_audio:
            self._notify_recovery("Çıkmadan önce Son Sonuç menüsünden kaydı kaydedin veya temizleyin.")
            self.show_last_result()
            return
        self.hotkey_mgr.stop()
        if hasattr(self.pill, "close"):
            self.pill.close()
        self.recorder.terminate()
        for service in (self._gemini_service, self._groq_service):
            if service is not None:
                service._session.close()
        self.last_text = ""
        self.last_groq_result = None
        self.q_app.quit()
