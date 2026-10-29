"""Credential-store failures must not block unrelated settings or lose persisted keys."""
import json
import threading
import time
from unittest.mock import Mock

import pytest

from katip.config import ConfigManager
from katip.infrastructure.secrets import SecretStore

REF = "a" * 32


class FakeStore:
    def __init__(self, locked=False):
        self.values = {}
        self.locked = locked

    def get(self, ref):
        if self.locked:
            raise RuntimeError("dbus: org.freedesktop.Secret locked SECRET-DETAIL")
        return self.values.get(ref)

    def put(self, ref, value):
        if self.locked:
            raise RuntimeError("dbus: org.freedesktop.Secret locked SECRET-DETAIL")
        self.values[ref] = value

    def delete(self, ref):
        self.values.pop(ref, None)
        return True


def _write(path, body):
    path.write_text(json.dumps(body), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_env_keys(monkeypatch):
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_upgrade_with_unavailable_vault_keeps_legacy_key_and_saves_other_settings(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"groq_api_key": "legacy", "provider": "groq"})
    store = FakeStore(locked=True)
    config = ConfigManager(path, secret_store=store)
    config.set("mode", "email")
    saved = _read(path)
    assert saved["mode"] == "email"
    assert saved["groq_api_key"] == "legacy" and saved["secret_refs"] == {}
    assert config.get("groq_api_key") == "legacy"

    with pytest.raises(RuntimeError) as error:
        config.set("groq_api_key", "new")
    assert "anahtar kasası kullanılamıyor" in str(error.value)
    assert "SECRET-DETAIL" not in str(error.value)
    assert _read(path)["groq_api_key"] == "legacy"
    assert config.get("groq_api_key") == "legacy"

    # Migration happens on a later save once the vault works.
    store.locked = False
    config.set("mode", "chat")
    assert "legacy" not in path.read_text(encoding="utf-8")
    assert ConfigManager(path, secret_store=store).get("groq_api_key") == "legacy"
    assert config.secret_error == ""


def test_unavailable_vault_keeps_existing_ref_exactly(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"secret_refs": {"groq_api_key": REF}, "groq_api_key": ""})
    store = FakeStore()
    store.values[REF] = "stored"
    config = ConfigManager(path, secret_store=store)
    store.locked = True
    config.set("vad_mode", 3)
    saved = _read(path)
    assert saved["secret_refs"] == {"groq_api_key": REF}
    assert saved["groq_api_key"] == "" and saved["vad_mode"] == 3
    assert config.secret_error


def test_vault_locked_at_startup_then_unlocked_in_same_session(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"secret_refs": {"groq_api_key": REF}})
    store = FakeStore(locked=True)
    store.values[REF] = "stored"
    config = ConfigManager(path, secret_store=store)
    assert config.secret_error and config.get("groq_api_key") == ""

    # The form echoes the unresolved (empty) key back; that is not a request to clear it.
    config.update({"mode": "email", "groq_api_key": ""})
    assert _read(path)["secret_refs"] == {"groq_api_key": REF}

    store.locked = False
    config.update({"mode": "chat", "groq_api_key": ""})
    assert config.secret_error == ""
    assert config.get("groq_api_key") == "stored"
    assert _read(path)["secret_refs"] == {"groq_api_key": REF}

    config.set("groq_api_key", "")
    assert _read(path)["secret_refs"] == {}
    assert config.get("groq_api_key") == ""


def test_missing_vault_entry_does_not_block_unrelated_saves(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"secret_refs": {"openai_api_key": REF}})
    store = FakeStore()
    config = ConfigManager(path, secret_store=store)
    assert config.secret_error
    config.set("language", "tr")
    saved = _read(path)
    assert saved["language"] == "tr"
    assert saved["secret_refs"] == {"openai_api_key": REF}
    assert config.secret_error

    config.set("openai_api_key", "replacement")
    reference = _read(path)["secret_refs"]["openai_api_key"]
    assert reference != REF and store.values[reference] == "replacement"
    assert config.secret_error == ""


def test_environment_key_is_not_refused_or_written_when_vault_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    path = tmp_path / "config.json"
    config = ConfigManager(path, secret_store=FakeStore(locked=True))
    config.update({"mode": "email", "groq_api_key": "from-env"})
    assert "from-env" not in path.read_text(encoding="utf-8")


def test_secret_store_service_name_is_stable_across_config_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("KATIP_PROFILE", raising=False)
    first = SecretStore(tmp_path / "home" / "config.json")
    second = SecretStore(tmp_path / "relocated" / "config.json")
    assert first.service == second.service == "katip:katip"
    monkeypatch.setenv("KATIP_PROFILE", "candidate")
    assert SecretStore(tmp_path / "config.json").service == "katip:katip-candidate"


def test_secret_store_reads_and_purges_legacy_path_hash_entries(tmp_path, monkeypatch):
    class Backend:
        __module__ = "keyring.backends.SecretService"
        def __init__(self): self.values = {}
        def set_password(self, service, reference, value): self.values[(service, reference)] = value
        def get_password(self, service, reference): return self.values.get((service, reference))
        def delete_password(self, service, reference): self.values.pop((service, reference), None)
    backend = Backend()
    monkeypatch.setattr("keyring.get_keyring", lambda: backend)
    store = SecretStore(tmp_path / "config.json")
    backend.values[(store.legacy_service, "old")] = "candidate-key"
    assert store.legacy_service != store.service
    assert store.get("old") == "candidate-key"
    store.put("new", "value")
    assert (store.service, "new") in backend.values
    assert store.delete("old") and not backend.values.get((store.legacy_service, "old"))


def test_settings_dialog_shows_actionable_vault_error(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete
    from katip.ui import settings as settings_module
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_module, "get_input_devices", lambda: [])
    monkeypatch.setattr(settings_module, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(settings_module, "is_desktop_installed", lambda: False)
    monkeypatch.setattr(settings_module, "set_autostart", Mock(return_value=True))
    warning = Mock()
    monkeypatch.setattr(settings_module.QMessageBox, "warning", warning)
    config = ConfigManager(tmp_path / "config.json", secret_store=FakeStore(locked=True))
    dialog = settings_module.SettingsDialog(config)
    try:
        dialog.gemini_key_edit.setText("typed-key")
        dialog._save_settings()
        assert "anahtar kasası kullanılamıyor" in warning.call_args.args[2]
    finally:
        dialog.close()
        delete(dialog)


def test_mic_test_waits_for_device_scan(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete
    from katip.ui import settings as settings_module
    app = QApplication.instance() or QApplication([])
    release = threading.Event()
    monkeypatch.setattr(settings_module, "get_input_devices", lambda: release.wait(5) and [])
    monkeypatch.setattr(settings_module, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(settings_module, "is_desktop_installed", lambda: False)
    dialog = settings_module.SettingsDialog(ConfigManager(tmp_path / "config.json"))
    try:
        assert not dialog.test_mic_btn.isEnabled()
        release.set()
        deadline = time.monotonic() + 5
        while not dialog.test_mic_btn.isEnabled() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert dialog.test_mic_btn.isEnabled()
    finally:
        dialog.close()
        delete(dialog)
