"""
Dynamic Floating Pill Overlay for Katip.
Renders an animated, draggable, glassmorphic pill widget indicating recording, audio levels, and status.
"""

import math
import sys
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

MODE_TITLES = {
    "dictation": "DİKTE",
    "chat": "CHAT",
    "email": "E-POSTA",
    "prompt": "PROMPT",
    "bullets": "NOTLAR",
}

class FloatingPill(QWidget):
    """Modern floating pill widget inspired by Dynamic Island / Wispr Flow."""

    # Custom signal if user clicks the pill to toggle
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Platform-specific non-activating window flags
        if sys.platform.startswith("win"):
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        elif sys.platform == "darwin":
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.ToolTip
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
                | Qt.WindowType.BypassWindowManagerHint
            )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # On Windows: Apply native WS_EX_NOACTIVATE style so active window never loses focus
        if sys.platform.startswith("win"):
            try:
                import ctypes
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOPMOST = 0x00000008
                user32 = ctypes.windll.user32
                cur_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cur_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
            except Exception:
                pass

        # State management
        self.state = "hidden"  # "recording", "processing", "success", "error", "hidden"
        self.mode = "dictation"
        self.status_message = ""
        self.audio_level = 0.0
        self.current_heights = [0.2] * 5

        # Dragging support
        self._drag_pos = QPoint()
        self._is_dragging = False

        # Animation timer (60 FPS)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_tick)

        # Auto-hide timer for success/error
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_pill)

        self._tick_counter = 0
        self.resize(260, 52)
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        """Positions pill near the top-center of the primary screen."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + 60
            self.move(x, y)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def set_audio_level(self, level: float) -> None:
        self.audio_level = max(0.0, min(1.0, level))

    def _show_overlay(self) -> None:
        """Show the status pill without taking focus from the user's app."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        # On macOS, raise_() can activate the Qt tool window even with
        # WA_ShowWithoutActivating. WindowStaysOnTopHint keeps the pill visible
        # without explicitly raising it over the frontmost application.
        if sys.platform != "darwin":
            self.raise_()
        self.repaint()

    def show_recording(self, mode: str) -> None:
        self._anim_timer.start(16)
        self._hide_timer.stop()
        self.state = "recording"
        self.mode = mode
        self.status_message = "Dinleniyor..."
        self._show_overlay()

    def show_processing(self) -> None:
        self._anim_timer.start(16)
        self._hide_timer.stop()
        self.state = "processing"
        self.status_message = "İşleniyor..."
        self._show_overlay()

    def show_success(self, latency: float = 0.0) -> None:
        self._anim_timer.stop()
        self.state = "success"
        if latency > 0:
            self.status_message = f"Yapıştırıldı! ({latency}s)"
        else:
            self.status_message = "Yapıştırıldı!"
        self._show_overlay()
        self._hide_timer.start(1600)

    def show_error(self, message: str) -> None:
        self._anim_timer.stop()
        self.state = "error"
        self.status_message = message[:28] + ("..." if len(message) > 28 else "")
        self._show_overlay()
        self._hide_timer.start(3500)

    def hide_pill(self) -> None:
        self._anim_timer.stop()
        self.state = "hidden"
        self.hide()

    def _on_tick(self) -> None:
        self._tick_counter += 1

        if self.state == "recording":
            # Animate waveform bars according to audio level + organic jitter
            for i in range(5):
                jitter = math.sin(self._tick_counter * 0.2 + i * 1.3) * 0.15
                target = max(0.15, min(1.0, self.audio_level * 1.5 + jitter))
                self.current_heights[i] += (target - self.current_heights[i]) * 0.35
            self.update()
        elif self.state == "processing":
            self.update()

    # --- Mouse Drag Support ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.clicked.emit()
        event.accept()

    # --- Custom Drawing ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        radius = rect.height() / 2.0

        # Draw soft shadow inside widget bounds
        shadow_rect = QRectF(4, 6, self.width() - 8, self.height() - 8)
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(shadow_rect, radius, radius)
        painter.fillPath(shadow_path, QBrush(QColor(0, 0, 0, 90)))

        # Draw Background Capsule
        bg_path = QPainterPath()
        bg_path.addRoundedRect(rect, radius, radius)

        # Dark glass gradient
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor(24, 24, 28, 235))
        grad.setColorAt(1.0, QColor(14, 14, 18, 245))
        painter.fillPath(bg_path, QBrush(grad))

        # Glowing border based on state
        if self.state == "recording":
            border_color = QColor(239, 68, 68, 180)  # Red glow
        elif self.state == "processing":
            pulse = (math.sin(self._tick_counter * 0.15) + 1.0) / 2.0
            border_color = QColor(59, 130, 246, int(120 + pulse * 130))  # Pulsing Blue
        elif self.state == "success":
            border_color = QColor(16, 185, 129, 200)  # Emerald green
        elif self.state == "error":
            border_color = QColor(244, 63, 94, 200)  # Rose red
        else:
            border_color = QColor(255, 255, 255, 40)

        border_pen = QPen(border_color, 1.2)
        painter.strokePath(bg_path, border_pen)

        # Draw Mode Badge (Left side)
        mode_str = MODE_TITLES.get(self.mode, "DİKTE")
        badge_rect = QRectF(rect.x() + 10, rect.y() + (rect.height() - 20) / 2.0, 52, 20)
        badge_path = QPainterPath()
        badge_path.addRoundedRect(badge_rect, 10, 10)
        painter.fillPath(badge_path, QBrush(QColor(255, 255, 255, 22)))

        painter.setPen(QColor(200, 200, 210))
        badge_font = QFont("Sans-Serif", 7, QFont.Weight.Bold)
        painter.setFont(badge_font)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, mode_str)

        # State Specific Indicators
        if self.state == "recording":
            # Pulsing recording dot
            dot_pulse = (math.sin(self._tick_counter * 0.25) + 1.0) / 2.0
            dot_color = QColor(239, 68, 68, int(180 + dot_pulse * 75))
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.PenStyle.NoPen)
            dot_y = rect.y() + rect.height() / 2.0
            painter.drawEllipse(QPoint(int(rect.x() + 74), int(dot_y)), 4, 4)

            # 5-Bar Dynamic Audio Waveform
            wave_x = rect.x() + 88
            max_bar_h = 20.0
            bar_w = 3.0
            spacing = 3.0
            painter.setBrush(QBrush(QColor(248, 113, 113)))
            for i in range(5):
                h = max(4.0, self.current_heights[i] * max_bar_h)
                bx = wave_x + i * (bar_w + spacing)
                by = dot_y - h / 2.0
                bar_path = QPainterPath()
                bar_path.addRoundedRect(QRectF(bx, by, bar_w, h), 1.5, 1.5)
                painter.fillPath(bar_path, QBrush(QColor(248, 113, 113)))

            # Status text
            painter.setPen(QColor(240, 240, 245))
            text_font = QFont("Sans-Serif", 9, QFont.Weight.Medium)
            painter.setFont(text_font)
            text_rect = QRectF(rect.x() + 125, rect.y(), rect.width() - 130, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.status_message)

        elif self.state == "processing":
            # Animated spinning arc
            arc_rect = QRectF(rect.x() + 74, rect.y() + (rect.height() - 16) / 2.0, 16, 16)
            arc_angle = int((self._tick_counter * 14) % 360)
            spin_pen = QPen(QColor(96, 165, 250), 2.2)
            spin_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(spin_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_rect, arc_angle * 16, 100 * 16)

            painter.setPen(QColor(220, 230, 255))
            text_font = QFont("Sans-Serif", 9, QFont.Weight.Medium)
            painter.setFont(text_font)
            text_rect = QRectF(rect.x() + 102, rect.y(), rect.width() - 108, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.status_message)

        elif self.state == "success":
            # Green check circle
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(16, 185, 129)))
            center_pt = QPoint(int(rect.x() + 80), int(rect.y() + rect.height() / 2.0))
            painter.drawEllipse(center_pt, 7, 7)

            painter.setPen(QPen(QColor(255, 255, 255), 1.6))
            painter.drawLine(center_pt.x() - 3, center_pt.y(), center_pt.x() - 1, center_pt.y() + 2)
            painter.drawLine(center_pt.x() - 1, center_pt.y() + 2, center_pt.x() + 3, center_pt.y() - 2)

            painter.setPen(QColor(167, 243, 208))
            text_font = QFont("Sans-Serif", 9, QFont.Weight.Bold)
            painter.setFont(text_font)
            text_rect = QRectF(rect.x() + 98, rect.y(), rect.width() - 104, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.status_message)

        elif self.state == "error":
            # Warning triangle / icon
            painter.setPen(QColor(253, 164, 175))
            text_font = QFont("Sans-Serif", 8, QFont.Weight.Medium)
            painter.setFont(text_font)
            text_rect = QRectF(rect.x() + 72, rect.y(), rect.width() - 76, rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"⚠️ {self.status_message}")
