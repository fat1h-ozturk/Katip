"""Settings persistence must report real outcomes without desktop side effects."""
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from katip.config import ConfigManager
from katip.ui import settings as settings_module

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "get_input_devices", lambda: [])
    monkeypatch.setattr(settings_module, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(settings_module, "is_desktop_installed", lambda: False)
    monkeypatch.setattr(settings_module, "set_autostart", Mock(return_value=True))
    monkeypatch.setattr(settings_module.QMessageBox, "warning", Mock())
    widget = settings_module.SettingsDialog(ConfigManager(tmp_path / "config.json"))
    yield widget
    widget.close()
    delete(widget)


def test_save_persists_form_once_and_emits_after_success(dialog):
    dialog.config.update = Mock(wraps=dialog.config.update)
    updated = []
    dialog.config_updated.connect(lambda: updated.append(True))
    dialog.gemini_key_edit.setText("new-key")
    dialog.restore_clip_check.setChecked(True)
    dialog._save_settings()
    dialog.config.update.assert_called_once()
    assert dialog.config.get("gemini_api_key") == "new-key"
    assert dialog.config.get("restore_clipboard") is True
    assert updated == [True]
    assert "Kaydedildi" in dialog.save_btn.text()


def test_failed_save_does_not_emit_or_report_success(dialog, monkeypatch):
    updated = []
    dialog.config_updated.connect(lambda: updated.append(True))
    monkeypatch.setattr(dialog.config, "update", Mock(side_effect=RuntimeError("Disk failure")))
    dialog._save_settings()
    assert not updated
    assert dialog.save_btn.text() == "Kaydet"
    settings_module.QMessageBox.warning.assert_called_once()
    settings_module.set_autostart.assert_not_called()


def test_busy_recording_cannot_save_or_change_autostart(dialog):
    dialog.can_edit = lambda: False
    dialog.config.update = Mock()
    dialog.autostart_check.setChecked(True)
    settings_module.set_autostart.assert_not_called()
    dialog._save_settings()
    dialog.config.update.assert_not_called()
    settings_module.set_autostart.assert_not_called()


def test_autostart_failure_is_reported_without_false_save_banner(dialog):
    settings_module.set_autostart.return_value = False
    dialog.autostart_check.setChecked(True)
    dialog._save_settings()
    settings_module.QMessageBox.warning.assert_called_once()
    assert not dialog.autostart_check.isChecked()
    assert dialog.save_btn.text() == "Kaydet"


def test_alias_form_round_trip_and_budget_hint(dialog):
    dialog.vocab_edit.setText("Eski, " + "ü" * 110)
    dialog.aliases_edit.setPlainText("paysayd altı => PySide6\nkafe => Café")
    assert "sığmayan 1 terim" in dialog.whisper_budget_label.text()
    dialog._save_settings()
    assert dialog.config.get("vocabulary_aliases") == {"paysayd altı": "PySide6", "kafe": "Café"}
    reopened = settings_module.SettingsDialog(ConfigManager(dialog.config.config_file))
    try:
        assert reopened.aliases_edit.toPlainText() == "paysayd altı => PySide6\nkafe => Café"
    finally:
        reopened.close()
        delete(reopened)


def test_conflicting_alias_lines_do_not_overwrite_or_save(dialog):
    dialog.config.update = Mock()
    dialog.aliases_edit.setPlainText("cafe\u0301 => Café\ncafé => Cafe")
    dialog._save_settings()
    dialog.config.update.assert_not_called()
    assert "farklı yazımlara" in settings_module.QMessageBox.warning.call_args.args[2]


def test_selected_microphone_is_saved_with_its_name(dialog):
    dialog.config.update({"input_device_index": 3, "input_device_name": "USB Headset"})
    # Before the scan finishes the placeholder row must not overwrite the saved name.
    dialog._devices_loaded = False
    dialog.mic_combo.addItem("Seçili mikrofon (aygıtlar yükleniyor)", 3)
    dialog.mic_combo.setCurrentIndex(dialog.mic_combo.findData(3))
    assert dialog._selected_device_name() == "USB Headset"
    dialog._populate_devices([{"index": 2, "name": "Built-in"}, {"index": 3, "name": "USB Headset 2"}])
    dialog.mic_combo.setCurrentIndex(dialog.mic_combo.findData(3))
    dialog._save_settings()
    assert dialog.config.get("input_device_name") == "USB Headset 2"
    dialog.mic_combo.setCurrentIndex(dialog.mic_combo.findData(-1))
    assert dialog._selected_device_name() == ""
