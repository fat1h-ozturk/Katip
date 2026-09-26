import tempfile
from pathlib import Path
from katip.config import ConfigManager

def test_config_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "config.json"
        mgr = ConfigManager(config_file=cfg_path)
        assert mgr.get("provider") == "gemini"
        assert mgr.get("mode") == "dictation"
        assert "Katip" in mgr.get("custom_vocabulary")

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
