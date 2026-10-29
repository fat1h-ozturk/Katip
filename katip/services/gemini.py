"""
Google Gemini Multimodal Audio-to-Formatted-Text Service.
"""

import base64
import time
from typing import List, Optional
import requests
from ..infrastructure.http_transport import HttpSession

from ..config import DEFAULT_GEMINI_MODEL
from ..prompts import build_system_prompt
from ..domain.models import DictationResult
from ..domain.errors import ProviderError, ConfigurationError
from .common import start_stt, http_status_message

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

class GeminiService:
    """Service for processing audio into polished text using Gemini Multimodal models."""

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL):
        self.last_warning = ""
        self.api_key = api_key.strip() if api_key else ""
        self.model = model or DEFAULT_GEMINI_MODEL
        self._session = HttpSession()

    def transcribe_and_format(
        self,
        audio_bytes: bytes,
        mode: str = "dictation",
        custom_vocabulary: Optional[List[str]] = None,
        timeout: int = 90
    ) -> DictationResult:
        """
        Sends audio WAV bytes to Gemini and returns the common dictation result.
        """
        self.last_warning = ""
        if not self.api_key:
            raise ConfigurationError(
                "Gemini API anahtarı bulunamadı!\n"
                "Lütfen Ayarlar'dan API anahtarınızı girin veya GEMINI_API_KEY tanımlayın."
            )

        start_time = time.time()
        start_stt(self, len(audio_bytes))
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        prompt = build_system_prompt(mode=mode, custom_vocabulary=custom_vocabulary)

        url = GEMINI_API_URL.format(model=self.model)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": b64_audio
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": min(8192, max(2048, len(audio_bytes) // 1600)),
            }
        }

        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ProviderError("NETWORK_TIMEOUT", "stt", "Ses işleme zaman aşımı; kayıt korunuyor.") from None
        except requests.exceptions.RequestException:
            # ASVS 16.5.1: never expose request URLs or provider error bodies.
            raise ProviderError("NETWORK_CONNECTION", "stt", "Gemini bağlantı hatası. Lütfen tekrar deneyin.") from None

        latency = round(time.time() - start_time, 2)

        if resp.status_code != 200:
            raise ProviderError("HTTP_ERROR", "stt", http_status_message("Gemini", resp))

        try:
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return DictationResult(None, "", latency, provider="gemini", mode=mode, llm_model=self.model)
            candidate = candidates[0]
            # ASVS 2.2.1: validate completion before accepting any text for injection.
            if candidate.get("finishReason") != "STOP":
                raise ProviderError("OUTPUT_INVALID", "stt", "Gemini yanıtı tamamlanamadı. Ses kaydı korunuyor; tekrar deneyin.")
            parts = candidate.get("content", {}).get("parts", [])
            texts = [part["text"] for part in parts if not part.get("thought") and "text" in part]
            if any(not isinstance(text, str) for text in texts):
                raise ValueError("invalid text")
            self.diagnostics.event("stt_finished", stage="stt")
            return DictationResult(None, "".join(texts), latency, provider="gemini", mode=mode,
                                   custom_vocabulary=tuple(custom_vocabulary or ()), llm_model=self.model)
        except RuntimeError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            raise ProviderError("OUTPUT_INVALID", "stt", "Gemini yanıtı ayrıştırılamadı.") from None
