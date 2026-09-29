"""
HotkeyRecorderWidget — klavyeden tuş yakalayarak kısayol atama widget'ı.
QLineEdit tabanlı, basılan tuş kombinasyonunu "Ctrl+Alt+Space" formatında döndürür.
evdev ve pynput hotkey parser'larıyla %100 uyumlu çıktı üretir.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QLineEdit


# Qt.Key → insan-okunur string haritası (config formatıyla uyumlu)
_MODIFIER_MAP = {
    Qt.Key.Key_Control: "Ctrl",
    Qt.Key.Key_Alt: "Alt",
    getattr(Qt.Key, "Key_AltGr", Qt.Key.Key_Alt): "Alt",
    Qt.Key.Key_Shift: "Shift",
    Qt.Key.Key_Meta: "Super",
    Qt.Key.Key_Super_L: "Super",
    Qt.Key.Key_Super_R: "Super",
}

_MODIFIER_ORDER = {"Ctrl": 0, "Alt": 1, "Shift": 2, "Super": 3}

_SPECIAL_KEY_MAP = {
    Qt.Key.Key_Space: "Space",
    Qt.Key.Key_Return: "Return",
    Qt.Key.Key_Enter: "Enter",
    Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_CapsLock: "CapsLock",
    Qt.Key.Key_Pause: "Pause",
    Qt.Key.Key_ScrollLock: "ScrollLock",
    Qt.Key.Key_Print: "PrintScreen",
    Qt.Key.Key_Insert: "Insert",
    Qt.Key.Key_Home: "Home",
    Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "PageUp",
    Qt.Key.Key_PageDown: "PageDown",
    Qt.Key.Key_Up: "Up",
    Qt.Key.Key_Down: "Down",
    Qt.Key.Key_Left: "Left",
    Qt.Key.Key_Right: "Right",
}

# F1-F24 tuşları
for _i in range(1, 25):
    _key = getattr(Qt.Key, f"Key_F{_i}", None)
    if _key:
        _SPECIAL_KEY_MAP[_key] = f"F{_i}"

class HotkeyRecorderWidget(QLineEdit):
    """
    Kullanıcı bu widget'a tıkladığında kayıt moduna girer.
    Basılan tuş kombinasyonunu yakalar ve "Ctrl+Alt+Space" formatında gösterir.

    Signals:
        hotkey_changed(str): Yeni kısayol kaydedildiğinde yayınlanır.
    """

    hotkey_changed = Signal(str)

    _IDLE_STYLE = ""
    _RECORDING_STYLE = "border: 2px solid #f59e0b; background-color: #1c1917;"
    _CAPTURED_STYLE = "border: 2px solid #4ade80; background-color: #1c1917;"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Tıklayıp bir kısayol tuşuna basın")
        self._recording = False
        self._current_hotkey = ""
        self._held_modifiers: list[str] = []
        self._max_held_modifiers: set[str] = set()

    def _finish_capture(self, hotkey_str: str) -> None:
        """Kısayol yakalamayı tamamlar, stili günceller ve sinyal yayar."""
        self._current_hotkey = hotkey_str
        self.setText(hotkey_str)
        self.setStyleSheet(self._CAPTURED_STYLE)
        self._recording = False
        self._held_modifiers = []
        self._max_held_modifiers = set()
        self.hotkey_changed.emit(hotkey_str)

        # Kısa bir süre sonra normal stile dön ve fokus bırak
        QTimer.singleShot(600, lambda: self.setStyleSheet(self._IDLE_STYLE))
        QTimer.singleShot(700, self.clearFocus)

    def set_hotkey(self, hotkey_str: str) -> None:
        """Mevcut kısayolu ayarlar (config'den yükleme için)."""
        self._current_hotkey = hotkey_str
        self.setText(hotkey_str)
        self.setStyleSheet(self._IDLE_STYLE)

    def get_hotkey(self) -> str:
        """Geçerli kısayol string'ini döndürür."""
        return self._current_hotkey

    def focusInEvent(self, event):
        """Widget fokus aldığında kayıt moduna geç."""
        super().focusInEvent(event)
        self._start_recording()

    def focusOutEvent(self, event):
        """Fokus kaybedildiğinde kayıt modundan çık."""
        super().focusOutEvent(event)
        if self._recording:
            self._stop_recording(cancel=True)

    def keyPressEvent(self, event: QKeyEvent):
        """Tuş basımlarını yakala — QLineEdit'e karakter yazılmasını engelle."""
        if not self._recording:
            return

        key = event.key()

        # Esc → iptal
        if key == Qt.Key.Key_Escape:
            self._stop_recording(cancel=True)
            self.clearFocus()
            return

        # Backspace/Delete → kısayolu temizle
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._current_hotkey = ""
            self.setText("")
            self.setPlaceholderText("Kısayol atanmadı")
            self._stop_recording(cancel=False)
            self.hotkey_changed.emit("")
            return

        # Modifier tuşu mu?
        if key in _MODIFIER_MAP:
            mod_name = _MODIFIER_MAP[key]
            if mod_name not in self._held_modifiers:
                self._held_modifiers.append(mod_name)
            self._max_held_modifiers.add(mod_name)
            qt_mods = event.modifiers()
            if qt_mods & Qt.KeyboardModifier.ControlModifier:
                self._max_held_modifiers.add("Ctrl")
            if qt_mods & Qt.KeyboardModifier.AltModifier:
                self._max_held_modifiers.add("Alt")
            if qt_mods & Qt.KeyboardModifier.ShiftModifier:
                self._max_held_modifiers.add("Shift")
            if qt_mods & Qt.KeyboardModifier.MetaModifier:
                self._max_held_modifiers.add("Super")
            self._update_display()
            return

        # Normal tuş — kısayolu tamamla
        key_name = _SPECIAL_KEY_MAP.get(key)
        if key_name is None:
            # 0x20 - 0x7E arasındaki standart ASCII karakterler (A-Z, 0-9, semboller)
            if 0x20 <= key <= 0x7E:
                key_name = chr(key).upper()
            else:
                seq = QKeySequence(key).toString().upper()
                if seq:
                    key_name = seq
                else:
                    return  # Tanımsız tuş, yoksay

        # Aktif modifier'ları topla (hem basılı tutulanlardan hem event.modifiers()'dan)
        active_modifiers = set(self._held_modifiers) | self._max_held_modifiers
        qt_mods = event.modifiers()
        if qt_mods & Qt.KeyboardModifier.ControlModifier:
            active_modifiers.add("Ctrl")
        if qt_mods & Qt.KeyboardModifier.AltModifier:
            active_modifiers.add("Alt")
        if qt_mods & Qt.KeyboardModifier.ShiftModifier:
            active_modifiers.add("Shift")
        if qt_mods & Qt.KeyboardModifier.MetaModifier:
            active_modifiers.add("Super")

        # Kombinasyonu oluştur (canonical modifier sıralaması: Ctrl -> Alt -> Shift -> Super)
        sorted_modifiers = sorted(active_modifiers, key=lambda m: _MODIFIER_ORDER.get(m, 99))
        parts = sorted_modifiers + [key_name]
        hotkey_str = "+".join(parts)
        self._finish_capture(hotkey_str)

    def keyReleaseEvent(self, event: QKeyEvent):
        """Modifier bırakıldığında kontrol et: 2+ modifier basılıp bırakıldıysa kombinasyonu ata."""
        if not self._recording:
            return

        key = event.key()
        if key in _MODIFIER_MAP:
            # En az 2 modifier birlikte basılıp bırakıldıysa (örn: Ctrl+Shift, Ctrl+Alt),
            # bunu tek başına geçerli bir kısayol olarak ata!
            if len(self._max_held_modifiers) >= 2:
                sorted_modifiers = sorted(self._max_held_modifiers, key=lambda m: _MODIFIER_ORDER.get(m, 99))
                hotkey_str = "+".join(sorted_modifiers)
                self._finish_capture(hotkey_str)
                return

            mod_name = _MODIFIER_MAP[key]
            if mod_name in self._held_modifiers:
                self._held_modifiers.remove(mod_name)
            if not self._held_modifiers:
                self._max_held_modifiers.clear()
            self._update_display()

    def _start_recording(self):
        self._recording = True
        self._held_modifiers = []
        self._max_held_modifiers = set()
        self.setText("🎹 Bir tuş kombinasyonuna basın...")
        self.setStyleSheet(self._RECORDING_STYLE)

    def _stop_recording(self, cancel: bool = False):
        self._recording = False
        self._held_modifiers = []
        self._max_held_modifiers = set()
        if cancel:
            self.setText(self._current_hotkey or "")
        self.setStyleSheet(self._IDLE_STYLE)

    def _update_display(self):
        """Kayıt sırasında basılı tutulan modifier'ları göster."""
        if self._held_modifiers:
            sorted_modifiers = sorted(self._held_modifiers, key=lambda m: _MODIFIER_ORDER.get(m, 99))
            self.setText("+".join(sorted_modifiers) + "+...")
        else:
            self.setText("🎹 Bir tuş kombinasyonuna basın...")
