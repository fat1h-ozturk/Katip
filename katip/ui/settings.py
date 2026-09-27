"""
Settings dialog for Katip.
Allows configuring API keys, AI providers, models, hotkeys, and custom vocabulary.
"""

from typing import Callable, Optional
import sys
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..audio import get_input_devices
from ..config import ConfigManager
from .hotkey_recorder import HotkeyRecorderWidget
from ..desktop import (
    install_desktop_entry,
    is_autostart_enabled,
    is_desktop_installed,
    set_autostart,
    uninstall_desktop_entry,
)

DARK_STYLE = """
QDialog {
    background-color: #18181b;
    color: #f4f4f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}
QGroupBox {
    border: 1px solid #27272a;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: bold;
    color: #e4e4e7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLabel {
    color: #a1a1aa;
    font-size: 13px;
}
QLineEdit, QComboBox, QTextEdit {
    background-color: #27272a;
    border: 1px solid #3f3f46;
    border-radius: 6px;
    padding: 6px 10px;
    color: #fafafa;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #6366f1;
}
QComboBox QAbstractItemView {
    background-color: #27272a;
    border: 1px solid #3f3f46;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
    outline: none;
}
QAbstractItemView::item {
    min-height: 28px;
    padding: 4px 8px;
}
QPushButton {
    background-color: #3f3f46;
    color: #f4f4f5;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #52525b;
}
QPushButton#primaryBtn {
    background-color: #4f46e5;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #4338ca;
}
QCheckBox {
    color: #d4d4d8;
    spacing: 8px;
}
"""

