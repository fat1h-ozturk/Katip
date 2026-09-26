"""
Main Application Coordinator for Talk-to-Write.
Connects Audio, AI Services, Text Injector, System Tray, Floating Pill, and Hotkeys.
"""

import os
import sys
import threading
from typing import Optional
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .audio import AudioRecorder
from .config import ConfigManager
from .hotkey import HotkeyManager
from .injector import TextInjector
from .services.gemini import GeminiService
from .services.groq import GroqService
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
    toggle_received = Signal()
    start_received = Signal()
    stop_received = Signal()
    notify_received = Signal()
    settings_received = Signal()

class TalkToWriteApp:
    """The central Talk-to-Write application."""

    def __init__(self, q_app: QApplication):
        self.q_app = q_app
        self.config = ConfigManager()

        # Thread-safe Qt signal bridge
        self.signals = WorkerSignals()
        self.signals.level_changed.connect(self._on_audio_level)
        self.signals.processing_done.connect(self._on_processing_success)
        self.signals.processing_error.connect(self._on_processing_error)
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
            device_index=self.config.get("input_device_index", -1),
            vad_mode=self.config.get("vad_mode", 2)
        )

        # UI Components: Use Wayland Layer Shell overlay (guarantees zero focus loss) if available
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.path.exists("/usr/lib64/libgtk4-layer-shell.so.0"):
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
        self.hotkey_mgr.start()

        self.is_busy_processing = False

        # Lazy-initialized AI service singletons (avoids re-creating per request)
        self._gemini_service: Optional[GeminiService] = None
        self._groq_service: Optional[GroqService] = None

        # Guide user: if API key is not configured yet, open Settings on first run
        if not self.config.get_api_key():
            QTimer.singleShot(400, self.open_settings)

    def _get_gemini_service(self) -> GeminiService:
        """Returns a cached GeminiService, recreating only if config changed."""
        api_key = self.config.get("gemini_api_key", "")
        model = self.config.get("gemini_model", "gemini-2.0-flash")
        if self._gemini_service is None or \
           self._gemini_service.api_key != api_key.strip() or \
           self._gemini_service.model != model:
            self._gemini_service = GeminiService(api_key=api_key, model=model)
        return self._gemini_service

    def _get_groq_service(self) -> GroqService:
        """Returns a cached GroqService, recreating only if config changed."""
        api_key = self.config.get("groq_api_key", "")
        stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        llm_model = self.config.get("groq_llm_model", "qwen/qwen3.8-27b")
        if self._groq_service is None or \
           self._groq_service.api_key != api_key.strip() or \
           self._groq_service.stt_model != stt_model or \
           self._groq_service.llm_model != llm_model:
            self._groq_service = GroqService(api_key=api_key, stt_model=stt_model, llm_model=llm_model)
        return self._groq_service

    def start_recording(self) -> None:
        """Starts audio recording if not already recording or busy."""
        if self.is_busy_processing or self.recorder.is_recording:
            return
        current_mode = self.config.get("mode", "dictation")
        print(f"[App] Kayıt başladı (Mod: {current_mode})")
        self.sound.play("start")
        self.pill.show_recording(mode=current_mode)
        self.tray.set_recording(True)
        self.recorder.start_recording()

    def stop_recording_and_process(self) -> None:
        """Stops audio recording and sends audio to AI pipeline."""
        if not self.recorder.is_recording:
            return
        print("[App] Kayıt durduruldu, ses işleniyor...")
        self.sound.play("stop")
        self.pill.show_processing()
        self.tray.set_recording(False)
        self.is_busy_processing = True
        self.q_app.processEvents()

        audio_bytes = self.recorder.stop_recording()

        if not audio_bytes or len(audio_bytes) < 3200:  # < 0.1s
            print("[App] Çok kısa ses veya ses algılanamadı.")
            self.is_busy_processing = False
            self.sound.play("error")
            self.pill.show_error("Ses algılanamadı.")
            return

        threading.Thread(target=self._process_audio_worker, args=(audio_bytes,), daemon=True).start()

    def toggle_recording(self) -> None:
        """Toggles between starting audio capture and sending to AI."""
        if self.is_busy_processing:
            print("[App] Henüz önceki işlem devam ediyor, bekleniyor...")
            return

        if not self.recorder.is_recording:
            self.start_recording()
        else:
            self.stop_recording_and_process()

    def _process_audio_worker(self, audio_bytes: bytes) -> None:
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
            else:
                lang = self.config.get("language", "tr")
                service = self._get_groq_service()
                text, latency = service.transcribe_and_format(
                    audio_bytes, mode=mode, custom_vocabulary=custom_vocab, language=lang
                )

            if not text.strip():
                print("[App] AI boş yanıt döndürdü.")
                self.signals.processing_error.emit("Boş yanıt veya ses anlaşılmadı.")
                return

            print(f"[App] Metin alındı ({latency}s): {text[:60]}...")

            # Inject text into active window
            success = self.injector.inject_text(text)
            if success:
                print("[App] Metin aktif pencereye başarıyla yapıştırıldı!")
            else:
                print(f"[App] Metin panoya kopyalandı (Ctrl+V ydotool gönderilemedi)")

            self.signals.processing_done.emit(text, latency)

        except Exception as e:
            print(f"[App] Hata oluştu: {e}")
            self.signals.processing_error.emit(str(e))
        finally:
            self.is_busy_processing = False

    def _on_audio_level(self, level: float) -> None:
        if self.recorder.is_recording:
            self.pill.set_audio_level(level)

    def _on_processing_success(self, text: str, latency: float) -> None:
        self.is_busy_processing = False
        self.sound.play("success")
        self.pill.show_success(latency=latency)

    def _on_processing_error(self, error_message: str) -> None:
        self.is_busy_processing = False
        self.sound.play("error")
        self.pill.show_error(error_message)

    def _on_mode_changed(self, new_mode: str) -> None:
        self.config.set("mode", new_mode)
        self.pill.set_mode(new_mode)

    def _on_notify_running(self) -> None:
        hotkey = self.config.get("hotkey", "Ctrl+Alt+Space")
        self.tray.showMessage(
            "Talk-to-Write",
            f"Uygulama zaten arka planda çalışıyor.\n🎙️ Dikte Kısayolu: {hotkey}",
            QSystemTrayIcon.MessageIcon.Information,
            3500
        )
        self.open_settings()

    def open_settings(self) -> None:
        if not self.settings_dialog:
            self.settings_dialog = SettingsDialog(self.config)
            self.settings_dialog.config_updated.connect(self._on_config_updated)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _on_config_updated(self) -> None:
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
                device_index=new_dev_idx,
                vad_mode=self.config.get("vad_mode", 2)
            )
        # Invalidate cached services so they pick up new config on next use
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
        self.hotkey_mgr.start()

    def quit(self) -> None:
        self.hotkey_mgr.stop()
        if hasattr(self.pill, "close"):
            self.pill.close()
        if self.recorder.is_recording:
            self.recorder.stop_recording()
        self.recorder.terminate()
        self.q_app.quit()
