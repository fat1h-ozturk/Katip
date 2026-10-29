import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
import requests
from ..infrastructure.http_transport import http_post
from ..infrastructure.process_runner import run_process, clean_environment

from ..domain.errors import ProviderError, ConfigurationError
from ..domain.models import DictationResult
from .common import parse_output, formatter_input, publish_transcript, formatting_stage, start_stt, http_status_message
from .catalog import model_profile
from ..prompts import build_groq_formatter_prompt, build_whisper_prompt

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

@dataclass(frozen=True)
class AntigravityResult(DictationResult):
    provider: str = "agy"

class AntigravityService:
    def __init__(self, stt_provider: str = "", stt_api_key: str = "", stt_model: str = "",
                 agy_model: str = ""):
        self.stt_provider = stt_provider
        self.stt_api_key = stt_api_key.strip() if stt_api_key else ""
        self.stt_model = stt_model
        self.agy_model = agy_model.strip()

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=90, vocabulary_aliases=None) -> AntigravityResult:
        if not self.stt_api_key:
            raise ConfigurationError("Antigravity ile sesli dikte kullanabilmek için STT (Groq veya OpenAI) anahtarı gereklidir!")
            
        start_time = time.time()
        
        start_stt(self, len(audio_bytes))
        # 1. Transcription (Whisper fallback via Groq or OpenAI)
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": self.stt_model, "response_format": "text"}
        prompt, omitted_stt = build_whisper_prompt(custom_vocabulary, vocabulary_aliases)
        if prompt:
            data["prompt"] = prompt
        if language and language != "auto":
            data["language"] = language
            
        stt_headers = {"Authorization": f"Bearer {self.stt_api_key}"}
        stt_url = GROQ_AUDIO_URL if self.stt_provider == "groq" else OPENAI_AUDIO_URL
            
        try:
            stt_resp = http_post(stt_url, files=files, data=data, headers=stt_headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ProviderError("NETWORK_TIMEOUT", "stt", "Ses tanıma zaman aşımı; ham kayıt korunuyor.") from None
        except requests.exceptions.RequestException:
            raise ProviderError("NETWORK_CONNECTION", "stt", f"{self.stt_provider.upper()} STT bağlantı hatası.")
            
        if stt_resp.status_code != 200:
            raise ProviderError("HTTP_ERROR", "stt", http_status_message(self.stt_provider.upper() + " STT", stt_resp))
            
        raw_text = stt_resp.text.strip()
        if not raw_text:
            return AntigravityResult("", None, round(time.time() - start_time, 2))
            
        publish_transcript(self, raw_text, mode, custom_vocabulary, language, vocabulary_aliases)
        result = self.format_transcript(raw_text, mode, custom_vocabulary, language,
                                        vocabulary_aliases, timeout)
        return replace(result, latency=round(time.time() - start_time, 2), omitted_stt_terms=omitted_stt)

    @formatting_stage
    def format_transcript(self, raw_text, mode="dictation", custom_vocabulary=None,
                          language="auto", vocabulary_aliases=None, timeout=90, **_metadata):
        start_time = time.time()
        result = self._format(raw_text, mode, custom_vocabulary, language, vocabulary_aliases, timeout)
        return replace(result, mode=mode, language=language,
                       custom_vocabulary=tuple(custom_vocabulary or ()),
                       vocabulary_aliases=tuple((vocabulary_aliases or {}).items()),
                       stt_model=self.stt_model, llm_model=self.agy_model,
                       latency=round(time.time() - start_time, 2))

    def _format(self, raw_text, mode, custom_vocabulary, language, vocabulary_aliases, timeout):
        start_time = time.time()
        # 2. Formatting (Antigravity CLI)
        sys_prompt = build_groq_formatter_prompt(mode)
        
        serialized, _budget, omitted = formatter_input(raw_text, language, custom_vocabulary,
            vocabulary_aliases, sys_prompt, model_profile("antigravity", self.agy_model))
        if serialized is None:
            return AntigravityResult(raw_text, None, 0,
                "[CONTEXT_LIMIT] Metin bağlama sığmadı; eksiksiz ham metin korundu.",
                omitted_formatter_terms=omitted)
        prompt = sys_prompt + '\n\nRespond ONLY with a JSON object: {"text": "formatted text"}.\nUser data:\n' + serialized

        agy_cmd = _find_agy_binary()
        cmd = [agy_cmd, "-p", prompt, "--new-project"]
        
        if self.agy_model:
            cmd.extend(["--model", self.agy_model])

        env = clean_environment()
        user_local_bin = os.path.expanduser("~/.local/bin")
        current_path = env.get("PATH", "")
        if user_local_bin not in current_path.split(os.pathsep):
            env["PATH"] = f"{user_local_bin}{os.pathsep}{current_path}" if current_path else user_local_bin
            
        try:
            result = run_process(
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
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), "Antigravity işlemi başarısız; ham metin korundu.")
            
        try:
            answer_content = result.stdout.strip()
            
            formatted_text = parse_output(answer_content, allow_fence=True)
        except Exception:
            return AntigravityResult(raw_text, None, round(time.time() - start_time, 2), "Antigravity yanıtı JSON olarak ayrıştırılamadı.")
            
        return AntigravityResult(raw_text, formatted_text, round(time.time() - start_time, 2),
            omitted_formatter_terms=omitted)
