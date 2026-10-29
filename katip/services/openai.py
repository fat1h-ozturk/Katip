import time
from dataclasses import dataclass, replace
import requests
from ..infrastructure.http_transport import HttpSession

from ..domain.errors import ProviderError, ConfigurationError
from ..domain.models import DictationResult
from .catalog import model_profile
from .common import parse_output, formatter_input, publish_transcript, formatting_stage, start_stt, http_status_message
from ..prompts import build_groq_formatter_prompt, build_whisper_prompt

OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

@dataclass(frozen=True)
class OpenAIResult(DictationResult):
    provider: str = "openai"

class OpenAIService:
    def __init__(self, api_key: str, stt_model: str = "whisper-1", llm_model: str = "gpt-4o-mini"):
        self.api_key = api_key.strip() if api_key else ""
        self.stt_model = stt_model or "whisper-1"
        self.llm_model = llm_model or "gpt-4o-mini"
        self._session = HttpSession()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def transcribe_and_format(self, audio_bytes: bytes, mode="dictation", custom_vocabulary=None,
                              language="auto", timeout=90, vocabulary_aliases=None) -> OpenAIResult:
        if not self.api_key:
            raise ConfigurationError("OpenAI API anahtarı bulunamadı!")
            
        start_time = time.time()
        
        start_stt(self, len(audio_bytes))
        # 1. Transcription (Whisper)
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": self.stt_model, "response_format": "text"}
        prompt, omitted_stt = build_whisper_prompt(custom_vocabulary, vocabulary_aliases)
        if prompt:
            data["prompt"] = prompt
        
        if language and language != "auto":
            data["language"] = language
            
        try:
            stt_resp = self._session.post(OPENAI_AUDIO_URL, files=files, data=data, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ProviderError("NETWORK_TIMEOUT", "stt", "Ses tanıma zaman aşımı; ham kayıt korunuyor.") from None
        except requests.exceptions.RequestException:
            raise ProviderError("NETWORK_CONNECTION", "stt", "OpenAI STT bağlantı hatası.")
            
        if stt_resp.status_code != 200:
            raise ProviderError("HTTP_ERROR", "stt", http_status_message("OpenAI STT", stt_resp))
            
        raw_text = stt_resp.text.strip()
        if not raw_text:
            return OpenAIResult("", None, round(time.time() - start_time, 2))
            
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
        # 2. Formatting (GPT)
        sys_prompt = build_groq_formatter_prompt(mode)
        profile = model_profile("openai", self.llm_model)
        serialized, budget, omitted = formatter_input(raw_text, language, custom_vocabulary,
            vocabulary_aliases, sys_prompt, profile)
        if serialized is None:
            return OpenAIResult(raw_text, None, 0, "[CONTEXT_LIMIT] Metin bağlama sığmadı; eksiksiz ham metin korundu.",
                omitted_formatter_terms=omitted)
        
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": serialized}
            ],
            "max_completion_tokens": budget,
            "store": False,
            "response_format": {"type": "json_object"}
        }
        
        if profile.temperature:
            payload["temperature"] = 0.1

        try:
            llm_resp = self._session.post(OPENAI_CHAT_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        except requests.exceptions.RequestException:
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), "LLM Bağlantı Hatası: Ham metin korundu.")
            
        if llm_resp.status_code != 200:
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), f"LLM API Hatası ({llm_resp.status_code}): Ham metin korundu.")
            
        try:
            choice = llm_resp.json()["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Incomplete response")
            formatted_text = parse_output(choice["message"]["content"])
        except (KeyError, ValueError, TypeError, AttributeError, IndexError):
            return OpenAIResult(raw_text, None, round(time.time() - start_time, 2), "LLM Yanıtı Ayrıştırılamadı: Ham metin korundu.")
            
        return OpenAIResult(raw_text, formatted_text, round(time.time() - start_time, 2),
            omitted_formatter_terms=omitted)
