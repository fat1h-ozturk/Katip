import json
import time
from typing import Optional, List, Dict
import requests

from ..prompts import build_groq_formatter_prompt

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"

class ClaudeResult:
    def __init__(self, raw_transcript: str, formatted_text: Optional[str], latency: float, warning: str = ""):
        self.raw_transcript = raw_transcript
        self.formatted_text = formatted_text
        self.latency = latency
        self.warning = warning

    @property
    def text(self) -> str:
        return self.formatted_text if self.formatted_text is not None else self.raw_transcript

class ClaudeService:
    def __init__(self, api_key: str, llm_model: str = "claude-3-5-sonnet-20241022",
                 stt_provider: str = "", stt_api_key: str = "", stt_model: str = ""):
        self.api_key = api_key.strip() if api_key else ""
        self.llm_model = llm_model or "claude-3-5-sonnet-20241022"
        self.stt_provider = stt_provider
        self.stt_api_key = stt_api_key.strip() if stt_api_key else ""
        self.stt_model = stt_model
        self._session = requests.Session()
        self._session.headers.update({
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        })

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=30, vocabulary_aliases=None) -> ClaudeResult:
        if not self.api_key:
            raise ValueError("Anthropic API anahtarı bulunamadı!")
        if not self.stt_api_key:
            raise ValueError("Claude ile STT kullanabilmek için Groq veya OpenAI anahtarı gereklidir!")
            
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
            return ClaudeResult("", None, round(time.time() - start_time, 2))
            
        # 2. Formatting (Claude)
        # We need a system prompt. build_groq_formatter_prompt returns (prompt, omitted_count). 
        # But we must ask Claude to output raw text or parse JSON. Anthropic supports tool calls or just JSON.
        # We'll ask it to output ONLY valid JSON without markdown wrapping.
        sys_prompt, omitted = build_groq_formatter_prompt(mode, custom_vocabulary or [], vocabulary_aliases or {})
        
        # We add a strong instruction to Anthropic to output pure JSON.
        sys_prompt += "\n\nCRITICAL: Respond ONLY with a valid JSON object. No explanation, no markdown tags. Exact format: {\"text\": \"your formatted text here\"}"
        
        payload = {
            "model": self.llm_model,
            "max_tokens": 2048,
            "system": sys_prompt,
            "messages": [
                {"role": "user", "content": raw_text}
            ],
            "temperature": 0.1
        }
        
        try:
            llm_resp = self._session.post(ANTHROPIC_MESSAGES_URL, json=payload, timeout=timeout)
        except requests.exceptions.RequestException:
            return ClaudeResult(raw_text, None, round(time.time() - start_time, 2), "LLM Bağlantı Hatası: Ham metin korundu.")
            
        if llm_resp.status_code != 200:
            return ClaudeResult(raw_text, None, round(time.time() - start_time, 2), f"LLM API Hatası ({llm_resp.status_code}): Ham metin korundu.")
            
        try:
            content = llm_resp.json()["content"][0]["text"]
            # Claude sometimes ignores the instruction and adds markdown ```json
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            parsed = json.loads(content.strip())
            formatted_text = parsed.get("text", "")
            if not formatted_text.strip():
                raise ValueError("Boş JSON yanıtı")
        except (KeyError, ValueError, json.JSONDecodeError, IndexError):
            return ClaudeResult(raw_text, None, round(time.time() - start_time, 2), "LLM Yanıtı Ayrıştırılamadı: Ham metin korundu.")
            
        return ClaudeResult(raw_text, formatted_text, round(time.time() - start_time, 2))