class SettingsDialog(QDialog):
    """Settings modal window for configuring Katip."""

    config_updated = Signal()

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Katip Ayarları")
        self.resize(540, 650)
        self.setStyleSheet(DARK_STYLE)

        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Title
        title_label = QLabel("⚡ Katip Ayarları")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        main_layout.addWidget(title_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; } QScrollBar:vertical { width: 10px; background: #18181b; } QScrollBar::handle:vertical { background: #3f3f46; border-radius: 5px; } QScrollBar::handle:vertical:hover { background: #52525b; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("scrollContent")
        scroll_content.setStyleSheet("QWidget#scrollContent { background-color: transparent; }")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 4, 10, 0)
        content_layout.setSpacing(16)
        
        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area)

        # 1. AI Provider Group
        ai_group = QGroupBox("Yapay Zeka & Model Sağlayıcısı")
        ai_layout = QFormLayout(ai_group)
        ai_layout.setSpacing(10)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google Gemini (Önerilen - Ücretsiz & Hızlı)", "gemini")
        self.provider_combo.addItem("Groq Cloud (Whisper + Llama 3)", "groq")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        ai_layout.addRow("Sağlayıcı:", self.provider_combo)

        # Gemini API Key
        key_layout = QHBoxLayout()
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_edit.setPlaceholderText("AIzaSy...")
        self.toggle_key_btn = QPushButton("👁")
        self.toggle_key_btn.setFixedWidth(36)
        self.toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        key_layout.addWidget(self.gemini_key_edit)
        key_layout.addWidget(self.toggle_key_btn)
        self.gemini_key_label = QLabel("Gemini API Anahtarı:")
        ai_layout.addRow(self.gemini_key_label, key_layout)

        # Gemini Model
        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems(["gemini-2.0-flash", "gemini-1.5-flash"])
        self.gemini_model_label = QLabel("Gemini Modeli:")
        ai_layout.addRow(self.gemini_model_label, self.gemini_model_combo)

        # Groq API Key
        self.groq_key_edit = QLineEdit()
        self.groq_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.groq_key_edit.setPlaceholderText("gsk_...")
        self.groq_key_label = QLabel("Groq API Anahtarı:")
        ai_layout.addRow(self.groq_key_label, self.groq_key_edit)

        # Groq STT Model
        self.groq_stt_combo = QComboBox()
        self.groq_stt_combo.addItem("whisper-large-v3 (En Yüksek Doğruluk - Önerilen)", "whisper-large-v3")
        self.groq_stt_combo.addItem("whisper-large-v3-turbo (Ultra Hızlı)", "whisper-large-v3-turbo")
        self.groq_stt_label = QLabel("Groq STT (Ses) Modeli:")
        ai_layout.addRow(self.groq_stt_label, self.groq_stt_combo)

        # Groq LLM Model
        self.groq_llm_combo = QComboBox()
        self.groq_llm_combo.addItem("qwen/qwen3.8-27b (Qwen 3.8 27B - Önerilen)", "qwen/qwen3.8-27b")
        self.groq_llm_combo.addItem("llama-3.3-70b-versatile (Meta Llama 3.3 70B)", "llama-3.3-70b-versatile")
        self.groq_llm_label = QLabel("Groq LLM (Metin) Modeli:")
        ai_layout.addRow(self.groq_llm_label, self.groq_llm_combo)

        # Language selection
        self.language_combo = QComboBox()
        self.language_combo.addItem("Otomatik Algıla (Auto)", "auto")
        self.language_combo.addItem("Türkçe (tr)", "tr")
        self.language_combo.addItem("İngilizce (en)", "en")
        self.language_label = QLabel("Konuşma Dili:")
        ai_layout.addRow(self.language_label, self.language_combo)

        content_layout.addWidget(ai_group)

        # 2. Shortcut & Trigger Group
        trigger_group = QGroupBox("Kısayol ve Tetikleyici")
        trigger_layout = QFormLayout(trigger_group)
        trigger_layout.setSpacing(8)

        self.hotkey_edit = HotkeyRecorderWidget()
        trigger_layout.addRow("Genel Kısayol:", self.hotkey_edit)

        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItem("Aç / Kapa (Toggle) — Basınca başlar, tekrar basınca durur", "toggle")
        self.trigger_mode_combo.addItem("Bas-Konuş (Push-to-Talk) — Basılı tutunca dinler, bırakınca yazar", "push_to_talk")
        trigger_layout.addRow("Çalışma Şekli:", self.trigger_mode_combo)


        content_layout.addWidget(trigger_group)

        # 3. Audio & Microphone Group
        audio_group = QGroupBox("Mikrofon ve Ses Girişi")
        audio_layout = QFormLayout(audio_group)
        audio_layout.setSpacing(8)

        self.mic_combo = QComboBox()
        self.mic_combo.addItem("Varsayılan Sistem Mikrofonu", -1)
        for dev in get_input_devices():
            dev_label = f"{dev['name']} {'(Varsayılan)' if dev.get('is_default') else ''}"
            self.mic_combo.addItem(dev_label, dev["index"])
        audio_layout.addRow("Mikrofon:", self.mic_combo)

        self.vad_combo = QComboBox()
        self.vad_combo.addItem("Düşük (1) - Hassas", 1)
        self.vad_combo.addItem("Orta (2) - Dengeli", 2)
        self.vad_combo.addItem("Yüksek (3) - Agresif", 3)
        audio_layout.addRow("Gürültü Filtreleme (VAD):", self.vad_combo)

        test_mic_layout = QHBoxLayout()
        self.test_mic_btn = QPushButton("🎙️ Mikrofonu Test Et (2 sn)")
        self.test_mic_btn.clicked.connect(self._test_microphone)
        self.mic_status_lbl = QLabel("Ses testi için butona tıklayın ve konuşun.")
        self.mic_status_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        test_mic_layout.addWidget(self.test_mic_btn)
        test_mic_layout.addWidget(self.mic_status_lbl)
        test_mic_layout.addStretch()
        audio_layout.addRow("", test_mic_layout)

        content_layout.addWidget(audio_group)

        # 4. Custom Vocabulary
        vocab_group = QGroupBox("Özel Kelime Dağarcığı (Custom Vocabulary)")
        vocab_layout = QVBoxLayout(vocab_group)
        vocab_info = QLabel("Sık kullandığınız isimler, teknik terimler ve kodlama kütüphaneleri (virgülle ayırın):")
        vocab_info.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        self.vocab_edit = QLineEdit()
        self.vocab_edit.setPlaceholderText("Örn: Katip, Gemini, PySide6, Docker, Kubernetes, Fatih")
        vocab_layout.addWidget(vocab_info)
        vocab_layout.addWidget(self.vocab_edit)
        content_layout.addWidget(vocab_group)

        # 4. Preferences Checkboxes
        pref_layout = QVBoxLayout()
        pref_layout.setSpacing(8)
        
        row1_layout = QHBoxLayout()
        self.sound_check = QCheckBox("Ses Geri Bildirimi (Bip sesleri)")
        self.restore_clip_check = QCheckBox("Panoyu Eski Haline Getir")
        row1_layout.addWidget(self.sound_check)
        row1_layout.addWidget(self.restore_clip_check)
        
        row2_layout = QHBoxLayout()
        self.terminal_paste_check = QCheckBox("Linux Terminal Uyumluluk Modu (Ctrl+Shift+V ile yapıştır)")
        row2_layout.addWidget(self.terminal_paste_check)
        row2_layout.addStretch()

        pref_layout.addLayout(row1_layout)
        pref_layout.addLayout(row2_layout)
        content_layout.addLayout(pref_layout)

        # 5. Desktop & Startup Integration Group
        desktop_group = QGroupBox("Sistem & Başlat Menüsü Entegrasyonu")
        desktop_layout = QVBoxLayout(desktop_group)
        desktop_layout.setSpacing(8)

        menu_row = QHBoxLayout()
        self.desktop_status_lbl = QLabel("Uygulama Menüsü: Kontrol ediliyor...")
        self.desktop_status_lbl.setStyleSheet("color: #e4e4e7; font-size: 12px;")

        self.desktop_action_btn = QPushButton("Menüye Ekle")
        self.desktop_action_btn.clicked.connect(self._toggle_desktop_entry)

        menu_row.addWidget(self.desktop_status_lbl)
        menu_row.addStretch()
        menu_row.addWidget(self.desktop_action_btn)
        desktop_layout.addLayout(menu_row)

        self.autostart_check = QCheckBox("Bilgisayar açıldığında arka planda otomatik başlat (Autostart)")
        self.autostart_check.toggled.connect(self._on_autostart_toggled)
        desktop_layout.addWidget(self.autostart_check)

        content_layout.addWidget(desktop_group)

        content_layout.addStretch()

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        self.test_paste_btn = QPushButton("📋 Metin Enjeksiyonunu Test Et")
        self.test_paste_btn.clicked.connect(self._test_injection)

        self.save_btn = QPushButton("Kaydet")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.clicked.connect(self._save_settings)

        self.cancel_btn = QPushButton("Kapat")
        self.cancel_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.test_paste_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        main_layout.addLayout(btn_layout)

    def _on_provider_changed(self) -> None:
        is_gemini = self.provider_combo.currentData() == "gemini"
        self.gemini_key_label.setVisible(is_gemini)
        self.gemini_key_edit.setVisible(is_gemini)
        self.toggle_key_btn.setVisible(is_gemini)
        self.gemini_model_label.setVisible(is_gemini)
        self.gemini_model_combo.setVisible(is_gemini)

        self.groq_key_label.setVisible(not is_gemini)
        self.groq_key_edit.setVisible(not is_gemini)
        self.groq_stt_label.setVisible(not is_gemini)
        self.groq_stt_combo.setVisible(not is_gemini)
        self.groq_llm_label.setVisible(not is_gemini)
        self.groq_llm_combo.setVisible(not is_gemini)

    def _toggle_key_visibility(self) -> None:
        if self.gemini_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _update_desktop_status(self) -> None:
        installed = is_desktop_installed()
        if installed:
            self.desktop_status_lbl.setText("✓ Başlat / Uygulama menüsüne kayıtlı")
            self.desktop_status_lbl.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: 500;")
            self.desktop_action_btn.setText("Menüden Kaldır")
        else:
            self.desktop_status_lbl.setText("✗ Uygulama menüsüne kayıtlı değil")
            self.desktop_status_lbl.setStyleSheet("color: #f87171; font-size: 12px; font-weight: 500;")
            self.desktop_action_btn.setText("Menüye Ekle")

    def _toggle_desktop_entry(self) -> None:
        if is_desktop_installed():
            uninstall_desktop_entry()
            QMessageBox.information(self, "Bilgi", "Katip uygulama menüsünden kaldırıldı.")
        else:
            install_desktop_entry()
            QMessageBox.information(self, "Bilgi", "Katip uygulama menüsüne başarıyla kaydedildi!")
        self._update_desktop_status()

    def _on_autostart_toggled(self, checked: bool) -> None:
        set_autostart(checked)

    def _load_values(self) -> None:
        provider = self.config.get("provider", "gemini")
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

        self.gemini_key_edit.setText(self.config.get("gemini_api_key", ""))
        self.gemini_model_combo.setCurrentText(self.config.get("gemini_model", "gemini-2.0-flash"))
        self.groq_key_edit.setText(self.config.get("groq_api_key", ""))

        stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        stt_idx = self.groq_stt_combo.findData(stt_model)
        if stt_idx >= 0:
            self.groq_stt_combo.setCurrentIndex(stt_idx)

        llm_model = self.config.get("groq_llm_model", "qwen/qwen3.8-27b")
        llm_idx = self.groq_llm_combo.findData(llm_model)
        if llm_idx >= 0:
            self.groq_llm_combo.setCurrentIndex(llm_idx)

        lang = self.config.get("language", "auto")
        lang_idx = self.language_combo.findData(lang)
        if lang_idx >= 0:
            self.language_combo.setCurrentIndex(lang_idx)

        dev_idx = self.config.get("input_device_index", -1)
        found_idx = self.mic_combo.findData(dev_idx)
        if found_idx >= 0:
            self.mic_combo.setCurrentIndex(found_idx)

        vad = self.config.get("vad_mode", 2)
        vad_idx = self.vad_combo.findData(vad)
        if vad_idx >= 0:
            self.vad_combo.setCurrentIndex(vad_idx)

        self.hotkey_edit.set_hotkey(self.config.get("hotkey", "Ctrl+Alt+Space"))
        trigger_mode = self.config.get("trigger_mode", "toggle")
        t_idx = self.trigger_mode_combo.findData(trigger_mode)
        if t_idx >= 0:
            self.trigger_mode_combo.setCurrentIndex(t_idx)

        vocab = self.config.get("custom_vocabulary", [])
        self.vocab_edit.setText(", ".join(vocab))

        self.sound_check.setChecked(self.config.get("sound_effects", True))
        self.restore_clip_check.setChecked(self.config.get("restore_clipboard", False))
        self.terminal_paste_check.setChecked(self.config.get("terminal_paste_mode", False))

        self.autostart_check.blockSignals(True)
        self.autostart_check.setChecked(is_autostart_enabled())
        self.autostart_check.blockSignals(False)

        self._update_desktop_status()
        self._on_provider_changed()

    def _save_settings(self) -> None:
        self.config.set("provider", self.provider_combo.currentData())
        self.config.set("gemini_api_key", self.gemini_key_edit.text().strip())
        self.config.set("gemini_model", self.gemini_model_combo.currentText().strip())
        self.config.set("groq_api_key", self.groq_key_edit.text().strip())
        self.config.set("groq_stt_model", self.groq_stt_combo.currentData())
        self.config.set("groq_llm_model", self.groq_llm_combo.currentData())
        self.config.set("language", self.language_combo.currentData())
        self.config.set("input_device_index", self.mic_combo.currentData())
        self.config.set("vad_mode", self.vad_combo.currentData())
        self.config.set("hotkey", self.hotkey_edit.get_hotkey())
        self.config.set("trigger_mode", self.trigger_mode_combo.currentData())

        raw_vocab = self.vocab_edit.text().split(",")
        vocab = [v.strip() for v in raw_vocab if v.strip()]
        self.config.set("custom_vocabulary", vocab)

        self.config.set("sound_effects", self.sound_check.isChecked())
        self.config.set("restore_clipboard", self.restore_clip_check.isChecked())
        self.config.set("terminal_paste_mode", self.terminal_paste_check.isChecked())

        set_autostart(self.autostart_check.isChecked())

        self.config_updated.emit()

        # Görsel onay: pencereyi kapatmadan butonda "Kaydedildi" göster
        self.save_btn.setText("✓ Kaydedildi!")
        self.save_btn.setStyleSheet("background-color: #16a34a; color: #ffffff;")
        QTimer.singleShot(1500, self._reset_save_btn)

    def _reset_save_btn(self) -> None:
        self.save_btn.setText("Kaydet")
        self.save_btn.setStyleSheet("")

    def _test_microphone(self) -> None:
        import pyaudio, struct, math
        dev_idx = self.mic_combo.currentData()
        self.test_mic_btn.setEnabled(False)
        self.mic_status_lbl.setText("Dinleniyor... Lütfen mikrofona konuşun...")
        self.mic_status_lbl.setStyleSheet("color: #60a5fa; font-size: 11px; font-weight: bold;")
        self.repaint()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        p = pyaudio.PyAudio()
        try:
            stream_kwargs = {
                "format": pyaudio.paInt16,
                "channels": 1,
                "rate": 16000,
                "input": True,
                "frames_per_buffer": 1024
            }
            if dev_idx is not None and dev_idx >= 0:
                stream_kwargs["input_device_index"] = dev_idx

            stream = p.open(**stream_kwargs)
            max_rms = 0.0
            for _ in range(30):  # ~2 seconds
                data = stream.read(1024, exception_on_overflow=False)
                shorts = struct.unpack(f"{len(data)//2}h", data)
                if shorts:
                    sum_sq = sum(s * s for s in shorts)
                    rms = math.sqrt(sum_sq / len(shorts)) / 32768.0
                    if rms > max_rms:
                        max_rms = rms
                QApplication.processEvents()
            stream.stop_stream()
            stream.close()

            if max_rms > 0.0008:
                self.mic_status_lbl.setText(f"✓ Ses başarıyla algılandı! (Seviye: {max_rms:.4f})")
                self.mic_status_lbl.setStyleSheet("color: #4ade80; font-size: 11px; font-weight: bold;")
            else:
                self.mic_status_lbl.setText(f"⚠️ Ses çok kısık veya algılanamadı ({max_rms:.5f}). Mikrofonu/ses düzeyini kontrol edin.")
                self.mic_status_lbl.setStyleSheet("color: #f87171; font-size: 11px; font-weight: bold;")
        except Exception as e:
            self.mic_status_lbl.setText(f"Mikrofon açılamadı: {e}")
            self.mic_status_lbl.setStyleSheet("color: #f87171; font-size: 11px;")
        finally:
            p.terminate()
            self.test_mic_btn.setEnabled(True)

    def _test_injection(self) -> None:
        from ..injector import TextInjector
        injector = TextInjector()
        test_text = "🎉 Katip başarıyla metin enjekte ediyor!"
        success = injector.inject_text(test_text)
        if success:
            QMessageBox.information(
                self,
                "Test Başarılı",
                "Metin panoya kopyalandı ve aktif pencereye yapıştırma simülasyonu gönderildi!"
            )
        else:
            if sys.platform == "darwin":
                help_text = (
                    "macOS'ta Sistem Ayarları > Gizlilik ve Güvenlik > Otomasyon bölümünde "
                    "uygulamanın/Terminal'in System Events'i denetlemesine izin verin; "
                    "Erişilebilirlik iznini de açın."
                )
            elif sys.platform.startswith("linux"):
                help_text = "Linux'ta ydotool servisinin çalıştığını kontrol edin."
            else:
                help_text = "İşletim sisteminin klavye denetimi izinlerini kontrol edin."
            QMessageBox.warning(
                self,
                "Test Uyarısı",
                f"Metin panoya kopyalandı ancak otomatik yapıştırma gönderilemedi.\n\n{help_text}"
            )
