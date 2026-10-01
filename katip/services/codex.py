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


def _find_codex_binary() -> str:
    """Find the 'codex' executable, checking PATH and common user/system install locations."""
    # 1. Standard PATH lookup
    try:
        found = shutil.which("codex")
        if found:
            return found
    except Exception:
        pass

    # 2. Check common user and system local bin directories
    candidates = [
        os.path.expanduser("~/.local/bin/codex"),
        os.path.expanduser("~/bin/codex"),
        os.path.expanduser("~/.cargo/bin/codex"),
        "/usr/local/bin/codex",
        "/usr/bin/codex",
        "/bin/codex",
    ]
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidates.extend([
                os.path.join(local_app_data, "Programs", "Codex", "codex.exe"),
                os.path.join(local_app_data, "Programs", "codex", "codex.exe"),
                os.path.join(local_app_data, "codex", "codex.exe"),
            ])
        candidates.extend([
            os.path.expanduser(r"~\AppData\Local\Programs\Codex\codex.exe"),
            os.path.expanduser(r"~/.local/bin/codex.exe"),
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
            found_in_fallback = shutil.which("codex", path=search_path)
            if found_in_fallback:
                return found_in_fallback
        except Exception:
            pass

    return "codex"


class CodexResult:
    def __init__(self, raw_transcript: str, formatted_text: Optional[str], latency: float, warning: str = ""):
        self.raw_transcript = raw_transcript
        self.formatted_text = formatted_text
        self.latency = latency
        self.warning = warning

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else self.raw_transcript

class CodexService:
    def __init__(self, stt_provider: str = "", stt_api_key: str = "", stt_model: str = "",
                 codex_model: str = ""):
        self.stt_provider = stt_provider
        self.stt_api_key = stt_api_key.strip() if stt_api_key else ""
        self.stt_model = stt_model
        self.codex_model = codex_model.strip()

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=45, vocabulary_aliases=None) -> CodexResult:
        if not self.stt_api_key:
            raise ValueError("Codex ile sesli dikte kullanabilmek için STT (Groq veya OpenAI) anahtarı gereklidir!")
            
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
            return CodexResult("", None, round(time.time() - start_time, 2))
            
        # 2. Formatting (Codex CLI)
        sys_prompt = build_groq_formatter_prompt(mode)
        
        # Talimat ve ham metin
        user_data = json.dumps({"transcript": raw_text, "language": language,
                                "custom_vocabulary": custom_vocabulary or [],
                                "vocabulary_aliases": vocabulary_aliases or {}}, ensure_ascii=False)
        prompt = f"{sys_prompt}\n\n---\n\nCRITICAL: Respond ONLY with a valid JSON object. Exact format: {{\"text\": \"formatted text here\"}}\n\nUser data:\n{user_data}"
        
        codex_cmd = _find_codex_binary()
        cmd = [
            codex_cmd, "exec", 
            "-c", 'sandbox_mode="read-only"',
            "-c", 'approval_policy="never"',
            "--skip-git-repo-check",
            "--json"
        ]
        if self.codex_model:
            cmd.extend(["-m", self.codex_model])
            
        cmd.append(prompt)

        env = os.environ.copy()
        user_local_bin = os.path.expanduser("~/.local/bin")
        current_path = env.get("PATH", "")
        if user_local_bin not in current_path.split(os.pathsep):
            env["PATH"] = f"{user_local_bin}{os.pathsep}{current_path}" if current_path else user_local_bin
        
        try:
            # ASVS 1.2.5: pass arguments without a shell; decode CLI output as UTF-8.
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
            return CodexResult(raw_text, None, round(time.time() - start_time, 2), "Sistemde 'codex' komutu bulunamadı. Lütfen Codex Desktop'ın yüklü olduğundan ve PATH'te olduğundan emin olun.")
        except subprocess.TimeoutExpired:
            return CodexResult(raw_text, None, round(time.time() - start_time, 2), "Codex yanıt vermedi (Zaman aşımı).")
            
        if result.returncode != 0:
            return CodexResult(raw_text, None, round(time.time() - start_time, 2), f"Codex Hatası: {result.stderr.strip()}")
            
        try:
            # --json emits JSONL events, not a single answer object.
            answer_content = ""
            completed = False
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("type") in ("error", "turn.failed"):
                    raise ValueError("Codex işlemi tamamlanamadı")
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        answer_content = item.get("text", "")
                if event.get("type") == "turn.completed":
                    completed = True
            if not completed or not isinstance(answer_content, str) or not answer_content.strip():
                raise ValueError("Codex yanıtı tamamlanmadı")
            
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
            
            # ASVS 2.2.1: accept only the requested non-empty text field.
            if not isinstance(inner_parsed, dict):
                raise ValueError("Geçersiz yanıt")
            formatted_text = inner_parsed.get("text")
            if not isinstance(formatted_text, str) or not formatted_text.strip():
                raise ValueError("Boş veya geçersiz metin")
        except Exception:
            return CodexResult(raw_text, None, round(time.time() - start_time, 2), "Codex yanıtı JSON olarak ayrıştırılamadı.")
            
        return CodexResult(raw_text, formatted_text, round(time.time() - start_time, 2))
