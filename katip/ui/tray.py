"""
System Tray Icon and context menu for Katip.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

class TrayIcon(QSystemTrayIcon):
    """System tray icon with quick actions and mode switcher."""

    mode_changed = Signal(str)
    toggle_requested = Signal()
    settings_requested = Signal()
    result_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_mode = "dictation"
        self.is_recording = False

        self._create_icons()
        self._build_menu()

        self.setIcon(self.icon_idle)
        self.setToolTip("Kâtip (Hazır)")
        self.activated.connect(self._on_activated)

    def _create_icons(self) -> None:
        """Procedurally draws high-DPI tray icons."""
        # 1. Idle Icon (Violet mic/circle)
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer ring
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(99, 102, 241)))  # Indigo
        painter.drawRoundedRect(8, 8, 48, 48, 14, 14)

        # Microphone capsule
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRoundedRect(25, 18, 14, 20, 7, 7)

        # Microphone stand base
        painter.drawRect(29, 41, 6, 6)
        painter.drawRect(23, 47, 18, 3)
        painter.end()
        self.icon_idle = QIcon(pix)

        # 2. Recording Icon (Red pulsating dot)
        pix_rec = QPixmap(64, 64)
        pix_rec.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix_rec)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(239, 68, 68)))  # Red
        painter.drawEllipse(10, 10, 44, 44)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(22, 22, 20, 20)
        painter.end()
        self.icon_recording = QIcon(pix_rec)

    def _build_menu(self) -> None:
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #09090b;
                color: #f4f4f5;
                border: 1px solid #27272a;
                border-radius: 2px;
                padding: 4px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 2px;
            }
            QMenu::item:selected {
                background-color: #3f3f46;
            }
            QMenu::separator {
                height: 1px;
                background: #27272a;
                margin: 4px 8px;
            }
        """)

        # Status header
        self.status_action = QAction("Kâtip: Hazır", self)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        # Toggle action
        self.toggle_action = QAction("🎙️ Kaydı Başlat / Durdur", self)
        self.toggle_action.triggered.connect(self.toggle_requested.emit)
        self.menu.addAction(self.toggle_action)

        self.menu.addSeparator()

        # Modes submenu
        modes_menu = self.menu.addMenu("🎯 Yazma Modu")
        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)

        mode_definitions = [
            ("dictation", "✍️ Doğal Dikte"),
            ("chat", "💬 Hızlı Mesajlaşma (Chat)"),
            ("email", "✉️ Resmi E-Posta"),
            ("prompt", "🤖 AI Prompt Oluşturucu"),
            ("bullets", "📝 Madde İmleri (Notlar)"),
        ]

        self.mode_actions = {}
        for mode_key, mode_title in mode_definitions:
            act = QAction(mode_title, self, checkable=True)
            if mode_key == self.current_mode:
                act.setChecked(True)
            act.triggered.connect(lambda checked=False, m=mode_key: self._on_mode_selected(m))
            self.mode_group.addAction(act)
            modes_menu.addAction(act)
            self.mode_actions[mode_key] = act

        self.menu.addSeparator()

        # Settings action
        self.settings_action = QAction("⚙️ Ayarlar...", self)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(self.settings_action)

        result_action = QAction("Son Sonuç / Kaydı Kurtar...", self)
        result_action.triggered.connect(self.result_requested.emit)
        self.menu.addAction(result_action)

        # Quit action
        self.quit_action = QAction("❌ Çıkış", self)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.quit_action)

        self.setContextMenu(self.menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            # Left-click opens settings
            self.settings_requested.emit()

    def _on_mode_selected(self, mode: str) -> None:
        self.current_mode = mode
        self.mode_changed.emit(mode)

    def set_recording(self, recording: bool) -> None:
        self.is_recording = recording
        if recording:
            self.setIcon(self.icon_recording)
            self.setToolTip("Kâtip (Kayıt Yapılıyor...)")
            self.status_action.setText("Durum: Dinleniyor...")
            self.toggle_action.setText("⏹️ Kaydı Durdur")
        else:
            self.setIcon(self.icon_idle)
            self.setToolTip("Kâtip (Hazır)")
            self.status_action.setText("Kâtip: Hazır")
            self.toggle_action.setText("🎙️ Kaydı Başlat / Durdur")

    def set_active_mode(self, mode: str) -> None:
        self.current_mode = mode
        if mode in self.mode_actions:
            self.mode_actions[mode].setChecked(True)
