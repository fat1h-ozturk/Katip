"""
Settings dialog for Katip.
Allows configuring API keys, AI providers, models, hotkeys, and custom vocabulary.
"""

from typing import Callable, Optional
from contextlib import suppress
import sys
import unicodedata
from PySide6.QtCore import QTimer, Signal, QEvent, QObject
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
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..audio import get_input_devices
from ..config import ConfigManager, DEFAULT_GEMINI_MODEL, normalize_vocabulary_aliases
from ..prompts import build_whisper_prompt
from .hotkey_recorder import HotkeyRecorderWidget
from ..desktop import (
    install_desktop_entry,
    is_autostart_enabled,
    is_desktop_installed,
    set_autostart,
    uninstall_desktop_entry,
)

from .styles import MINIMAL_DARK_STYLE


def parse_vocabulary_aliases(text: str) -> dict[str, str]:
    """Parse multiline hints and detect conflicts before a dict can overwrite them."""
    aliases = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.count("=>") != 1:
            raise ValueError(f"{line_number}. satır 'varyant => yazım' biçiminde olmalıdır.")
        variant, spelling = (unicodedata.normalize("NFC", part.strip()) for part in line.split("=>"))
        pair = normalize_vocabulary_aliases({variant: spelling})
        if variant in aliases and aliases[variant] != spelling:
            raise ValueError(f"{line_number}. satır: Aynı varyant farklı yazımlara bağlanamaz: {variant}")
        aliases.update(pair)
        if len(aliases) > 100:
            raise ValueError("Yazım eşleşmeleri en fazla 100 kayıt olabilir.")
    return aliases

