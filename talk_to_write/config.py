import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

def get_config_dir() -> Path:
    """Returns standard config directory based on host OS."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "talk-to-write"
        return Path.home() / "AppData" / "Roaming" / "talk-to-write"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "talk-to-write"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "talk-to-write"
        return Path.home() / ".config" / "talk-to-write"

CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": "gemini",  # "gemini" or "groq"
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "gemini_model": "gemini-2.0-flash",
    "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
    "groq_stt_model": "whisper-large-v3-turbo",
    "groq_llm_model": "qwen/qwen3.8-27b",
    "mode": "dictation",  # "dictation", "chat", "email", "prompt", "bullets"
    "hotkey": "Ctrl+Alt+Space",
    "trigger_mode": "toggle",  # "toggle" or "push_to_talk"
    "custom_vocabulary": ["TalkToWrite", "Gemini", "PySide6", "Wayland"],
    "sound_effects": True,
    "language": "auto",  # "auto", "tr", "en"
    "restore_clipboard": False,
    "input_device_index": -1,
    "pill_x": -1,
    "pill_y": -1,
}

class ConfigManager:
    """Manages loading, saving, and accessing application configuration."""

    def __init__(self, config_file: Path = CONFIG_FILE):
        self.config_file = config_file
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        """Loads configuration from JSON file or creates default."""
        if not self.config_file.parent.exists():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except Exception as e:
                print(f"[Config] Error loading config: {e}. Using defaults.")

        # Check environment fallback for API keys if empty
        if not self.data.get("gemini_api_key") and os.environ.get("GEMINI_API_KEY"):
            self.data["gemini_api_key"] = os.environ["GEMINI_API_KEY"]
        if not self.data.get("groq_api_key") and os.environ.get("GROQ_API_KEY"):
            self.data["groq_api_key"] = os.environ["GROQ_API_KEY"]

    def save(self) -> None:
        """Saves current configuration to file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def get_api_key(self) -> str:
        provider = self.get("provider", "gemini")
        if provider == "gemini":
            return self.get("gemini_api_key", "").strip()
        elif provider == "groq":
            return self.get("groq_api_key", "").strip()
        return ""
