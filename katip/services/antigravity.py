import json
import os
import shutil
import subprocess
import sys
import time
from typing import Optional
import requests

from ..prompts import build_groq_formatter_prompt

GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"


def _find_agy_binary() -> str:
    """Find the 'agy' executable, checking PATH and common user/system install locations."""
    # 1. Standard PATH lookup
    try:
        found = shutil.which("agy")
        if found:
            return found
    except Exception:
        pass

    # 2. Check common user and system local bin directories
    candidates = [
        os.path.expanduser("~/.local/bin/agy"),
        os.path.expanduser("~/bin/agy"),
        os.path.expanduser("~/.cargo/bin/agy"),
        "/usr/local/bin/agy",
        "/usr/bin/agy",
        "/bin/agy",
    ]
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidates.extend([
                os.path.join(local_app_data, "Programs", "agy", "agy.exe"),
                os.path.join(local_app_data, "agy", "agy.exe"),
            ])
        candidates.extend([
            os.path.expanduser(r"~\AppData\Local\Programs\agy\agy.exe"),
            os.path.expanduser(r"~/.local/bin/agy.exe"),
        ])

    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # 3. Fallback search via shutil.which across common directories (handles PATHEXT etc.)
    fallback_dirs = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/bin"),
        os.path.expanduser("~/.cargo/bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    search_path = os.pathsep.join(d for d in fallback_dirs if os.path.isdir(d))
    if search_path:
        try:
            found_in_fallback = shutil.which("agy", path=search_path)
            if found_in_fallback:
                return found_in_fallback
        except Exception:
            pass

    return "agy"

class AntigravityResult:
    def __init__(self, raw_transcript: str, formatted_text: Optional[str], latency: float, warning: str = ""):
        self.raw_transcript = raw_transcript
        self.formatted_text = formatted_text
        self.latency = latency
        self.warning = warning

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else self.raw_transcript

class AntigravityService:
    def __init__(self, stt_provider: str = "", stt_api_key: str = "", stt_model: str = "",
                 agy_model: str = ""):
        self.stt_provider = stt_provider
        self.stt_api_key = stt_api_key.strip() if stt_api_key else ""
        self.stt_model = stt_model
        self.agy_model = agy_model.strip()

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=60, vocabulary_aliases=None) -> AntigravityResult:
        if not self.stt_api_key:
            raise ValueError("Antigravity ile sesli dikte kullanabilmek için STT (Groq veya OpenAI) anahtarı gereklidir!")
            
        start_time = time.time()
        
        # 1. Transcription (Whisper fallback via Groq or OpenAI)
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": self.stt_model, "response_format": "text"}
        if language and language != "auto":
            data["language"] = language
            
        stt_headers = {"Authorization": f"Bearer {self.stt_api_key}"}
        stt_url = GROQ_AUDIO_URL if self.stt_provider == "groq" else OPENAI_AUDIO_URL
            
        try:
            stt_resp = requests.post(stt_url, files=files, data=data, headers=stt_headers, timeout=timeout)
        except requests.exceptions.RequestException:
            raise RuntimeError(f"{self.stt_provider.upper()} STT bağlantı hatası.")
            
        if stt_resp.status_code != 200:
            raise RuntimeError(f"{self.stt_provider.upper()} STT API Hatası (HTTP {stt_resp.status_code})")
            
        raw_text = stt_resp.text.strip()
        if not raw_text:
            return AntigravityResult("", None, round(time.time() - start_time, 2))
            
        # 2. Formatting (Antigravity CLI)
        sys_prompt = build_groq_formatter_prompt(mode)
        
        user_data = {
            "transcript": raw_text,
            "language": language,
            "custom_vocabulary": list(custom_vocabulary or []),
            "vocabulary_aliases": dict(vocabulary_aliases or {})
        }
        
        prompt = f"{sys_prompt}\n\n---\n\nCRITICAL: Respond ONLY with a valid JSON object. No markdown tags. Exact format: {{\"text\": \"formatted text here\"}}\n\nText to format:\n{json.dumps(user_data, ensure_ascii=False)}"
        
        agy_cmd = _find_agy_binary()
        cmd = [agy_cmd, "-p", prompt, "--new-project"]
        
        if self.agy_model:
            cmd.extend(["--model", self.agy_model])

        env = os.environ.copy()
        user_local_bin = os.path.expanduser("~/.local/bin")
        current_path = env.get("PATH", "")
        if user_local_bin not in current_path.split(os.pathsep):
            env["PATH"] = f"{user_local_bin}{os.pathsep}{current_path}" if current_path else user_local_bin
            
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                env=env,
            )
        except FileNotFoundError:
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), "Sistemde 'agy' komutu bulunamadı. Antigravity CLI'ın yüklü olduğundan emin olun.")
        except subprocess.TimeoutExpired:
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), "Antigravity yanıt vermedi (Zaman aşımı).")
            
        if result.returncode != 0:
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), f"Antigravity Hatası: {result.stderr.strip()}")
            
        try:
            answer_content = result.stdout.strip()
            
            # İçinde JSON var mı kontrol et
            inner_parsed = None
            try:
                inner_parsed = json.loads(answer_content)
            except json.JSONDecodeError:
                # Markdown blokları içinde olabilir
                if "```json" in answer_content:
                    extracted = answer_content.split("```json")[1].split("```")[0].strip()
                    inner_parsed = json.loads(extracted)
                elif "```" in answer_content:
                    extracted = answer_content.split("```")[1].split("```")[0].strip()
                    inner_parsed = json.loads(extracted)
            
            if inner_parsed and isinstance(inner_parsed, dict) and "text" in inner_parsed:
                formatted_text = inner_parsed["text"]
            else:
                formatted_text = answer_content
                
            if not formatted_text.strip():
                raise ValueError("Boş metin")
        except Exception:
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), "Antigravity yanıtı JSON olarak ayrıştırılamadı.")
            
        return AntigravityResult(raw_text, formatted_text, round(time.time() - start_time, 2))