class SettingsDialog(QDialog):
    """Settings modal window for configuring Katip."""

    config_updated = Signal()

    def __init__(self, config: ConfigManager, parent=None, can_edit: Optional[Callable[[], bool]] = None):
        super().__init__(parent)
        self.config = config
        self.can_edit = can_edit or (lambda: True)
        self.setWindowTitle("Kâtip Ayarları")
        self.resize(750, 750)
        self.setStyleSheet(MINIMAL_DARK_STYLE)

        self._build_ui()
        self._load_values()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._reset_save_btn)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Title
        title_label = QLabel("⚡ Kâtip Ayarları")
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
        self.provider_combo.addItem("Google Gemini", "gemini")
        self.provider_combo.addItem("Groq Cloud (Whisper + Llama 3)", "groq")
        self.provider_combo.addItem("ChatGPT (OpenAI)", "openai")
        self.provider_combo.addItem("Claude (Anthropic)", "claude")
        self.provider_combo.addItem("Codex Desktop (Yerel Uygulama)", "codex")
        self.provider_combo.addItem("Antigravity CLI (Yerel Uygulama)", "agy")
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
        self.gemini_model_combo.addItems([DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite"])
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

        # OpenAI API Key
        self.openai_key_edit = QLineEdit()
        self.openai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_edit.setPlaceholderText("sk-...")
        self.openai_key_label = QLabel("OpenAI API Anahtarı:")
        ai_layout.addRow(self.openai_key_label, self.openai_key_edit)

        # OpenAI Models
        self.openai_stt_combo = QComboBox()
        self.openai_stt_combo.addItem("whisper-1", "whisper-1")
        self.openai_stt_label = QLabel("OpenAI STT Modeli:")
        ai_layout.addRow(self.openai_stt_label, self.openai_stt_combo)

        self.openai_llm_combo = QComboBox()
        self.openai_llm_combo.addItem("gpt-5-mini", "gpt-5-mini")
        self.openai_llm_combo.addItem("gpt-5.4", "gpt-5.4")
        self.openai_llm_combo.addItem("gpt-5.5", "gpt-5.5")
        self.openai_llm_combo.addItem("gpt-5.6-luna", "gpt-5.6-luna")
        self.openai_llm_combo.addItem("gpt-5.6-terra", "gpt-5.6-terra")
        self.openai_llm_combo.addItem("gpt-4o-mini", "gpt-4o-mini")
        self.openai_llm_combo.addItem("gpt-4o", "gpt-4o")
        self.openai_llm_label = QLabel("OpenAI LLM Modeli:")
        ai_layout.addRow(self.openai_llm_label, self.openai_llm_combo)

        # Anthropic API Key
        self.anthropic_key_edit = QLineEdit()
        self.anthropic_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key_edit.setPlaceholderText("sk-ant-...")
        self.anthropic_key_label = QLabel("Anthropic API Anahtarı:")
        ai_layout.addRow(self.anthropic_key_label, self.anthropic_key_edit)

        # Claude Model
        self.claude_llm_combo = QComboBox()
        self.claude_llm_combo.addItem("claude-5-sonnet", "claude-5-sonnet")
        self.claude_llm_combo.addItem("claude-5-opus", "claude-5-opus")
        self.claude_llm_combo.addItem("claude-4.5-haiku", "claude-4.5-haiku")
        self.claude_llm_combo.addItem("claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20241022")
        self.claude_llm_label = QLabel("Claude LLM Modeli:")
        ai_layout.addRow(self.claude_llm_label, self.claude_llm_combo)

        # Codex Model
        self.codex_llm_combo = QComboBox()
        self.codex_llm_combo.addItem("Varsayılan (Codex Ayarları)", "")
        self.codex_llm_combo.addItem("gpt-5.6-luna", "gpt-5.6-luna")
        self.codex_llm_combo.addItem("gpt-5.5", "gpt-5.5")
        self.codex_llm_combo.addItem("gpt-5.4", "gpt-5.4")
        self.codex_llm_combo.addItem("gpt-5-mini", "gpt-5-mini")
        self.codex_llm_label = QLabel("Codex LLM Modeli:")
        ai_layout.addRow(self.codex_llm_label, self.codex_llm_combo)
        
        # Antigravity Model
        self.agy_llm_combo = QComboBox()
        self.agy_llm_combo.addItem("Varsayılan (Antigravity Ayarları)", "")
        self.agy_llm_combo.addItem("Gemini 3.8 Flash (High)", "gemini-3.8-flash-high")
        self.agy_llm_combo.addItem("Gemini 3.8 Flash (Medium)", "gemini-3.8-flash-medium")
        self.agy_llm_combo.addItem("Gemini 3.8 Flash (Low)", "gemini-3.8-flash-low")
        self.agy_llm_combo.addItem("Gemini 3.1 Pro (High)", "gemini-3.1-pro-high")
        self.agy_llm_label = QLabel("Antigravity Modeli:")
        ai_layout.addRow(self.agy_llm_label, self.agy_llm_combo)

        # STT Note for Claude, Codex, Antigravity
        self.stt_note_label = QLabel("Not: Ses tanıma (STT) için ücretsiz Groq Whisper anahtarı kullanılır.")
        self.stt_note_label.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        ai_layout.addRow("", self.stt_note_label)

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
        self.vocab_edit.setPlaceholderText("Örn: Kâtip, Gemini, PySide6, Docker, Kubernetes, Fatih")
        vocab_layout.addWidget(vocab_info)
        vocab_layout.addWidget(self.vocab_edit)
        self.aliases_edit = QTextEdit()
        self.aliases_edit.setPlaceholderText("Örn: paysayd altı => PySide6")
        self.aliases_edit.setFixedHeight(80)
        self.aliases_edit.setAccessibleName("Telaffuz ve yazım eşleşmeleri")
        vocab_layout.addWidget(QLabel("Telaffuz / yazım ipuçları (her satır: varyant => doğru yazım):"))
        vocab_layout.addWidget(self.aliases_edit)
        self.whisper_budget_label = QLabel()
        self.whisper_budget_label.setWordWrap(True)
        vocab_layout.addWidget(self.whisper_budget_label)
        self.vocab_edit.textChanged.connect(self._update_whisper_budget_hint)
        self.aliases_edit.textChanged.connect(self._update_whisper_budget_hint)
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
        
        # Make all inputs stretch to uniform maximum width
        for widget in self.findChildren(QComboBox) + self.findChildren(QLineEdit):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _on_provider_changed(self) -> None:
        provider = self.provider_combo.currentData()
        
        is_gemini = provider == "gemini"
        is_groq = provider == "groq"
        is_openai = provider == "openai"
        is_claude = provider == "claude"
        is_codex = provider == "codex"
        is_agy = provider == "agy"
        
        needs_stt_key = is_claude or is_codex or is_agy

        # Gemini
        self.gemini_key_label.setVisible(is_gemini)
        self.gemini_key_edit.setVisible(is_gemini)
        self.toggle_key_btn.setVisible(is_gemini)
        self.gemini_model_label.setVisible(is_gemini)
        self.gemini_model_combo.setVisible(is_gemini)

        # Groq (show STT models for Groq, show keys if needs_stt_key)
        self.groq_key_label.setVisible(is_groq or needs_stt_key)
        self.groq_key_edit.setVisible(is_groq or needs_stt_key)
        self.groq_stt_label.setVisible(is_groq)
        self.groq_stt_combo.setVisible(is_groq)
        self.groq_llm_label.setVisible(is_groq)
        self.groq_llm_combo.setVisible(is_groq)
        
        # OpenAI (only show when OpenAI is the selected provider)
        self.openai_key_label.setVisible(is_openai)
        self.openai_key_edit.setVisible(is_openai)
        self.openai_stt_label.setVisible(is_openai)
        self.openai_stt_combo.setVisible(is_openai)
        self.openai_llm_label.setVisible(is_openai)
        self.openai_llm_combo.setVisible(is_openai)
        
        # Anthropic (Claude)
        self.anthropic_key_label.setVisible(is_claude)
        self.anthropic_key_edit.setVisible(is_claude)
        self.claude_llm_label.setVisible(is_claude)
        self.claude_llm_combo.setVisible(is_claude)
        
        # Codex
        self.codex_llm_label.setVisible(is_codex)
        self.codex_llm_combo.setVisible(is_codex)
        
        # Antigravity
        self.agy_llm_label.setVisible(is_agy)
        self.agy_llm_combo.setVisible(is_agy)
        
        # Note
        self.stt_note_label.setVisible(needs_stt_key)

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
            success = uninstall_desktop_entry()
            message = "Kâtip uygulama menüsünden kaldırıldı."
        else:
            success = install_desktop_entry()
            message = "Kâtip uygulama menüsüne başarıyla kaydedildi!"
        if success:
            QMessageBox.information(self, "Bilgi", message)
        else:
            QMessageBox.warning(self, "İşlem Başarısız", "Uygulama menüsü kaydı değiştirilemedi.")
        self._update_desktop_status()

    def _load_values(self) -> None:
        provider = self.config.get("provider", "gemini")
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

        def _set_combo(combo: QComboBox, value: str):
            if not value:
                idx = combo.findData("")
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                return
            idx = combo.findData(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.addItem(value, value)
                combo.setCurrentIndex(combo.count() - 1)

        self.gemini_key_edit.setText(self.config.get("gemini_api_key", ""))
        _set_combo(self.gemini_model_combo, self.config.get("gemini_model", DEFAULT_GEMINI_MODEL))
        
        self.groq_key_edit.setText(self.config.get("groq_api_key", ""))
        stt_model = self.config.get("groq_stt_model", "whisper-large-v3-turbo")
        stt_idx = self.groq_stt_combo.findData(stt_model)
        if stt_idx >= 0:
            self.groq_stt_combo.setCurrentIndex(stt_idx)

        _set_combo(self.groq_llm_combo, self.config.get("groq_llm_model", "qwen/qwen3.8-27b"))
            
        self.openai_key_edit.setText(self.config.get("openai_api_key", ""))
        openai_stt = self.config.get("openai_stt_model", "whisper-1")
        o_stt_idx = self.openai_stt_combo.findData(openai_stt)
        if o_stt_idx >= 0:
            self.openai_stt_combo.setCurrentIndex(o_stt_idx)
            
        _set_combo(self.openai_llm_combo, self.config.get("openai_llm_model", "gpt-4o-mini"))
        
        self.anthropic_key_edit.setText(self.config.get("anthropic_api_key", ""))
        _set_combo(self.claude_llm_combo, self.config.get("claude_llm_model", "claude-5-sonnet"))
        _set_combo(self.codex_llm_combo, self.config.get("codex_model", ""))
        _set_combo(self.agy_llm_combo, self.config.get("agy_model", ""))

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
        aliases = self.config.get("vocabulary_aliases", {})
        self.aliases_edit.setPlainText("\n".join(f"{variant} => {spelling}" for variant, spelling in aliases.items()))
        self._update_whisper_budget_hint()

        self.sound_check.setChecked(self.config.get("sound_effects", True))
        self.restore_clip_check.setChecked(self.config.get("restore_clipboard", False))
        self.terminal_paste_check.setChecked(self.config.get("terminal_paste_mode", False))

        self.autostart_check.blockSignals(True)
        self.autostart_check.setChecked(is_autostart_enabled())
        self.autostart_check.blockSignals(False)

        self._update_desktop_status()
        self._on_provider_changed()

    def _save_settings(self) -> None:
        if not self.can_edit():
            QMessageBox.warning(self, "Kayıt Devam Ediyor", "Ayarları değiştirmeden önce kayıt ve işleme tamamlanmalıdır.")
            return
        try:
            aliases = parse_vocabulary_aliases(self.aliases_edit.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Yazım Eşleşmesi Geçersiz", str(error))
            return
        def _get_val(combo):
            data = combo.currentData()
            return data if data is not None else combo.currentText().strip()

        values = {
            "provider": self.provider_combo.currentData(),
            "gemini_api_key": self.gemini_key_edit.text().strip(),
            "gemini_model": self.gemini_model_combo.currentText().strip(),
            "groq_api_key": self.groq_key_edit.text().strip(),
            "groq_stt_model": self.groq_stt_combo.currentData(),
            "groq_llm_model": self.groq_llm_combo.currentData(),
            "openai_api_key": self.openai_key_edit.text().strip(),
            "openai_stt_model": self.openai_stt_combo.currentData(),
            "openai_llm_model": self.openai_llm_combo.currentText().strip(),
            "anthropic_api_key": self.anthropic_key_edit.text().strip(),
            "claude_llm_model": _get_val(self.claude_llm_combo),
            "codex_model": _get_val(self.codex_llm_combo),
            "agy_model": _get_val(self.agy_llm_combo),
            "language": self.language_combo.currentData(),
            "input_device_index": self.mic_combo.currentData(),
            "vad_mode": self.vad_combo.currentData(),
            "hotkey": self.hotkey_edit.get_hotkey(),
            "trigger_mode": self.trigger_mode_combo.currentData(),
            "custom_vocabulary": [v.strip() for v in self.vocab_edit.text().split(",") if v.strip()],
            "vocabulary_aliases": aliases,
            "sound_effects": self.sound_check.isChecked(),
            "restore_clipboard": self.restore_clip_check.isChecked(),
            "terminal_paste_mode": self.terminal_paste_check.isChecked(),
        }
        try:
            self.config.update(values)
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Kaydedilemedi", str(error))
            return
        self.config_updated.emit()
        if not set_autostart(self.autostart_check.isChecked()):
            QMessageBox.warning(self, "Başlangıç Ayarı", "Ayarlar kaydedildi, ancak otomatik başlatma değiştirilemedi.")
            self.autostart_check.setChecked(is_autostart_enabled())
            return

        # Görsel onay: pencereyi kapatmadan butonda "Kaydedildi" göster
        self.save_btn.setText("✓ Kaydedildi!")
        self.save_btn.setStyleSheet("background-color: #16a34a; color: #ffffff;")
        self._save_timer.start(1500)

    def _update_whisper_budget_hint(self) -> None:
        try:
            aliases = parse_vocabulary_aliases(self.aliases_edit.toPlainText())
        except ValueError:
            self.whisper_budget_label.setText("Yazım eşleşmesi biçimini düzeltin.")
            return
        vocab = [item.strip() for item in self.vocab_edit.text().split(",") if item.strip()]
        _, omitted = build_whisper_prompt(vocab, aliases)
        self.whisper_budget_label.setText(
            f"Ses tanıma ipucu sınırı: 224 UTF-8 byte; sığmayan {omitted} terim kayıtta korunur."
        )

    def _reset_save_btn(self) -> None:
        self.save_btn.setText("Kaydet")
        self.save_btn.setStyleSheet("")

    def _test_microphone(self) -> None:
        if not self.can_edit():
            QMessageBox.warning(self, "Kayıt Devam Ediyor", "Mikrofon testi için önce mevcut kaydı bitirin.")
            return
        import pyaudio, struct, math
        dev_idx = self.mic_combo.currentData()
        self.test_mic_btn.setEnabled(False)
        self.mic_status_lbl.setText("Dinleniyor... Lütfen mikrofona konuşun...")
        self.mic_status_lbl.setStyleSheet("color: #60a5fa; font-size: 11px; font-weight: bold;")
        self.repaint()

        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()
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
            if stream is not None:
                with suppress(Exception):
                    stream.close()
            if p is not None:
                with suppress(Exception):
                    p.terminate()
            self.test_mic_btn.setEnabled(True)

    def _test_injection(self) -> None:
        from ..injector import TextInjector
        injector = TextInjector(restore_clipboard=self.restore_clip_check.isChecked(),
                                terminal_paste_mode=self.terminal_paste_check.isChecked())
        test_text = "🎉 Kâtip başarıyla metin enjekte ediyor!"
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
                f"Metin eklenemedi: {injector.last_error}\n\n{help_text}"
            )
