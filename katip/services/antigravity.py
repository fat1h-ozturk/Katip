import json
import time
import subprocess
from typing import Optional
import requests

from ..prompts import build_groq_formatter_prompt

GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"

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
        
        cmd = ["agy", "-p", prompt, "--new-project"]
        
        if self.agy_model:
            cmd.extend(["--model", self.agy_model])
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
