import json
import os
import re
import sys
import tempfile
import unicodedata
from uuid import uuid4
from copy import deepcopy
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict
from .runtime import app_id, profile

def get_config_dir() -> Path:
    """Returns standard config directory based on host OS."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / app_id()
        return Path.home() / "AppData" / "Roaming" / app_id()
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id()
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / app_id()
        return Path.home() / ".config" / app_id()

CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

SECRET_KEYS = ("gemini_api_key", "groq_api_key", "openai_api_key", "anthropic_api_key")

DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": 1,
    "secret_refs": {},
    "secret_history": [],
    "stt_provider": "auto",
    "provider": "gemini",  # "gemini", "groq", "openai", "claude"
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "gemini_model": DEFAULT_GEMINI_MODEL,
    "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
    "groq_stt_model": "whisper-large-v3-turbo",
    "groq_llm_model": "qwen/qwen3.8-27b",
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "openai_stt_model": "whisper-1",
    "openai_llm_model": "gpt-5-mini",
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "claude_llm_model": "claude-5-sonnet",
    "codex_model": "",
    "agy_model": "",
    "mode": "dictation",  # "dictation", "chat", "email", "prompt", "bullets"
    "hotkey": "Ctrl+Alt+Space",
    "trigger_mode": "toggle",  # "toggle" or "push_to_talk"
    "custom_vocabulary": ["Kâtip", "Gemini", "PySide6", "Wayland"],
    "vocabulary_aliases": {},
    "sound_effects": True,
    "vad_mode": 2,  # 1: Low, 2: Medium, 3: High
    "terminal_paste_mode": False,
    "language": "auto",  # "auto", "tr", "en"
    "restore_clipboard": False,
    "input_device_index": -1,
}


def normalize_vocabulary_aliases(value: Any) -> Dict[str, str]:
    """Normalize spelling hints without changing Turkish case or silently merging conflicts."""
    # ASVS 2.2.1/2.2.2: validate limits and normalized key collisions at the storage boundary.
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("Yazım eşleşmeleri en fazla 100 kayıtlık bir nesne olmalıdır.")
    result = {}
    for variant, spelling in value.items():
        if not isinstance(variant, str) or not isinstance(spelling, str):
            raise ValueError("Yazım eşleşmelerinin iki tarafı da metin olmalıdır.")
        if any(unicodedata.category(char) == "Cc" for char in variant + spelling):
            raise ValueError("Yazım eşleşmelerinde kontrol karakteri olamaz.")
        variant = unicodedata.normalize("NFC", variant.strip())
        spelling = unicodedata.normalize("NFC", spelling.strip())
        if (not variant or not spelling or len(variant) > 200 or len(spelling) > 200
                or "=>" in variant or "=>" in spelling):
            raise ValueError("Yazım eşleşmelerinde boş taraf, => işareti veya 200 karakteri aşan terim olamaz.")
        if variant in result and result[variant] != spelling:
            raise ValueError(f"Aynı varyant farklı yazımlara bağlanamaz: {variant}")
        result[variant] = spelling
    return result


def validate_config(values: Dict[str, Any]) -> Dict[str, Any]:
    """Validate persisted settings before using them in devices or requests."""
    if not isinstance(values, dict):
        raise ValueError("Ayarlar bir JSON nesnesi olmalıdır.")
    choices = {
        "provider": ("gemini", "groq", "openai", "claude", "codex", "agy"),
        "stt_provider": ("auto", "groq", "openai"),
        "mode": ("dictation", "chat", "email", "prompt", "bullets"),
        "trigger_mode": ("toggle", "push_to_talk"),
        "language": ("auto", "tr", "en"),
    }
    result = {}
    # ASVS 2.2.1: enforce types, enumerations and device/VAD bounds at the storage boundary.
    for key, value in values.items():
        if key not in DEFAULT_CONFIG:
            continue
        if type(value) is not type(DEFAULT_CONFIG[key]):
            raise ValueError(f"Geçersiz ayar türü: {key}")
        if key in choices and value not in choices[key]:
            raise ValueError(f"Geçersiz ayar: {key}")
        if key == "schema_version" and value != 1:
            raise ValueError("Desteklenmeyen ayar şeması; dosya değiştirilmedi.")
        if key == "secret_history" and (len(value) > 1000 or not all(isinstance(ref, str) and re.fullmatch(r"[a-f0-9]{32}", ref) for ref in value)):
            raise ValueError("Geçersiz anahtar geçmişi.")
        if key == "secret_refs" and (not all(k in SECRET_KEYS and isinstance(v, str) and re.fullmatch(r"[a-f0-9]{32}", v) for k, v in value.items())):
            raise ValueError("Geçersiz anahtar referansı.")
        if key == "vad_mode" and not 0 <= value <= 3:
            raise ValueError("VAD seviyesi 0–3 arasında olmalıdır.")
        if key == "input_device_index" and value < -1:
            raise ValueError("Geçersiz mikrofon seçimi.")
        if key == "custom_vocabulary" and not all(isinstance(item, str) for item in value):
            raise ValueError("Özel kelimeler metin olmalıdır.")
        if key == "vocabulary_aliases":
            value = normalize_vocabulary_aliases(value)
        if key.endswith("_model") and not re.fullmatch(r"[A-Za-z0-9._/-]*", value):
            raise ValueError(f"Geçersiz model adı: {key}")
        if key == "gemini_model" and value.startswith(("gemini-1.5-", "gemini-2.0-")):
            value = DEFAULT_GEMINI_MODEL
        result[key] = value
    return result

class ConfigManager:
    """Manages loading, saving, and accessing application configuration."""

    def __init__(self, config_file: Path = None, secret_store=None):
        self.config_file = config_file if config_file is not None else CONFIG_FILE
        self.secret_store = secret_store
        self.secret_error = ""
        self._read_only = False
        self._extra = {}
        self.data = deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        """Loads configuration from JSON file or creates default."""
        if not self.config_file.parent.exists():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

        # Migrate from legacy talk-to-write config if present
        if not self.config_file.exists() and not profile():
            legacy_config = self.config_file.parent.parent / "talk-to-write" / "config.json"
            if legacy_config.exists():
                try:
                    import shutil
                    shutil.copy2(legacy_config, self.config_file)
                    print("[Config] Migrated settings from talk-to-write to katip.")
                except Exception as e:
                    print(f"[Config] Migration error: {e}")

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if not isinstance(saved, dict):
                        raise ValueError("Ayar dosyası bir nesne olmalıdır.")
                    if saved.get("schema_version", 1) != 1:
                        self._read_only = True
                        self.secret_error = "Bu ayar dosyası daha yeni bir sürüme ait; dosya değiştirilmedi."
                    self._extra = {k: v for k, v in saved.items() if k not in DEFAULT_CONFIG}
                    for key, value in saved.items():
                        try:
                            self.data.update(validate_config({key: value}))
                        except ValueError:
                            print(f"[Config] Invalid setting ignored: {key}")
            except Exception as e:
                print(f"[Config] Error loading config: {e}. Using defaults.")

        if self.secret_store:
            for key, reference in self.data["secret_refs"].items():
                try:
                    value = self.secret_store.get(reference)
                    if value is None:
                        raise RuntimeError("Anahtar kasasındaki kayıt bulunamadı.")
                    self.data[key] = value
                except RuntimeError as error:
                    self.secret_error = str(error)

        # Check environment fallback for API keys if empty
        if not self.data.get("gemini_api_key") and os.environ.get("GEMINI_API_KEY"):
            self.data["gemini_api_key"] = os.environ["GEMINI_API_KEY"]
        if not self.data.get("groq_api_key") and os.environ.get("GROQ_API_KEY"):
            self.data["groq_api_key"] = os.environ["GROQ_API_KEY"]
        if not self.data.get("openai_api_key") and os.environ.get("OPENAI_API_KEY"):
            self.data["openai_api_key"] = os.environ["OPENAI_API_KEY"]
        if not self.data.get("anthropic_api_key") and os.environ.get("ANTHROPIC_API_KEY"):
            self.data["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]

    def save(self) -> None:
        """Atomically replace the file; never truncate the last valid settings."""
        temporary_path = None
        created_refs = []
        if self._read_only:
            raise RuntimeError("Daha yeni ayar şeması üzerine yazılamaz; önceki dosya korundu.")
        persisted = {**self._extra, **validate_config(self.data)}
        refs = dict(persisted["secret_refs"])
        try:
            if self.secret_store:
                for key in SECRET_KEYS:
                    value = self.data[key]
                    reference = refs.get(key)
                    if not value and reference:
                        # A locked/unavailable vault must not erase an existing reference.
                        if self.secret_error:
                            raise RuntimeError(self.secret_error)
                        refs.pop(key, None)
                    elif value:
                        if not reference or self.secret_store.get(reference) != value:
                            reference = uuid4().hex
                            created_refs.append(reference)
                            self.secret_store.put(reference, value)
                            refs[key] = reference
                    persisted[key] = ""
                persisted["secret_refs"] = refs
                history = set(self.data["secret_history"]) | set(self.data["secret_refs"].values()) | set(refs.values())
                if len(history) > 1000:
                    raise RuntimeError("Anahtar geçmişi sınırı aşıldı; önceki kayıtlar korundu.")
                persisted["secret_history"] = sorted(history)
            if self.config_file.exists() and not (self.config_file.parent / "config.previous.json").exists():
                # Preserve one rollback copy with user-only permissions.
                backup = self.config_file.parent / "config.previous.json"
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(self.config_file.read_bytes())
                    handle.flush()
                    os.fsync(handle.fileno())
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_file.parent,
                                             prefix=".config-", suffix=".tmp", delete=False) as f:
                temporary_path = Path(f.name)
                json.dump(persisted, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.config_file)
            self.data["secret_refs"] = refs
            self.data["secret_history"] = persisted["secret_history"]
        except Exception as e:
            if self.secret_store:
                for reference in created_refs:
                    with suppress(Exception):
                        self.secret_store.delete(reference)
            raise RuntimeError("Ayarlar kaydedilemedi; önceki ayar dosyası korundu.") from e
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.update({key: value})

    def update(self, values: Dict[str, Any]) -> None:
        """Save a settings form once and roll back memory if persistence fails."""
        updated = {**self.data, **validate_config(values)}
        previous = self.data
        self.data = updated
        try:
            self.save()
        except Exception:
            self.data = previous
            raise

    def get_api_key(self) -> str:
        provider = self.get("provider", "gemini")
        if provider == "gemini":
            return self.get("gemini_api_key", "").strip()
        elif provider == "groq":
            return self.get("groq_api_key", "").strip()
        elif provider == "openai":
            return self.get("openai_api_key", "").strip()
        elif provider == "claude":
            return self.get("anthropic_api_key", "").strip()
        if provider in ("codex", "agy"):
            return (self.get("groq_api_key", "") or self.get("openai_api_key", "")).strip()
        return ""
