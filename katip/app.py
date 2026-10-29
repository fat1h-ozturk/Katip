"""
Main Application Coordinator for Katip.
Connects Audio, AI Services, Text Injector, System Tray, Floating Pill, and Hotkeys.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from PySide6.QtCore import QIODevice, QObject, QSaveFile, Signal, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                              QPushButton, QSystemTrayIcon, QTabWidget, QTextEdit, QVBoxLayout)

from .application.session import JobEvent, SessionController, State
from .domain.models import CAPABILITIES
from .domain.errors import ProviderError
from .diagnostics import Diagnostics, diagnostic_logger, install_crash_reporting, record_app_start
from .infrastructure.http_transport import execution_scope
from .audio import AudioRecorder
from .config import ConfigManager, DEFAULT_GEMINI_MODEL
from .hotkey import HotkeyManager
from .injector import TextInjector
from .services.gemini import GeminiService
from .services.groq import GroqResult, GroqService
from .services.openai import OpenAIService
from .services.claude import ClaudeService
from .services.codex import CodexService
from .services.antigravity import AntigravityService
from .sound import SoundPlayer
from .ui.overlay_controller import LayerOverlayController
from .ui.pill import FloatingPill
from .ui.settings import SettingsDialog
from .ui.styles import MINIMAL_DARK_STYLE
from .ui.tray import TrayIcon

class WorkerSignals(QObject):
    """Thread-safe signals for background transcription, injection, and IPC events."""
    trigger_received = Signal(str, str)
    hotkey_health = Signal(str)
    work_event = Signal(object)
    level_changed = Signal(float)
    processing_done = Signal(str, float)
    processing_error = Signal(str)
    processing_ready = Signal(str)
    reformat_done = Signal(object, object)
    capture_error = Signal(str, str)
    toggle_received = Signal()
    start_received = Signal()
    stop_received = Signal()
    notify_received = Signal()
    settings_received = Signal()
    update_available = Signal(str, str)

class KatipApp:
    """The central Katip application."""

    def __init__(self, q_app: QApplication, config=None):
        self.q_app = q_app
        from .config import CONFIG_FILE
        from .infrastructure.secrets import SecretStore
        self.config = config if config is not None else ConfigManager(secret_store=SecretStore(CONFIG_FILE))
        self.session = SessionController()
        from . import __version__
        log_directory = self.config.config_file.parent
        self.diagnostics = Diagnostics(logger=diagnostic_logger(log_directory))
        self.app_diagnostics = record_app_start(log_directory, self.diagnostics._logger, __version__)
        install_crash_reporting(log_directory, self.app_diagnostics)
        self._app_stopped = False
        # A desktop logout ends the event loop without the tray's quit action.
        q_app.aboutToQuit.connect(self._record_app_stopped)
        self._capture_job_id = None
        self._target = None
        self.pending_audio = b""
        self.last_text = ""
        self.last_groq_result: Optional[GroqResult] = None
        self.last_error = ""
        self._processing_thread = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="katip-job")

        # Thread-safe Qt signal bridge
        self.signals = WorkerSignals()
        self.signals.work_event.connect(self._on_work_event)
        self.signals.trigger_received.connect(self._handle_trigger)
        self.signals.hotkey_health.connect(self._on_hotkey_health)
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
        self.signals.update_available.connect(self._on_update_available)
        self.update_toast = None

        # Core Engines
        self.sound = SoundPlayer(enabled=self.config.get("sound_effects", True))
        self.injector = TextInjector(
            restore_clipboard=self.config.get("restore_clipboard", False),
            terminal_paste_mode=self.config.get("terminal_paste_mode", False)
        )
        self.recorder = AudioRecorder(
            on_level_callback=lambda lvl: self.signals.level_changed.emit(lvl),
            on_error_callback=lambda error: None,
            device_index=self.config.get("input_device_index", -1),
            vad_mode=self.config.get("vad_mode", 2)
        )

        # The Qt indicator is always available; optional layer-shell starts only
        # through its checked helper protocol and falls back to Qt.
        self.pill = LayerOverlayController(fallback=FloatingPill())
        self.pill.clicked.connect(self.toggle_recording)
        self.pill.set_mode(self.config.get("mode", "dictation"))

        self.tray = TrayIcon()
        self.tray.set_active_mode(self.config.get("mode", "dictation"))
        self.tray.mode_changed.connect(self._on_mode_changed)
        self.tray.toggle_requested.connect(lambda: self.toggle_recording("tray"))
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.quit_requested.connect(self.quit)
        self.tray.cancel_requested.connect(self.cancel_processing)
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
            on_open_settings=lambda: self.signals.settings_received.emit(),
            on_trigger=lambda kind, source: self.signals.trigger_received.emit(kind, source),
            on_status=lambda status: self.signals.hotkey_health.emit(status)
        )
        if not self.hotkey_mgr.start():
            self.recorder.terminate()
            self.pill.close()
            self.tray.hide()
            raise RuntimeError("Kâtip zaten çalışıyor veya uygulama iletişim kanalı açılamadı.")

        # Lazy-initialized AI service singletons (avoids re-creating per request)
        self._gemini_service: Optional[GeminiService] = None
        self._groq_service: Optional[GroqService] = None
        self._openai_service: Optional[OpenAIService] = None
        self._claude_service: Optional[ClaudeService] = None
        self._codex_service: Optional[CodexService] = None
        self._agy_service: Optional[AntigravityService] = None

        # Guide user: if API key is not configured yet, open Settings on first run
        if not self.config.get_api_key():
            QTimer.singleShot(400, self.open_settings)

        if self.config.secret_error:
            QTimer.singleShot(600, lambda: self._notify_recovery(self.config.secret_error))

        # Check for updates in background shortly after launch
        QTimer.singleShot(2500, self._check_for_updates)

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
        
        preferred_stt = self.config.get("stt_provider", "auto")
        if groq_key and preferred_stt != "openai":
            stt_provider = "groq"
            stt_api_key = groq_key
            stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        elif openai_key and preferred_stt != "groq":
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
           self._claude_service.stt_api_key != stt_api_key.strip() or \
           self._claude_service.stt_model != stt_model:
            if self._claude_service is not None:
                self._claude_service._session.close()
            self._claude_service = ClaudeService(api_key=api_key, llm_model=llm_model,
                                                 stt_provider=stt_provider, stt_api_key=stt_api_key, stt_model=stt_model)
        return self._claude_service

    def _get_codex_service(self) -> CodexService:
        codex_model = self.config.get("codex_model", "")
        
        groq_key = self.config.get("groq_api_key", "")
        openai_key = self.config.get("openai_api_key", "")
        
        preferred_stt = self.config.get("stt_provider", "auto")
        if groq_key and preferred_stt != "openai":
            stt_provider = "groq"
            stt_api_key = groq_key
            stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        elif openai_key and preferred_stt != "groq":
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
           self._codex_service.stt_api_key != stt_api_key.strip() or \
           self._codex_service.stt_model != stt_model:
            self._codex_service = CodexService(codex_model=codex_model,
                                               stt_provider=stt_provider, stt_api_key=stt_api_key, stt_model=stt_model)
        return self._codex_service

    def _get_agy_service(self) -> AntigravityService:
        agy_model = self.config.get("agy_model", "")
        
        groq_key = self.config.get("groq_api_key", "")
        openai_key = self.config.get("openai_api_key", "")
        
        preferred_stt = self.config.get("stt_provider", "auto")
        if groq_key and preferred_stt != "openai":
            stt_provider = "groq"
            stt_api_key = groq_key
            stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        elif openai_key and preferred_stt != "groq":
            stt_provider = "openai"
            stt_api_key = openai_key
            stt_model = self.config.get("openai_stt_model", "whisper-1")
        else:
            stt_provider = ""
            stt_api_key = ""
            stt_model = ""

        if self._agy_service is None or \
           self._agy_service.agy_model != agy_model or \
           self._agy_service.stt_provider != stt_provider or \
           self._agy_service.stt_api_key != stt_api_key.strip() or \
           self._agy_service.stt_model != stt_model:
            self._agy_service = AntigravityService(agy_model=agy_model,
                                               stt_provider=stt_provider, stt_api_key=stt_api_key, stt_model=stt_model)
        return self._agy_service

    @property
    def is_busy_processing(self):
        return self.session.busy

    def _emit(self, job, kind, value=None):
        self.signals.work_event.emit(JobEvent(job.id, job.attempt, kind, value))

    def _spawn(self, target, *args):
        self._processing_thread = self._pool.submit(target, *args)

    def _service(self, provider):
        return {"gemini": self._get_gemini_service, "groq": self._get_groq_service,
                "openai": self._get_openai_service, "claude": self._get_claude_service,
                "codex": self._get_codex_service, "agy": self._get_agy_service}[provider]()

    def start_recording(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording or self.recorder.is_capturing:
            return
        if self.pending_audio or self.recorder.has_pending_audio:
            self._notify_recovery("Önceki kayıt korunuyor. Son Sonuç menüsünden yeniden işleyin veya kaydedin.")
            self.show_last_result()
            return
        if self.q_app.activeModalWidget() is not None:
            return
        if self.settings_dialog and self.settings_dialog.isVisible():
            self._notify_recovery("Dikteyi başlatmadan önce ayarlar penceresini kapatın.")
            return
        desired_device = self.config.get("input_device_index", -1)
        desired_vad = self.config.get("vad_mode", 2)
        if self.recorder.device_index != desired_device or self.recorder.vad_mode != desired_vad:
            self.recorder.terminate()
            self.recorder = AudioRecorder(device_index=desired_device, vad_mode=desired_vad,
                on_level_callback=lambda level: self.signals.level_changed.emit(level))
        from .platform.target import capture_target
        self._target = capture_target()
        job = self.session.begin(self.config.data)
        job.target = self._target
        self.diagnostics = Diagnostics(logger=getattr(self.diagnostics, "_logger", None))
        self.diagnostics.job_id = job.id
        job.diagnostics = self.diagnostics
        self.diagnostics.event("recording_requested", stage="capture",
                               provider=str(job.settings.get("provider", "gemini")))
        job.service = self._service(job.settings.get("provider", "gemini"))
        self._capture_job_id = job.id
        self.recorder.diagnostics = self.diagnostics
        self.recorder.on_error_callback = lambda error, token=job.id: self.signals.capture_error.emit(token, error)
        try:
            self.recorder.start_recording()
        except RuntimeError as error:
            self._on_processing_error(str(error))
            return
        self.last_text = ""
        self.last_groq_result = None
        self.last_error = ""
        self.sound.play("start")
        self.pill.show_recording(mode=job.settings.get("mode", "dictation"))
        self.tray.set_recording(True)

    def stop_recording_and_process(self, source="hotkey") -> None:
        if not self.recorder.is_recording:
            return
        self.session.transition(State.DRAINING)
        self.diagnostics.event("stop_requested", stage="capture", source=source)
        self.sound.play("stop")
        self.pill.show_processing()
        self.tray.set_recording(False)
        self._spawn(self._drain_worker, self.session.job)

    def _drain_worker(self, job):
        try:
            self._emit(job, "phase", State.PREPROCESSING)
            audio = self.recorder.stop_recording()
            self._emit(job, "captured", (audio, self.recorder.last_error))
        except Exception as error:
            self._emit(job, "error", self._safe_error(error))

    @staticmethod
    def _safe_error(error):
        # Only our explicit safe errors may reach the desktop or log.
        from .domain.errors import ProviderError, ConfigurationError
        if isinstance(error, (ProviderError, ConfigurationError)):
            return str(error)
        return "[UNEXPECTED_ERROR] İşlem tamamlanamadı; alınan ses ve önceki sonuç korunuyor."

    def _start_processing(self, audio_bytes: bytes, auto_paste: bool = True) -> None:
        self.pending_audio = audio_bytes
        if not self.session.job:
            self.session.begin(self.config.data)
        job = self.session.job
        job.publish = lambda kind, value: self._emit(job, kind, value)
        job.diagnostics = self.diagnostics
        import time
        job.deadline = time.monotonic() + 180
        self.last_error = ""
        self.session.transition(State.TRANSCRIBING)
        self.pill.show_processing()
        service = job.service or self._service(job.settings.get("provider", "gemini"))
        job.service = service
        self._spawn(self._process_audio_worker, audio_bytes, auto_paste, job, service)

    def _on_hotkey_health(self, status):
        if status in ("ipc_only", "portal_denied"):
            self._notify_recovery("Genel kısayol kullanılamıyor. Sistem kısayollarına 'katip --toggle' komutunu atayabilirsiniz.")

    def _handle_trigger(self, kind, source):
        if kind == "toggle":
            self.toggle_recording(source)
        elif kind == "start":
            self.start_recording()
        elif kind == "stop":
            self.stop_recording_and_process(source)

    def toggle_recording(self, source="hotkey") -> None:
        if self.is_busy_processing:
            return
        if self.recorder.is_recording:
            self.stop_recording_and_process(source)
        else:
            self.start_recording()

    def _process_audio_worker(self, audio_bytes, auto_paste=True, job=None, service=None):
        job = job or self.session.job
        settings = job.settings
        provider = settings.get("provider", "gemini")
        try:
            job.check()
            service = service or self._service(provider)
            service.diagnostics = self.diagnostics
            kwargs = {"mode": settings.get("mode", "dictation"),
                      "custom_vocabulary": list(settings.get("custom_vocabulary", []))}
            if provider != "gemini":
                kwargs.update(language=settings.get("language", "auto"),
                              vocabulary_aliases=dict(settings.get("vocabulary_aliases", {})))
            with execution_scope(job):
                result = service.transcribe_and_format(audio_bytes, **kwargs)
            job.check()
            if not result.text.strip():
                raise ProviderError("EMPTY_OUTPUT", "stt", "Boş yanıt veya ses anlaşılmadı; kayıt korunuyor.")
            from dataclasses import replace
            result = replace(result, job_id=job.id)
            self._emit(job, "processed", (result, auto_paste))
        except Exception as error:
            self._emit(job, "error", self._safe_error(error))

    def _on_work_event(self, event):
        if not self.session.accepts(event):
            return
        job = self.session.job
        if event.kind == "phase":
            self.session.transition(event.value)
        elif event.kind == "retry_audio":
            self.pending_audio = event.value
            self._start_processing(event.value, auto_paste=False)
        elif event.kind == "error":
            # The session state names the stage that was running when the job failed.
            self.diagnostics.event("failed", stage=self.session.state.value,
                                   code=str(event.value).split("]")[0].lstrip("["))
            self._on_processing_error(event.value)
        elif event.kind == "transcript":
            self.last_groq_result = event.value
            self.last_text = event.value.text
            self.session.transition(State.FORMATTING)
        elif event.kind == "captured":
            audio, error = event.value
            self.pending_audio = audio
            if error:
                self._on_processing_error(error)
            elif not audio or len(audio) < 3200:
                self._on_processing_error("[NO_SPEECH] Ses algılanamadı; ham kayıt korunuyor.")
            else:
                self._start_processing(audio)
        elif event.kind == "processed":
            result, auto_paste = event.value
            self.last_groq_result = result
            self.last_text = result.text
            if result.warning:
                self._on_processing_error(result.warning + " Son Sonuç menüsünden metni alın.")
            elif not auto_paste:
                self._on_processing_ready(result.text)
            else:
                self.session.transition(State.DELIVERING)
                self._spawn(self._deliver_worker, job, result)
        elif event.kind == "ready_unverified":
            if event.value:
                # The text is safely on the clipboard; holding the audio would block the next dictation.
                self.recorder.discard_audio()
                self.pending_audio = b""
                self._on_processing_ready(self.last_text, "Hedef pencere bu masaüstünde (ör. Wayland) doğrulanamadığından "
                                          "otomatik yapıştırılmadı. Metin panoya kopyalandı; Ctrl+V ile yapıştırın.")
            else:
                self._on_processing_ready(self.last_text, "Hedef pencere bu masaüstünde (ör. Wayland) doğrulanamadığından "
                                          "otomatik yapıştırılmadı. Metin hazır; Son Sonuç menüsünden kopyalayın.")
        elif event.kind == "delivered":
            success, error, warning = event.value
            if success:
                self._on_processing_success(self.last_text, self.last_groq_result.latency)
                if warning:
                    self._notify_recovery(warning)
            else:
                self._on_processing_error(error)
        elif event.kind == "reformatted":
            original, candidate = event.value
            self._on_reformat_done(original, candidate)

    def _deliver_worker(self, job, result):
        try:
            job.check()
            from .platform.target import target_unchanged
            if job.target is None:
                # Never send input to an unverified window; the clipboard is safe unless the user asked to keep it.
                copied = not self.injector.restore_clipboard and self.injector.set_clipboard(result.text)
                self.diagnostics.event("delivery_finished", stage="delivery",
                                       code="CLIPBOARD_ONLY" if copied else "TARGET_UNVERIFIED")
                self._emit(job, "ready_unverified", copied)
                return
            if not target_unchanged(job.target):
                self._emit(job, "error", "[TARGET_CHANGED] Hedef pencere değişti veya doğrulanamıyor; metin Son Sonuç menüsünde hazır.")
                return
            self.diagnostics.event("delivery_started", stage="delivery")
            def check_delivery():
                job.check()
                if not target_unchanged(job.target):
                    raise ProviderError("TARGET_CHANGED", "delivery", "Hedef pencere değişti; metin Son Sonuç menüsünde korunuyor.")
            success = self.injector.inject_text(result.text, before_paste=check_delivery)
            self.diagnostics.event("delivery_finished", stage="delivery", code="INPUT_SENT" if success else "DELIVERY_FAILED")
            self._emit(job, "delivered", (success, self.injector.last_error or "[DELIVERY_FAILED] Metin Son Sonuç menüsünde korunuyor.",
                                          getattr(self.injector, "last_warning", "")))
        except Exception as error:
            self._emit(job, "error", self._safe_error(error))

    def cancel_processing(self):
        if not self.is_busy_processing:
            return
        self.session.cancel()
        self.diagnostics.event("failed", code="CANCELLED", source="user")
        self._on_processing_error("[CANCELLED] İşlem iptal edildi; alınan ses ve metin korunuyor.")

    def _on_audio_level(self, level: float) -> None:
        if self.recorder.is_recording:
            self.pill.set_audio_level(level)

    def _on_processing_success(self, text: str, latency: float) -> None:
        self.session.transition(State.COMPLETED)
        self.recorder.discard_audio()
        self.pending_audio = b""
        self.last_error = ""
        self.sound.play("success")
        self.pill.show_success(latency=latency)

    def _on_processing_error(self, error_message: str) -> None:
        self.session.transition(State.ERROR)
        self.last_error = error_message
        self.tray.set_recording(False)
        self.sound.play("error")
        self.pill.show_error(error_message)
        self._notify_recovery(error_message)

    def _on_capture_error(self, job_id: str, error_message: str) -> None:
        # Capture callbacks are attached to the session that owns that device.
        if job_id != getattr(self.session.job, "id", None):
            return
        if self.is_busy_processing or self.pending_audio:
            self._notify_recovery(error_message)
            return
        self.diagnostics.event("stop_requested", stage="capture", source="capture_error")
        self.session.transition(State.DRAINING)
        self._spawn(self._drain_worker, self.session.job)

    def _on_processing_ready(self, text: str, message=None) -> None:
        self.session.transition(State.READY)
        self.last_text = text
        self.last_error = message or "Metin hazır. Son Sonuç menüsünden kopyalayabilirsiniz."
        self.pill.hide_pill()
        self.sound.play("success")
        self.tray.showMessage("Kâtip", self.last_error, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _notify_recovery(self, message: str) -> None:
        self.tray.showMessage("Kâtip", message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def _check_for_updates(self) -> None:
        """Launches background thread to check for latest release."""
        threading.Thread(target=self._update_checker_worker, daemon=True).start()

    def _update_checker_worker(self) -> None:
        import re
        import requests
        from . import __version__
        try:
            resp = requests.get(
                "https://api.github.com/repos/fat1h-ozturk/Katip/releases/latest",
                headers={"User-Agent": "Katip-App"},
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json()
                latest_tag = data.get("tag_name", "").strip()
                release_url = data.get("html_url", "https://github.com/fat1h-ozturk/Katip/releases/latest")

                def parse_v(v: str):
                    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v)
                    return tuple(map(int, match.groups())) if match else (0, 0, 0)

                if latest_tag and parse_v(latest_tag) > parse_v(__version__):
                    self.signals.update_available.emit(latest_tag, release_url)
        except Exception:
            pass

    def _on_update_available(self, new_version: str, release_url: str) -> None:
        """Triggered on GUI thread when a new version is detected."""
        # Native OS system tray notification
        self.tray.showMessage(
            f"⚡ Yeni Güncelleme: {new_version}",
            "Güncellemek için yeni sürümü kurun. Ayrıntılar için tıklayın.",
            QSystemTrayIcon.MessageIcon.Information,
            12000,
        )
        try:
            from .desktop import open_url
            self.tray.messageClicked.connect(lambda: open_url(release_url))
        except Exception:
            pass

        # Floating toast notification in top-right corner
        try:
            from .ui.toast import UpdateNotificationToast
            self.update_toast = UpdateNotificationToast(new_version, release_url)
            self.update_toast.show()
        except Exception as error:
            print(f"[Update] Toast notification could not be shown: {error}")

    def retry_last_audio(self, filtered=True) -> None:
        if self.is_busy_processing or self.recorder.is_recording or self.q_app.activeModalWidget() is not None:
            return
        if not self.session.job:
            self.session.begin(self.config.data)
            self.session.transition(State.ERROR)
        self.session.retry(settings=self.config.data)
        self.session.transition(State.PREPROCESSING)
        self.pill.show_processing()
        self._spawn(self._retry_worker, self.session.job, filtered)

    def _retry_worker(self, job, filtered):
        try:
            audio = self.pending_audio if filtered and not self.recorder.has_pending_audio else b""
            if not audio:
                audio = self.recorder.retry_audio(filtered=filtered)
            if not audio:
                raise ProviderError("NO_SPEECH", "preprocessing", "Filtre konuşma bulamadı. Filtresiz yeniden deneyebilir veya ham sesi kaydedebilirsiniz.")
            # Retry is always review-only; never paste into the recovery dialog.
            self._emit(job, "retry_audio", audio)
        except Exception as error:
            self._emit(job, "error", self._safe_error(error))

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
        dialog.setWindowTitle("Kâtip — Son Sonuç")
        dialog.resize(700, 480)
        dialog.setStyleSheet(MINIMAL_DARK_STYLE)
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
                ("Ham Metin", result.raw_transcript or "", "rawTranscript"),
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
            
            literal_changes = getattr(result, "literal_changes", [])
            changes = "\n".join(literal_changes) or "Belirgin literal farkı bulunmadı. Bu, anlamın korunduğunu kanıtlamaz."
            mode = getattr(result, "mode", "dictation")
            language = getattr(result, "language", "auto")
            stt_model = getattr(result, "stt_model", "Bilinmiyor")
            llm_model = getattr(result, "llm_model", "Bilinmiyor")
            omitted_stt = getattr(result, "omitted_stt_terms", 0)
            omitted_fmt = getattr(result, "omitted_formatter_terms", 0)
            segments = getattr(result, "segments", [])
            
            details.setPlainText(
                f"Mod: {mode}\nDil: {language}\n"
                f"STT: {stt_model}\nMetin modeli: {llm_model}\n\n"
                f"STT bağlamına sığmayan terim: {omitted_stt}\n"
                f"Formatter bağlamına sığmayan ipucu: {omitted_fmt}\n\n"
                "İnceleme bilgisi (öz düzeltme ve özetleme bu farkları açıklayabilir):\n"
                f"{changes}\n\nSegment bilgisi (kelime güveni veya doğruluk yüzdesi değildir):\n"
                + json.dumps(segments, ensure_ascii=False, indent=2)
                + "\n\nTeşhis (ses ve metin içermez):\n"
                + json.dumps(self.diagnostics.snapshot(), ensure_ascii=False, indent=2)
            )
            tabs.addTab(details, "Ayrıntılar")
            tabs.setCurrentIndex(1 if result.formatted_text is not None else 0)
        else:
            details = QTextEdit()
            details.setReadOnly(True)
            details.setPlainText(json.dumps(self.diagnostics.snapshot(), ensure_ascii=False, indent=2))
            tabs.addTab(details, "Teşhis")
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
            reformat.setEnabled(bool(result.raw_transcript) and CAPABILITIES[result.provider].reformat)
            reformat.clicked.connect(lambda: (dialog.accept(), self.reformat_last_text(current_settings.isChecked())))
            layout.addWidget(reformat)
        buttons = QHBoxLayout()
        for title, action, enabled in (
            ("Sesi Yeniden İşle", self.retry_last_audio, bool(self.pending_audio or self.recorder.has_pending_audio)),
            ("Filtresiz Yeniden İşle", lambda: self.retry_last_audio(filtered=False), bool(self.recorder.has_pending_audio)),
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
        mode = self.config.get("mode", "dictation") if use_current_settings else getattr(original, "mode", self.config.get("mode", "dictation"))
        vocabulary = list(self.config.get("custom_vocabulary", [])) if use_current_settings else list(getattr(original, "custom_vocabulary", self.config.get("custom_vocabulary", [])))
        aliases = dict(self.config.get("vocabulary_aliases", {})) if use_current_settings else dict(getattr(original, "vocabulary_aliases", self.config.get("vocabulary_aliases", {})))
        
        if not CAPABILITIES[original.provider].reformat:
            self._notify_recovery("Bu sağlayıcı metni yeniden düzenlemeyi desteklemiyor.")
            return
        if original.provider == "groq":
            service = self._get_groq_service(stt_model=original.stt_model, llm_model=original.llm_model)
        else:
            service = self._service(original.provider)
            # Reformat with the original formatter, rather than silently switching providers/models.
            if hasattr(service, "llm_model"):
                service.llm_model = original.llm_model
            elif original.provider == "codex":
                service.codex_model = original.llm_model
            elif original.provider == "agy":
                service.agy_model = original.llm_model
        self.session.retry()
        self.session.transition(State.FORMATTING)
        self.last_error = ""
        self.pill.show_processing()
        self._spawn(self._reformat_text_worker, original, service, mode, vocabulary, aliases, self.session.job)

    def _reformat_text_worker(self, original, service, mode, vocabulary, aliases, job=None):
        job = job or self.session.job
        service.diagnostics = self.diagnostics
        try:
            with execution_scope(job):
                candidate = service.format_transcript(original.raw_transcript, mode=mode,
                    custom_vocabulary=vocabulary, language=original.language,
                    vocabulary_aliases=aliases, segments=original.segments,
                    omitted_stt_terms=original.omitted_stt_terms)
            job.check()
            from dataclasses import replace
            candidate = replace(candidate, stt_model=original.stt_model, segments=original.segments,
                                omitted_stt_terms=original.omitted_stt_terms)
            self._emit(job, "reformatted", (original, candidate))
        except Exception as error:
            self._emit(job, "error", self._safe_error(error))

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
            return
        # An explicit copy of the recovered text acknowledges this recording.
        if text and (text == self.last_text or (self.last_groq_result and text == self.last_groq_result.raw_transcript)):
            try:
                self.recorder.discard_audio()
                self.pending_audio = b""
            except RuntimeError as error:
                self._notify_recovery(str(error))

    def _save_last_audio(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        try:
            raw = self.recorder.raw_wav() or self.pending_audio
            path, _ = QFileDialog.getSaveFileName(None, "Ses Kaydını Kaydet", "katip-kayit.wav", "WAV (*.wav)")
            if path and raw:
                file = QSaveFile(path)
                if not file.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise RuntimeError("Dosya açılamadı.")
                if file.write(raw) != len(raw) or not file.commit():
                    raise RuntimeError("Ses kaydı dosyaya yazılamadı.")
                self.recorder.discard_audio()
                self.pending_audio = b""
                self.last_error = ""
        except RuntimeError as error:
            self._notify_recovery(str(error))

    def _discard_last_audio(self) -> None:
        if self.is_busy_processing or self.recorder.is_recording:
            return
        try:
            self.recorder.discard_audio()
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
            "Kâtip",
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
        if not self.recorder.has_pending_audio and (getattr(self.recorder, "device_index", -1) != new_dev_idx or getattr(self.recorder, "vad_mode", 2) != new_vad_mode):
            self.recorder.terminate()
            self.recorder = AudioRecorder(
                on_level_callback=lambda lvl: self.signals.level_changed.emit(lvl),
                on_error_callback=lambda error: None,
                device_index=new_dev_idx,
                vad_mode=self.config.get("vad_mode", 2)
            )
        # Invalidate cached services so they pick up new config on next use
        for service in (self._gemini_service, self._groq_service, self._openai_service, self._claude_service):
            if service is not None:
                service._session.close()
        self._gemini_service = None
        self._groq_service = None
        self._openai_service = None
        self._claude_service = None
        self._codex_service = None
        self._agy_service = None
        # Refresh hotkey manager
        self.hotkey_mgr.stop()
        self.hotkey_mgr = HotkeyManager(
            hotkey_str=self.config.get("hotkey", "Ctrl+Alt+Space"),
            trigger_mode=self.config.get("trigger_mode", "toggle"),
            on_toggle=lambda: self.signals.toggle_received.emit(),
            on_press=lambda: self.signals.start_received.emit(),
            on_release=lambda: self.signals.stop_received.emit(),
            on_notify_running=lambda: self.signals.notify_received.emit(),
            on_open_settings=lambda: self.signals.settings_received.emit(),
            on_trigger=lambda kind, source: self.signals.trigger_received.emit(kind, source),
            on_status=lambda status: self.signals.hotkey_health.emit(status)
        )
        if not self.hotkey_mgr.start():
            self._notify_recovery("Kısayol iletişimi başlatılamadı. Kâtip'i yeniden açın.")

    def _can_edit_settings(self) -> bool:
        return not (self.is_busy_processing or self.recorder.is_recording or self.recorder.is_capturing)

    def quit(self) -> None:
        if self.is_busy_processing:
            self.cancel_processing()
            self._notify_recovery("İşlem iptal ediliyor; kayıt Son Sonuç menüsünde korunuyor.")
            return
        if self.recorder.is_recording:
            try:
                self.stop_recording_and_process(source="quit")
                return
            except RuntimeError as error:
                self._on_processing_error(str(error))
                return
            self.tray.set_recording(False)
        if self.pending_audio or self.recorder.has_pending_audio:
            self._notify_recovery("Çıkmadan önce Son Sonuç menüsünden kaydı kaydedin veya temizleyin.")
            self.show_last_result()
            return
        self.session.transition(State.SHUTTING_DOWN)
        self.hotkey_mgr.stop()
        if hasattr(self.pill, "close"):
            self.pill.close()
        self.recorder.terminate()
        self._pool.shutdown(wait=False, cancel_futures=True)
        for service in (self._gemini_service, self._groq_service, self._openai_service, self._claude_service):
            if service is not None:
                service._session.close()
        self.last_text = ""
        self.last_groq_result = None
        self._record_app_stopped()
        self.q_app.quit()

    def _record_app_stopped(self) -> None:
        if not getattr(self, "_app_stopped", True):
            self._app_stopped = True
            self.app_diagnostics.event("app_stopped")
