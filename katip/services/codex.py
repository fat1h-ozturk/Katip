import json
import time
import subprocess
import sys
from typing import Optional
import requests

from ..prompts import build_groq_formatter_prompt

GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"

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
        
        cmd = [
            "codex", "exec", 
            "-c", 'sandbox_mode="read-only"',
            "-c", 'approval_policy="never"',
            "--skip-git-repo-check",
            "--json"
        ]
        if self.codex_model:
            cmd.extend(["-m", self.codex_model])
            
        cmd.append(prompt)
        
        try:
            # ASVS 1.2.5: pass arguments without a shell; decode CLI output as UTF-8.
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
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
