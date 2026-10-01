import json
import time
from typing import Optional, List, Dict
import requests

from ..prompts import build_groq_formatter_prompt

OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

class OpenAIResult:
    def __init__(self, raw_transcript: str, formatted_text: Optional[str], latency: float, warning: str = ""):
        self.raw_transcript = raw_transcript
        self.formatted_text = formatted_text
        self.latency = latency
        self.warning = warning

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else self.raw_transcript

class OpenAIService:
    def __init__(self, api_key: str, stt_model: str = "whisper-1", llm_model: str = "gpt-4o-mini"):
        self.api_key = api_key.strip() if api_key else ""
        self.stt_model = stt_model or "whisper-1"
        self.llm_model = llm_model or "gpt-4o-mini"
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=30, vocabulary_aliases=None) -> OpenAIResult:
        if not self.api_key:
            raise ValueError("OpenAI API anahtarı bulunamadı!")
            
        start_time = time.time()
        
        # 1. Transcription (Whisper)
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": self.stt_model, "response_format": "text"}
        
        if language and language != "auto":
            data["language"] = language
            
        try:
            stt_resp = self._session.post(OPENAI_AUDIO_URL, files=files, data=data, timeout=timeout)
        except requests.exceptions.RequestException:
            raise RuntimeError("OpenAI STT bağlantı hatası.")
            
        if stt_resp.status_code != 200:
            raise RuntimeError(f"OpenAI STT API Hatası (HTTP {stt_resp.status_code})")
            
        raw_text = stt_resp.text.strip()
        if not raw_text:
            return OpenAIResult("", None, round(time.time() - start_time, 2))
            
        # 2. Formatting (GPT)
        sys_prompt, omitted = build_groq_formatter_prompt(mode, custom_vocabulary or [], vocabulary_aliases or {})
        
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": raw_text}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        
        try:
            llm_resp = self._session.post(OPENAI_CHAT_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        except requests.exceptions.RequestException:
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), "LLM Bağlantı Hatası: Ham metin korundu.")
            
        if llm_resp.status_code != 200:
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), f"LLM API Hatası ({llm_resp.status_code}): Ham metin korundu.")
            
        try:
            content = llm_resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            formatted_text = parsed.get("text", "")
            if not formatted_text.strip():
                raise ValueError("Boş JSON yanıtı")
        except (KeyError, ValueError, json.JSONDecodeError):
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), "LLM Yanıtı Ayrıştırılamadı: Ham metin korundu.")
            
        return OpenAIResult(raw_text, formatted_text, round(time.time() - start_time, 2))
