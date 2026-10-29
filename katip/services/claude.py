import time
from dataclasses import dataclass, replace
import requests
from ..infrastructure.http_transport import http_post
from ..infrastructure.http_transport import HttpSession

from ..domain.errors import ProviderError, ConfigurationError
from ..domain.models import DictationResult
from .catalog import model_profile
from .common import parse_output, formatter_input, publish_transcript, formatting_stage, start_stt, http_status_message
from ..prompts import build_groq_formatter_prompt, build_whisper_prompt

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"

@dataclass(frozen=True)
class ClaudeResult(DictationResult):
    provider: str = "claude"

class ClaudeService:
    def __init__(self, api_key: str, llm_model: str = "claude-3-5-sonnet-20241022",
                 stt_provider: str = "", stt_api_key: str = "", stt_model: str = ""):
        self.api_key = api_key.strip() if api_key else ""
        self.llm_model = llm_model or "claude-3-5-sonnet-20241022"
        self.stt_provider = stt_provider
        self.stt_api_key = stt_api_key.strip() if stt_api_key else ""
        self.stt_model = stt_model
        self._session = HttpSession()
        self._session.headers.update({
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        })

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=90, vocabulary_aliases=None) -> ClaudeResult:
        if not self.api_key:
            raise ConfigurationError("Anthropic API anahtarı bulunamadı!")
        if not self.stt_api_key:
            raise ConfigurationError("Claude ile STT kullanabilmek için Groq veya OpenAI anahtarı gereklidir!")
            
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
            return ClaudeResult("", None, round(time.time() - start_time, 2))
            
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
                       stt_model=self.stt_model, llm_model=self.llm_model,
                       latency=round(time.time() - start_time, 2))

    def _format(self, raw_text, mode, custom_vocabulary, language, vocabulary_aliases, timeout):
        start_time = time.time()
        # 2. Formatting (Claude)
        sys_prompt = build_groq_formatter_prompt(mode)
        profile = model_profile("claude", self.llm_model)
        serialized, budget, omitted = formatter_input(raw_text, language, custom_vocabulary,
            vocabulary_aliases, sys_prompt, profile)
        if serialized is None:
            return ClaudeResult(raw_text, None, 0, "[CONTEXT_LIMIT] Metin bağlama sığmadı; eksiksiz ham metin korundu.",
                omitted_formatter_terms=omitted)
        
        # We add a strong instruction to Anthropic to output pure JSON.
        sys_prompt += "\n\nCRITICAL: Respond ONLY with a valid JSON object. No explanation, no markdown tags. Exact format: {\"text\": \"your formatted text here\"}"
        
        payload = {
            "model": self.llm_model,
            "max_tokens": budget,
            "system": sys_prompt,
            "messages": [
                {"role": "user", "content": serialized}
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
            body = llm_resp.json()
            if body.get("stop_reason") != "end_turn":
                raise ValueError("Incomplete response")
            parts = body["content"]
            content = "".join(part["text"] for part in parts if part.get("type") == "text")
            formatted_text = parse_output(content, allow_fence=True)
        except (KeyError, ValueError, TypeError, AttributeError, IndexError):
            return ClaudeResult(raw_text, None, round(time.time() - start_time, 2), "LLM Yanıtı Ayrıştırılamadı: Ham metin korundu.")
            
        return ClaudeResult(raw_text, formatted_text, round(time.time() - start_time, 2),
            omitted_formatter_terms=omitted)
