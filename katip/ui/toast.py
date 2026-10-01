"""
Floating Toast Notification for Updates in Katip.
Renders a modern, non-intrusive notification in the top-right corner of the screen.
"""

import sys
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from ..desktop import open_url


class UpdateNotificationToast(QWidget):
    """Modern, top-right floating notification for app updates."""

    def __init__(self, new_version: str, release_url: str, parent=None):
        super().__init__(parent)
        self.release_url = release_url
        self.new_version = new_version

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setStyleSheet("""
            QWidget#toastCard {
                background-color: #09090b;
                border: 1px solid #3f3f46;
                border-radius: 4px;
            }
            QLabel#toastTitle {
                color: #fafafa;
                font-size: 13px;
                font-weight: 700;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
            }
            QLabel#toastBody {
                color: #a1a1aa;
                font-size: 12px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
            }
            QPushButton#actionBtn {
                background-color: #fafafa;
                color: #09090b;
                border: none;
                border-radius: 2px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
            }
            QPushButton#actionBtn:hover {
                background-color: #e4e4e7;
            }
            QPushButton#closeBtn {
                background: transparent;
                color: #71717a;
                border: none;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 6px;
            }
            QPushButton#closeBtn:hover {
                color: #fafafa;
            }
        """)

        # Main Layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("toastCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)

        # Top row: Title + Close Button
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        title_lbl = QLabel(f"⚡ Yeni Güncelleme: {new_version}")
        title_lbl.setObjectName("toastTitle")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)
        card_layout.addLayout(header_layout)

        # Body row
        if sys.platform.startswith("linux"):
            body_text = "Güncellemek için yeni .rpm paketini kurun."
        elif sys.platform == "darwin":
            body_text = "Güncellemek için yeni .dmg paketini kurun."
        else:
            body_text = "Güncellemek için yeni .exe dosyasını kurun."

        body_lbl = QLabel(body_text)
        body_lbl.setObjectName("toastBody")
        body_lbl.setWordWrap(True)
        card_layout.addWidget(body_lbl)

        # Action row
        action_layout = QHBoxLayout()
        action_layout.addStretch()

        download_btn = QPushButton("İndir / İncele")
        download_btn.setObjectName("actionBtn")
        download_btn.clicked.connect(self._on_download_clicked)
        action_layout.addWidget(download_btn)

        card_layout.addLayout(action_layout)
        root_layout.addWidget(card)

        # Position at top-right of primary screen
        self._reposition()

        # Auto-dismiss after 20 seconds
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.close)
        self._auto_close_timer.start(20000)

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            width = 320
            self.setFixedWidth(width)
            self.adjustSize()
            x = geo.right() - width - 24
            y = geo.top() + 24
            self.move(x, y)

    def _on_download_clicked(self) -> None:
        if self.release_url:
            open_url(self.release_url)
        self.close()
