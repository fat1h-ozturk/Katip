import tempfile
from pathlib import Path
from katip.config import ConfigManager
import json
import pytest
from katip.config import DEFAULT_GEMINI_MODEL, normalize_vocabulary_aliases

def test_config_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "config.json"
        mgr = ConfigManager(config_file=cfg_path)
        assert mgr.get("provider") == "gemini"
        assert mgr.get("mode") == "dictation"
        assert "Kâtip" in mgr.get("custom_vocabulary")
        assert mgr.get("vocabulary_aliases") == {}

def test_config_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "config.json"
        mgr = ConfigManager(config_file=cfg_path)
        mgr.set("mode", "email")
        mgr.set("gemini_api_key", "test_key_123")

        # Reload from same file
        mgr2 = ConfigManager(config_file=cfg_path)
        assert mgr2.get("mode") == "email"
        assert mgr2.get("gemini_api_key") == "test_key_123"


@pytest.mark.parametrize("operation", ["dump", "replace"])
def test_failed_save_keeps_file_and_memory(tmp_path, monkeypatch, operation):
    import katip.config as config_module
    path = tmp_path / "config.json"
    mgr = ConfigManager(path)
    mgr.set("mode", "email")
    original = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("simulated full disk")

    monkeypatch.setattr(config_module.json if operation == "dump" else config_module.os, operation, fail)
    with pytest.raises(RuntimeError, match="önceki ayar dosyası korundu"):
        mgr.update({"mode": "chat", "gemini_api_key": "new-key"})
    assert path.read_bytes() == original
    assert mgr.get("mode") == "email"
    assert not list(tmp_path.glob(".config-*.tmp"))


def test_settings_batch_writes_once(tmp_path, monkeypatch):
    import katip.config as config_module
    mgr = ConfigManager(tmp_path / "config.json")
    original_replace = config_module.os.replace
    calls = []

    def replace(*args):
        calls.append(args)
        original_replace(*args)

    monkeypatch.setattr(config_module.os, "replace", replace)
    mgr.update({"mode": "chat", "gemini_api_key": "new-key", "sound_effects": False})
    assert len(calls) == 1
    assert ConfigManager(mgr.config_file).get("mode") == "chat"


def test_retired_models_migrate_without_losing_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"gemini_model": "gemini-2.0-flash", "gemini_api_key": "keep-me"}))
    mgr = ConfigManager(path)
    assert mgr.get("gemini_model") == DEFAULT_GEMINI_MODEL
    assert mgr.get("gemini_api_key") == "keep-me"
    mgr.save()
    assert json.loads(path.read_text())["gemini_model"] == DEFAULT_GEMINI_MODEL


@pytest.mark.parametrize("values", [{"vad_mode": 99}, {"provider": "unknown"},
                                     {"sound_effects": "yes"}, {"custom_vocabulary": [1]},
                                     {"gemini_model": "bad?key=oops"}])
def test_invalid_updates_do_not_change_state(tmp_path, values):
    mgr = ConfigManager(tmp_path / "config.json")
    before = dict(mgr.data)
    with pytest.raises(ValueError):
        mgr.update(values)
    assert mgr.data == before
    assert not mgr.config_file.exists()


def test_invalid_saved_fields_fall_back_individually(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"vad_mode": "bad", "mode": "email", "pill_x": 42}))
    mgr = ConfigManager(path)
    assert mgr.get("vad_mode") == 2
    assert mgr.get("mode") == "email"
    assert "pill_x" not in mgr.data


def test_aliases_normalize_and_round_trip_without_touching_old_vocab(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"custom_vocabulary": ["Eski"], "mode": "chat"}), encoding="utf-8")
    mgr = ConfigManager(path)
    assert mgr.get("vocabulary_aliases") == {}
    mgr.update({"vocabulary_aliases": {"  kafe  ": " Cafe\u0301 ", "paysayd altı": "PySide6"}})
    reloaded = ConfigManager(path)
    assert reloaded.get("vocabulary_aliases") == {"kafe": "Café", "paysayd altı": "PySide6"}
    assert reloaded.get("custom_vocabulary") == ["Eski"]
    assert reloaded.get("mode") == "chat"


@pytest.mark.parametrize("aliases", [
    {"a": ""}, {"a\n": "b"}, {"a": "b" * 201},
    {str(i): "x" for i in range(101)},
    {"e\u0301": "bir", "é": "iki"}, {"a=>b": "c"},
])
def test_invalid_aliases_rejected_before_save(tmp_path, aliases):
    mgr = ConfigManager(tmp_path / "config.json")
    with pytest.raises(ValueError):
        mgr.update({"vocabulary_aliases": aliases})
    assert mgr.get("vocabulary_aliases") == {}
    assert not mgr.config_file.exists()


def test_same_normalized_alias_merges_if_target_agrees():
    assert normalize_vocabulary_aliases({"e\u0301": " Café ", "é": "Cafe\u0301"}) == {"é": "Café"}
